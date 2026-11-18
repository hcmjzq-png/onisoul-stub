"""Normal HTTP/auth and atomic migration against an explicitly isolated MySQL."""
import copy
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

from app import db, state
from app.main import build_registry
from app.tables import TableCatalog
from app.transport.http_server import serve
from tests.test_gameplay import FIXTURES
from tools.repair_initial_mission import apply_plan, digest, repaired


@unittest.skipUnless(os.environ.get("ONI_TUTORIAL_MYSQL_TEST") == "1", "isolated MySQL opt-in required")
class TutorialMySQLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = int(os.environ["ONI_TUTORIAL_TEST_PORT"])
        if port == 3306 or not 1024 <= port <= 65535:
            raise RuntimeError("disposable loopback nondefault MySQL port required")
        cls.database = "oni_tutorial_test_" + uuid.uuid4().hex
        env = patch.dict(os.environ, {"ONI_DB_HOST": "127.0.0.1", "ONI_DB_PORT": str(port),
            "ONI_DB_USER": "root", "ONI_DB_PASSWORD": "", "ONI_DB_NAME": cls.database,
            "STUB_AUTH_MODE": "strict"})
        env.start(); cls.addClassCleanup(env.stop)
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                cur.execute(f"CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        cls.addClassCleanup(cls.drop_database)
        db.init_schema()

    @classmethod
    def drop_database(cls):
        if not re.fullmatch(r"oni_tutorial_test_[0-9a-f]{32}", cls.database):
            raise RuntimeError("unexpected cleanup database")
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                cur.execute(f"DROP DATABASE `{cls.database}`")

    def setUp(self):
        self.catalog = TableCatalog(FIXTURES, FIXTURES / "table_list.tsv")
        catalog_patch = patch("app.business.gameplay.default_catalog", return_value=self.catalog)
        catalog_patch.start(); self.addCleanup(catalog_patch.stop)
        self.httpd = serve("127.0.0.1", 0, build_registry())
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start(); self.addCleanup(self.close_server)
        self.account = "tut_" + uuid.uuid4().hex[:12]
        self.password = uuid.uuid4().hex
        self.request("/index.php/gwz/client/login/?page=register", dict(account=self.account, password=self.password))
        self.login()
        result = self.api("auth/gameLogin")
        self.assertFalse(result["succeeded"]); self.pid = result["playerId"]
        self.assertTrue(self.api("auth/registerName", username=self.account)["succeeded"])
        self.assertTrue(self.api("auth/createPlayer", username=self.account, countryId="country01",
                                 navigatorId="navi8000101", colorIndex="color1")["succeeded"])

    def close_server(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.worker.join(5)

    def request(self, path, form):
        con = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=10)
        try:
            con.request("POST", path, urlencode(form), {"Content-Type": "application/x-www-form-urlencoded"})
            response = con.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            con.close()

    def login(self):
        status, headers, _ = self.request("/index.php/gwz/client/login/", dict(account=self.account, password=self.password))
        self.assertEqual(status, 302)
        self.token = parse_qs(urlsplit(headers["Location"]).query)["token"][0]

    def api(self, name, **params):
        status, _, body = self.request("/api/" + name, {"params": json.dumps(dict(token=self.token, **params))})
        self.assertEqual(status, 200)
        return json.loads(body)

    def plan_for(self, *ids):
        entries = []
        for pid in ids:
            p = state.load(pid)
            p["missions"] = {"0": "C", "1": "O"}
            state.save(p, pid)
            entries.append(dict(player_id=pid, before_sha256=digest(p),
                                after_sha256=digest(repaired(p, self.catalog.load("politicMission")))))
        return dict(version=1, players=entries)

    def test_http_fresh_resume_and_reward_only_once(self):
        self.assertEqual(self.api("politic/mission/getStatesFromAllMissions")["states"], {"0": "C"})
        for target in ("opened", "accepted", "finished"):
            response = self.api("politic/mission/changeState", missionIds=["po_mission_00001"], states=[target])
            self.assertNotIn("errorReason", response)
            self.login()
            self.assertEqual(self.api("politic/mission/getMissionsInProgress")["missions"]["po_mission_00001"]["state"], target)
        close = dict(missionIds=["po_mission_00001"], states=["closed"])
        self.assertNotIn("errorReason", self.api("politic/mission/changeState", **close))
        before = state.load(self.pid)
        self.assertEqual(before["entity"]["exp"], 25)
        self.assertEqual(before["resources"]["credit"]["amount"], 0)
        self.assertNotIn("item11_0000501", before["items"])
        self.assertEqual(self.api("politic/mission/changeState", **close)["reward"], {})
        self.assertEqual(state.load(self.pid)["resources"], before["resources"])
        self.login()
        self.assertEqual(self.api("common/getPlayerParams")["entity"]["exp"], 25)
        self.assertIn("errorReason", self.api("politic/mission/setWorkingValue", missionId="po_mission_00000", indexes=[0], values=[0xfffffff]))

    def test_shop_whole_set_purchase_and_construction_over_http(self):
        player = state.load(self.pid)
        player["resources"]["gold"]["amount"] = 5000
        state.save(player, self.pid)
        self.assertIn("shop0000041", self.api("politic/shop/getShopItems", category="draft")["shopItems"])
        bought = self.api("politic/shop/buyShopItem", shopItemId="shop0000041",
                          storetable="shop_item", index=-1.0, quantity=1)
        self.assertTrue(bought["succeeded"], bought)
        self.assertNotIn("errorReason", bought)
        self.assertEqual(bought["result"]["item04_0200041"], 1)
        self.login()
        placed = self.api("politic/task/submitBuildTask", draftId="draft2000041", originCoord=[10, 10])
        self.assertTrue(placed["succeeded"], placed)
        self.assertNotIn("item04_0200041", state.load(self.pid)["items"])

    def test_unique_name_index_blocks_races_and_direct_create_bypass(self):
        from concurrent.futures import ThreadPoolExecutor
        import uuid
        from app.business.gameplay import GameplayService
        service = GameplayService(catalog=self.catalog)
        ids = ["name_" + uuid.uuid4().hex for _ in range(2)]
        for pid in ids:
            state.save(service._default_state(pid), pid)
        name = "昵称" + uuid.uuid4().hex[:8]
        def reserve(pid):
            return service.register_name({"username": name}, {"playerId": pid})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ids))
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        refused = next(r for r in results if not r["succeeded"])
        self.assertEqual(set(refused), {"succeeded", "now"})
        winner = next(pid for pid in ids if state.load(pid)["entity"]["username"] == name)
        loser = next(pid for pid in ids if pid != winner)
        before = state.load(loser)
        result = service.create_player(dict(username=name, countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), {"playerId": loser})
        self.assertFalse(result["succeeded"])
        self.assertEqual(state.load(loser), before)
        self.assertEqual(state.load(winner)["entity"]["playerId"], winner)

    def test_http_taken_name_remains_retryable_without_transport_error(self):
        other = "taken_" + uuid.uuid4().hex
        from app.business.gameplay import GameplayService
        service = GameplayService(catalog=self.catalog)
        value = service._default_state(other)
        value["entity"]["username"] = other
        state.save(value, other)
        before = state.load(self.pid)
        refused = self.api("auth/registerName", username=other)
        self.assertIs(refused["succeeded"], False)
        self.assertEqual(set(refused), {"succeeded", "now"})
        self.assertEqual(state.load(self.pid), before)
        # The same token can retry after the native name-in-use dialog closes.
        accepted = self.api("auth/registerName", username=self.account)
        self.assertIs(accepted["succeeded"], True)
        self.assertNotIn("errorReason", accepted)

    def test_name_migration_refuses_legacy_duplicates_without_changing_saves(self):
        import pymysql
        other = "legacy_name_" + uuid.uuid4().hex
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("ALTER TABLE players DROP INDEX uk_players_username, DROP COLUMN username_key")
        value = state.load(self.pid)
        value["entity"]["playerId"] = other; value["_revision"] = 0
        state.save(value, other)
        before = {pid: state.load(pid) for pid in (self.pid, other)}
        migration = (Path(__file__).resolve().parents[1] /
            "db/migrations/20261115_unique_player_names.sql").read_text()
        with self.assertRaises(pymysql.err.IntegrityError), db.connection() as con:
            with con.cursor() as cur:
                cur.execute(migration)
        self.assertEqual({pid: state.load(pid) for pid in before}, before)
        # Resolve only this test's deliberately duplicated name, then verify DDL.
        value = state.load(other); value["entity"]["username"] = other; state.save(value, other)
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute(migration)

    def test_atomic_repair_backup_and_persistent_reload(self):
        plan = self.plan_for(self.pid)
        before = state.load(self.pid)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "before.json"
            self.assertEqual(apply_plan(plan, self.catalog.load("politicMission"), path), 1)
            backup = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(backup["before"][self.pid], before)
        expected = copy.deepcopy(before); del expected["missions"]["1"]; expected["_revision"] += 1
        self.assertEqual(state.load(self.pid), expected)
        self.login()
        self.assertEqual(self.api("politic/mission/getStatesFromAllMissions")["states"], {"0": "C"})

    def test_second_update_failure_rolls_back_both_players(self):
        other = "repair_" + uuid.uuid4().hex
        value = state.load(self.pid); value["entity"]["playerId"] = other; value["_revision"] = 0
        value["entity"]["username"] = other
        state.save(value, other)
        plan = self.plan_for(self.pid, other)
        before = {pid: state.load(pid) for pid in (self.pid, other)}
        import pymysql.cursors
        real_execute = pymysql.cursors.DictCursor.execute
        writes = 0
        def fail_second(cursor, query, args=None):
            nonlocal writes
            if query.startswith("UPDATE players SET state_json"):
                writes += 1
                if writes == 2:
                    raise RuntimeError("injected second update failure")
            return real_execute(cursor, query, args)
        with tempfile.TemporaryDirectory() as folder, patch.object(pymysql.cursors.DictCursor, "execute", fail_second):
            path = Path(folder) / "before.json"
            with self.assertRaisesRegex(RuntimeError, "second update"):
                apply_plan(plan, self.catalog.load("politicMission"), path)
            self.assertTrue(path.exists())
        self.assertEqual({pid: state.load(pid) for pid in before}, before)

    def test_field_production_http_restart_and_sql_reward_once(self):
        from app.business.gameplay import GameplayService
        from app.business.registry import Registry
        from app.business.tutorial_production import TutorialFieldProduction
        from app.tables import TableError
        sample = json.loads((Path(__file__).parent / "fixtures/tutorial-production.json").read_text("utf-8"))
        original = self.catalog.load
        def load(name):
            try:
                value = original(name)
            except TableError:
                if name not in sample:
                    raise
                value = {}
            return {**value, **sample.get(name, {})}
        self.catalog.load = load
        p = state.load(self.pid)
        # Isolated database only: explicit constructed-field prerequisite.
        p["missions"].update({str(i): "C" for i in range(1, 5)})
        p["buildings"]["1"] = dict(instanceId=1, buildingTypeId=TutorialFieldProduction.FIELD,
            level=1, exp=0, status="none", durability=10001, deployedMapKey="map001", x=4, y=4)
        state.save(p, self.pid)
        now = [2000000000.75]
        def restart():
            self.close_server()
            service = GameplayService(catalog=self.catalog)
            service.tutorial_production.clock = lambda: now[0]
            registry = service.register(Registry()).register_contract_defaults()
            self.httpd = serve("127.0.0.1", 0, registry)
            self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.worker.start()
        restart()
        change = dict(missionIds=["po_mission_00005"], states=["accepted"])
        self.assertTrue(self.api("politic/mission/changeState", **change)["succeeded"])
        started = self.api("politic/task/submitProduceTask", buildingId=1, productId=TutorialFieldProduction.PRODUCT)
        self.assertTrue(started["succeeded"])
        self.assertEqual(started["dueTime"], 2000000010)
        before = state.load(self.pid)
        self.assertFalse(self.api("politic/task/completeTasks", buildingIds=[1])["succeeded"])
        self.assertEqual(state.load(self.pid), before)
        restart(); self.login()
        self.assertEqual(self.api("politic/map/getMapData")["producings"]["1"]["dueTime"], started["dueTime"])
        now[0] += 10
        result = self.api("politic/task/completeTasks", buildingIds=[1])
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000301"], 13)
        harvested = state.load(self.pid)
        self.assertEqual(harvested["resources"]["food"]["amount"], 13)
        self.assertEqual(harvested["buildings"]["1"]["exp"], 10)
        self.assertEqual(self.api("politic/task/completeTasks", buildingIds=[1])["producings"], {})
        self.assertEqual(state.load(self.pid), harvested)
        for target in ("finished", "closed"):
            self.assertTrue(self.api("politic/mission/changeState", missionIds=change["missionIds"], states=[target])["succeeded"])
        self.assertEqual(self.api("politic/mission/changeState", missionIds=change["missionIds"], states=["closed"])["reward"], {})
        restart(); self.login()
        self.assertEqual(self.api("politic/mission/getStatesFromAllMissions")["states"]["5"], "C")
        self.assertEqual(self.api("common/getPlayerParams")["resources"]["food"]["amount"], 313)

    def test_restaurant_build_seven_cycles_upgrade_and_restart_over_http_sql(self):
        from app.business.gameplay import GameplayService
        from app.business.registry import Registry
        from app.business.restaurant_production import RestaurantProduction
        from app.tables import TableError
        sample = json.loads((Path(__file__).parent / "fixtures/restaurant-production.json").read_text("utf-8"))
        original = self.catalog.load

        def load(name):
            try:
                value = original(name)
            except TableError:
                if name not in sample:
                    raise
                value = {}
            return {**value, **sample.get(name, {})}

        self.catalog.load = load
        # Isolated database: supply inventory/resources, then build through HTTP.
        player = state.load(self.pid)
        player["drafts"]["draft2000036"] = 1
        player["resources"]["food"]["amount"] = 3000
        player["resources"]["gold"]["amount"] = 5000
        player["actionPoints"]["politicPoint"]["point"] = 100
        state.save(player, self.pid)
        now = [2000000000.75]

        def restart():
            self.close_server()
            service = GameplayService(catalog=self.catalog)
            service.restaurant_production.clock = lambda: now[0]
            registry = service.register(Registry()).register_contract_defaults()
            self.httpd = serve("127.0.0.1", 0, registry)
            self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.worker.start()

        restart()
        built = self.api("politic/task/submitBuildTask", draftId="draft2000036", originCoord=[10, 10])
        self.assertTrue(built["succeeded"], built)
        key = built["buildingId"]
        self.assertTrue(self.api("politic/task/completeTasks", buildingIds=[key])["succeeded"])
        baseline = state.load(self.pid)
        for cycle in range(7):
            started = self.api("politic/task/submitProduceTask", buildingId=int(key), productId=RestaurantProduction.PRODUCT)
            self.assertTrue(started["succeeded"], started)
            self.assertNotIn("errorReason", started)
            self.assertEqual(started["dueTime"] - started["createdTime"], 900)
            active = state.load(self.pid)
            self.assertFalse(self.api("politic/task/completeTasks", buildingIds=[key])["succeeded"])
            self.assertEqual(state.load(self.pid), active)
            if cycle == 0:
                restart()
                self.login()
                self.assertEqual(self.api("politic/map/getMapData")["producings"][key]["dueTime"], started["dueTime"])
            now[0] += 900  # Only this isolated service clock; original duration stays 900.
            harvested = self.api("politic/task/completeTasks", buildingIds=[key])
            self.assertTrue(harvested["succeeded"], harvested)
            self.assertEqual(harvested["producings"][key]["reward"], {"item11_0000101": 125, "item11_0000501": 12})
            after = state.load(self.pid)
            self.assertEqual(self.api("politic/task/completeTasks", buildingIds=[key])["producings"], {})
            self.assertEqual(state.load(self.pid), after)
        result = self.api("politic/building/levelUpBuilding", buildingId=int(key))
        self.assertTrue(result["succeeded"], result)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (2, 0))
        after = state.load(self.pid)
        self.assertEqual(after["resources"]["gold"]["amount"], baseline["resources"]["gold"]["amount"] + 875 - 400)
        self.assertEqual(after["resources"]["food"]["amount"], baseline["resources"]["food"]["amount"] - 700 - 100)
        self.assertEqual(after["actionPoints"]["politicPoint"]["point"], baseline["actionPoints"]["politicPoint"]["point"] - 15)
        restart()
        self.login()
        mapped = self.api("politic/map/getMapData")
        self.assertEqual((mapped["buildings"][key]["level"], mapped["buildings"][key]["exp"]), (2, 0))
        self.assertEqual(mapped["producings"], {})

    def test_resource_buildings_multiple_recipes_restart_and_upgrade_over_http_sql(self):
        from app.business.gameplay import GameplayService
        from app.business.registry import Registry
        from app.tables import TableError
        from tests.test_fixed_resource_production import TABLES
        original = self.catalog.load

        def load(name):
            try:
                value = original(name)
            except TableError:
                if name not in TABLES:
                    raise
                value = {}
            return {**value, **TABLES.get(name, {})}

        self.catalog.load = load
        player = state.load(self.pid)
        # Owned temporary SQL player only; original drafts/costs/times are used.
        for draft in ("draft2000037", "draft2000039", "draft2000042"):
            player["drafts"][draft] = 1
        for resource in ("gold", "wood", "food", "iron"):
            player["resources"][resource]["amount"] = 50000
        player["actionPoints"]["politicPoint"].update(point=100, confirmTime=0.0)
        state.save(player, self.pid)
        now = [2000000000.0]

        def restart():
            self.close_server()
            service = GameplayService(catalog=self.catalog)
            service.fixed_production.clock = lambda: now[0]
            registry = service.register(Registry()).register_contract_defaults()
            self.httpd = serve("127.0.0.1", 0, registry)
            self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.worker.start()

        restart()
        self.api("common/getPlayerParams")
        instances = []
        for draft, coordinate in (("draft2000037", [10, 10]), ("draft2000039", [15, 15]),
                                  ("draft2000042", [20, 20])):
            built = self.api("politic/task/submitBuildTask", draftId=draft, originCoord=coordinate)
            self.assertTrue(built["succeeded"], built)
            key = built["buildingId"]
            instances.append(key)
            remaining = state.load(self.pid)["buildings"][key]["remainedClickCount"]
            for _ in range(int(remaining)):
                self.assertTrue(self.api("politic/task/progressBuildTask", buildingId=int(key))["succeeded"])
        completed = self.api("politic/task/completeTasks", buildingIds=instances)
        self.assertTrue(completed["succeeded"], completed)
        self.assertEqual(completed["completeCount"], 3)
        recipes = ["building200_037_01_01_1_1", "product060_012_01_01_1_1", "product060_020_01_01_1_1"]
        for key, product in zip(instances, recipes):
            result = self.api("politic/task/submitProduceTask", buildingId=int(key), productId=product)
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["dueTime"] - result["createdTime"], TABLES["product"][product]["dueInterval"])
        active = state.load(self.pid)
        self.assertFalse(self.api("politic/task/completeTasks", buildingIds=instances[:2])["succeeded"])
        self.assertEqual(state.load(self.pid), active)
        restart()
        self.login()
        mapped = self.api("politic/map/getMapData")
        self.assertEqual(set(mapped["producings"]), set(instances))
        for index in sorted(range(len(recipes)), key=lambda i: TABLES["product"][recipes[i]]["dueInterval"]):
            key, product = instances[index], recipes[index]
            now[0] = 2000000000.0 + TABLES["product"][product]["dueInterval"]
            result = self.api("politic/task/completeTasks", buildingIds=[key])
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["buildings"][key]["exp"], TABLES["product"][product]["buildingExp"])
            after = state.load(self.pid)
            self.assertEqual(self.api("politic/task/completeTasks", buildingIds=[key])["producings"], {})
            self.assertEqual(state.load(self.pid), after)
        key, product = instances[0], recipes[0]
        for _ in range(6):
            self.assertTrue(self.api("politic/task/submitProduceTask", buildingId=int(key), productId=product)["succeeded"])
            now[0] += 900
            self.assertTrue(self.api("politic/task/completeTasks", buildingIds=[key])["succeeded"])
        result = self.api("politic/building/levelUpBuilding", buildingId=int(key))
        self.assertTrue(result["succeeded"], result)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (2, 0))
        restart()
        self.login()
        mapped = self.api("politic/map/getMapData")
        self.assertEqual(mapped["buildings"][key]["level"], 2)
        self.assertEqual(mapped["producings"], {})

        # Original collective-production and auto-harvest callbacks use one
        # start PP per building, then ten PP for the whole multi-harvest.
        before = state.load(self.pid)
        started = self.api("politic/task/submitBulkProduceTasks", buildingIds=instances, productIds=recipes)
        self.assertTrue(started["succeeded"], started)
        self.assertEqual(set(started["producings"]), set(instances))
        active = state.load(self.pid)
        self.assertEqual(active["actionPoints"]["politicPoint"]["point"],
                         before["actionPoints"]["politicPoint"]["point"] - 3)
        self.assertFalse(self.api("politic/task/completeTasks", buildingIds=instances)["succeeded"])
        self.assertEqual(state.load(self.pid), active)
        restart()
        self.login()
        self.assertEqual(set(self.api("politic/map/getMapData")["producings"]), set(instances))
        now[0] += 900
        harvested = self.api("politic/task/completeTasks", buildingIds=instances)
        self.assertTrue(harvested["succeeded"], harvested)
        self.assertEqual(set(harvested["producings"]), set(instances))
        after = state.load(self.pid)
        self.assertEqual(after["actionPoints"]["politicPoint"]["point"],
                         active["actionPoints"]["politicPoint"]["point"] - 10)
        self.assertEqual(after["buildings"][key]["level"], 2)
        self.assertEqual(self.api("politic/task/completeTasks", buildingIds=instances)["producings"], {})
        self.assertEqual(state.load(self.pid), after)

    def test_automatic_finite_cancel_and_accelerate_over_http_sql(self):
        from app.business.gameplay import GameplayService
        from app.business.registry import Registry
        from app.tables import TableError
        from tests.test_fixed_resource_production import TABLES
        from tests.test_production_lifecycle import EXTRA, CASES
        tables = {name: {**TABLES.get(name, {}), **EXTRA.get(name, {})} for name in {*TABLES, *EXTRA}}
        original = self.catalog.load

        def load(name):
            try:
                value = original(name)
            except TableError:
                if name not in tables:
                    raise
                value = {}
            return {**value, **tables.get(name, {})}

        self.catalog.load = load
        player = state.load(self.pid)
        player["drafts"].update(draft2000031=1, draft2000032=1, draft2000037=1)
        # Original Lv3 gold cap is 300,000, enough for ten 20,000-gold harvests.
        player["entity"]["level"] = 3
        for kind in ("gold", "wood", "food", "iron"):
            player["resources"][kind]["amount"] = 50000
        player["resources"]["credit"]["amount"] = 100
        player["actionPoints"]["politicPoint"].update(point=100, confirmTime=0.0)
        state.save(player, self.pid)
        now = [2000000000.0]

        def restart():
            self.close_server()
            service = GameplayService(catalog=self.catalog)
            for engine in (service.fixed_production, service.automatic_production, service.restaurant_production):
                engine.clock = lambda: now[0]
            registry = service.register(Registry()).register_contract_defaults()
            self.httpd = serve("127.0.0.1", 0, registry)
            self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.worker.start()

        restart()
        ids = []
        for draft, coord in (("draft2000031", [10, 10]), ("draft2000032", [15, 15]), ("draft2000037", [20, 20])):
            built = self.api("politic/task/submitBuildTask", draftId=draft, originCoord=coord)
            self.assertTrue(built["succeeded"], built)
            key = built["buildingId"]
            ids.append(key)
            for _ in range(state.load(self.pid)["buildings"][key]["remainedClickCount"]):
                self.assertTrue(self.api("politic/task/progressBuildTask", buildingId=int(key))["succeeded"])
        completed = self.api("politic/task/completeTasks", buildingIds=ids)
        self.assertTrue(completed["succeeded"], completed)
        self.assertEqual(set(completed["autoProducings"]), set(ids[:2]))
        furniture = ids[2]
        self.assertTrue(self.api("politic/task/submitProduceTask", buildingId=int(furniture), productId="building200_037_01_01_1_1")["succeeded"])
        active = state.load(self.pid)
        self.assertTrue(self.api("politic/task/cancelTasks", buildingIds=[furniture])["succeeded"])
        self.assertEqual(state.load(self.pid)["resources"], active["resources"])
        restart()
        self.login()
        mapped = self.api("politic/map/getMapData")
        self.assertEqual(set(mapped["producings"]), set(ids[:2]))
        water = ids[1]
        accelerated = self.api("politic/task/accelerateProduceTask", buildingId=int(water), id="produce_accel_0001", count=1)
        self.assertTrue(accelerated["succeeded"], accelerated)
        self.assertEqual(accelerated["producings"][water]["dueTime"], 2000006600)
        now[0] += 7200
        first = self.api("politic/task/completeTasks", buildingIds=ids[:2])
        self.assertTrue(first["succeeded"], first)
        self.assertEqual(first["buildings"][ids[0]]["durability"], 9)
        self.assertEqual(set(first["autoProducings"]), set(ids[:2]))
        upgraded = self.api("politic/building/levelUpBuilding", buildingId=int(water))
        self.assertTrue(upgraded["succeeded"], upgraded)
        self.assertEqual(upgraded["building"]["level"], 2)
        mine = ids[0]
        for _ in range(9):
            now[0] = state.load(self.pid)["produce"][mine]["dueTime"]
            harvested = self.api("politic/task/completeTasks", buildingIds=[mine])
            self.assertTrue(harvested["succeeded"], harvested)
        final = state.load(self.pid)
        self.assertNotIn(mine, final["buildings"])
        self.assertNotIn(mine, final["produce"])
        self.assertNotIn(mine, final["occupiedGrids"].values())
        self.assertIn(water, final["produce"])
        self.assertEqual(final["buildings"][water]["level"], 2)
        self.assertEqual(final["resources"]["credit"]["amount"], 99)
        restart()
        self.login()
        mapped = self.api("politic/map/getMapData")
        self.assertNotIn(mine, mapped["buildings"])
        self.assertEqual(mapped["producings"][water], final["produce"][water])

    def test_special_inventory_friend_atomic_help_and_evolution_survive_http_sql_restart(self):
        from app.business.gameplay import GameplayService
        from app.business.registry import Registry
        from app.business.social_services import SocialServices
        from app.business.friend_production import FriendProduction
        from app.tables import TableError
        from tests.test_fixed_resource_production import TABLES
        from tests.test_production_lifecycle import EXTRA as LIFECYCLE
        from tests.test_production_completion import EXTRA, CASES, EVOLVE, RESTAURANT
        tables = {}
        for group in (TABLES, LIFECYCLE, EXTRA):
            for name, rows in group.items():
                tables[name] = {**tables.get(name, {}), **rows}
        original = self.catalog.load

        def load(name):
            try:
                value = original(name)
            except TableError:
                if name not in tables:
                    raise
                value = {}
            return {**value, **tables.get(name, {})}

        self.catalog.load = load
        now = [2000000000.0]

        def restart():
            self.close_server()
            service = GameplayService(catalog=self.catalog)
            for engine in (service.fixed_production, service.automatic_production,
                           service.tutorial_production, service.restaurant_production):
                engine.clock = lambda: now[0]
            registry = service.register(Registry())
            social = SocialServices(service, atomic_players=state.atomic_players, clock=lambda: now[0])
            social.register(registry)
            FriendProduction(service, social).register(registry)
            self.httpd = serve("127.0.0.1", 0, registry.register_contract_defaults())
            self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.worker.start()

        restart()
        actor = (self.pid, self.account, self.password)
        owner_account, owner_password = "prod_" + uuid.uuid4().hex[:12], uuid.uuid4().hex
        self.request("/index.php/gwz/client/login/?page=register", dict(account=owner_account, password=owner_password))
        self.account, self.password = owner_account, owner_password
        self.login()
        owner_id = self.api("auth/gameLogin")["playerId"]
        self.assertTrue(self.api("auth/registerName", username=owner_account)["succeeded"])
        self.assertTrue(self.api("auth/createPlayer", username=owner_account, countryId="country01",
                                navigatorId="navi8000101", colorIndex="color1")["succeeded"])
        owner = (owner_id, owner_account, owner_password)

        def switch(account):
            self.pid, self.account, self.password = account
            self.login()

        for account in (actor, owner):
            player = state.load(account[0])
            player["entity"]["level"] = 100
            player["actionPoints"]["politicPoint"].update(point=25, confirmTime=0.0)
            for kind in ("gold", "wood", "food", "iron"):
                player["resources"][kind]["amount"] = 0
            state.save(player, account[0])
        switch(actor)
        self.assertTrue(self.api("friend/sendFriendOffer", friendPlayerId=owner_id)["result"])
        switch(owner)
        self.assertTrue(self.api("friend/feedbackFriendOffer", friendPlayerId=actor[0], reply="ok")["result"])

        # Isolated SQL prerequisites: original owned building snapshots. Other
        # HTTP tests cover draft costs and construction clicks independently.
        player = state.load(owner_id)
        player["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": CASES["friend"],
            "level": 1, "exp": 0, "status": "none", "durability": 10001,
            "deployedMapKey": "map001", "x": 10, "y": 10, "remainedClickCount": 0}}
        player["occupiedGrids"] = {"10,10": "1"}
        player["counters"].update(nextBuildingId=2, buildingCount=1)
        state.save(player, owner_id)
        switch(actor)
        mapped = self.api("friend/getFriendMapData2", friendPlayerId=owner_id, mapId=-1)
        self.assertIn("1", mapped["producings"])
        visit = self.api("friend/visitFriendMap", friendPlayerId=owner_id)
        self.assertIs(visit["isFirst"], False)
        self.assertEqual(visit["reward"], {})
        accelerated = self.api("friend/task/accelerateFriendProduceTask", friendPlayerId=owner_id,
                               mapId=0, buildingId=1, id="produce_accel_0001")
        self.assertTrue(accelerated["succeeded"], accelerated)
        now[0] = accelerated["producings"]["1"]["dueTime"]
        restart()
        switch(actor)
        before = {pid: state.load(pid) for pid in (actor[0], owner_id)}
        import pymysql.cursors
        real_execute = pymysql.cursors.DictCursor.execute
        writes = [0]

        def fail_second(cursor, query, args=None):
            if query.startswith("UPDATE players SET state_json"):
                writes[0] += 1
                if writes[0] == 2:
                    raise state.StateConflictError("isolated second-player failure")
            return real_execute(cursor, query, args)

        with patch.object(pymysql.cursors.DictCursor, "execute", fail_second):
            refused = self.api("friend/task/completeFriendTasks", friendPlayerId=owner_id, mapId=0, buildingId=1)
            self.assertFalse(refused["succeeded"], refused)
        self.assertEqual({pid: state.load(pid) for pid in before}, before)
        result = self.api("friend/task/completeFriendTasks", friendPlayerId=owner_id, mapId=0, buildingId=1)
        self.assertTrue(result["succeeded"], result)
        self.assertNotIn("errno", result)
        self.assertEqual(self.api("friend/task/completeFriendTasks", friendPlayerId=owner_id, mapId=0, buildingId=1)["errno"], 1)
        for pid in before:
            saved = state.load(pid)
            self.assertEqual(saved["resources"]["gold"]["amount"], 18000)
            self.assertEqual(saved["actionPoints"]["politicPoint"]["point"], 25)

        # Three original reward categories must use the same inventory keys on
        # harvest, after a service restart and through their query routes.
        for label in ("shrine", "tactics", "cannon"):
            player = state.load(actor[0])
            for kind in ("gold", "wood", "food", "iron"):
                player["resources"][kind]["amount"] = 5000000
            bid = CASES[label]
            player["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": bid, "level": 1, "exp": 0,
                "status": "none", "durability": tables["building"][bid]["durability"],
                "deployedMapKey": "map001", "x": 10, "y": 10, "remainedClickCount": 0}}
            player["produce"] = {}
            player["automaticResourceProductionV1"] = {}
            player["occupiedGrids"] = {"10,10": "1"}
            state.save(player, actor[0])
            mapped = self.api("politic/map/getMapData")
            if tables["building"][bid]["produceType"] == "auto":
                now[0] = mapped["producings"]["1"]["dueTime"]
            else:
                started = self.api("politic/task/submitProduceTask", buildingId=1,
                                   productId=tables["building"][bid]["products"][0])
                self.assertTrue(started["succeeded"], started)
                now[0] = started["dueTime"]
            result = self.api("politic/task/completeTasks", buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            for code, amount in result["producings"]["1"]["reward"].items():
                if code.startswith("item03_"):
                    key = tables["item03"][code]["parameterId"]
                    self.assertEqual(self.api("common/getTactics")[key]["amount"], amount)
                elif code.startswith(("item07_", "item15_")):
                    self.assertEqual(state.load(actor[0])["items"][code], amount)
            restart()
            switch(actor)

        player = state.load(actor[0])
        base = {"instanceId": 1, "buildingTypeId": RESTAURANT, "level": 10, "exp": 0,
                "status": "waiting", "durability": 10001, "deployedMapKey": "none", "x": 10, "y": 10,
                "remainedClickCount": 0}
        player["buildings"] = {"1": base, "2": {**base, "instanceId": 2}}
        player["produce"], player["automaticResourceProductionV1"], player["occupiedGrids"] = {}, {}, {}
        player["counters"].update(nextBuildingId=3, buildingCount=2)
        state.save(player, actor[0])
        result = self.api(EVOLVE, first=1, second=2)
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["building"]["buildingTypeId"], "building200_036_02_01_1_1")
        restart()
        switch(actor)
        self.assertEqual(set(self.api("politic/map/getMapData")["buildings"]), {"3"})
        self.assertFalse(self.api(EVOLVE, first=1, second=2)["succeeded"])
        player = state.load(actor[0])
        player["resources"]["food"]["amount"] = 5000  # Explicit isolated recipe prerequisite.
        state.save(player, actor[0])
        deployed = self.api("politic/building/deployBuilding", buildingId=3, originCoord=[10, 10])
        self.assertTrue(deployed["succeeded"], deployed)
        code = tables["building"][result["building"]["buildingTypeId"]]["products"][0]
        started = self.api("politic/task/submitProduceTask", buildingId=3, productId=code)
        self.assertTrue(started["succeeded"], started)
        now[0] = started["dueTime"]
        self.assertTrue(self.api("politic/task/completeTasks", buildingIds=[3])["succeeded"])
        final = state.load(actor[0])
        restart()
        switch(actor)
        self.assertEqual(self.api("politic/map/getMapData")["buildings"]["3"], final["buildings"]["3"])

    def test_commit_failure_preserves_old_state_and_backup(self):
        plan = self.plan_for(self.pid); before = state.load(self.pid)
        import pymysql.connections
        with tempfile.TemporaryDirectory() as folder, patch.object(pymysql.connections.Connection, "commit", side_effect=RuntimeError("commit failed")):
            path = Path(folder) / "before.json"
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                apply_plan(plan, self.catalog.load("politicMission"), path)
            self.assertTrue(path.exists())
        self.assertEqual(state.load(self.pid), before)


if __name__ == "__main__":
    unittest.main()
