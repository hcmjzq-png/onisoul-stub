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
