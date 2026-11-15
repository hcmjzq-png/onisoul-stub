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
        self.assertEqual(self.api("politic/mission/changeState", **close)["reward"], {})
        self.assertEqual(state.load(self.pid)["resources"], before["resources"])
        self.assertIn("errorReason", self.api("politic/mission/setWorkingValue", missionId="po_mission_00000", indexes=[0], values=[0xfffffff]))

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
