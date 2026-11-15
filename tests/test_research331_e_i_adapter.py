"""Run I's real adapter against a disposable durable SQL contract database.

SQLite's BEGIN IMMEDIATE serializes writers. Removing FOR UPDATE is dialect
translation, NOT a test of InnoDB's row locks/deadlocks. See verify_i_adapter.py.
"""
import json
import os
import re
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import db, state
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.social_services import SocialServices
from app.business.social_inbox_services import SocialInboxServices
from app.tables import TableCatalog


class _SqlConnection:
    def __init__(self, owner):
        self.owner = owner
        self.con = sqlite3.connect(owner.path, timeout=15)
        self.con.row_factory = sqlite3.Row
        self.con.execute("BEGIN IMMEDIATE")
        self.updates = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE players"):
            self.updates += 1
            if self.owner.fail_update == self.updates:
                raise RuntimeError("injected SQL update failure")
        self.result = self.con.execute(sql.replace(" FOR UPDATE", "").replace("%s", "?"), params)

    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row is not None else None

    def commit(self):
        if self.owner.fail_commit:
            raise RuntimeError("injected pre-commit failure")
        self.con.commit()

    def rollback(self):
        self.con.rollback()

    def close(self):
        self.con.close()


@unittest.skipUnless(hasattr(state, "atomic_players"), "requires I's atomic_players; run verify_i_adapter.py")
class Research331EIAdapterTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        scratch = root / "tests/fixtures/research331/e-social"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="e-sql-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "isolated.sqlite")
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("CREATE TABLE players (player_id TEXT PRIMARY KEY, state_json TEXT, updated_at REAL)")
        self.fail_update, self.fail_commit = None, False
        self.connector = patch.object(db, "_connect", side_effect=lambda **kw: _SqlConnection(self))
        self.connector.start()
        self.addCleanup(self.connector.stop)
        self.seed()

    def seed(self):
        root = Path(__file__).resolve().parents[1]
        self.now = 1000.
        self.catalog = TableCatalog(root / "tests/fixtures/gameplay/tables")
        self.tables = {name: json.loads((root / "tests/fixtures/social" / (name + ".json")).read_text())
                       for name in ("defines", "playerLevel")}
        for pid in ("a", "b", "c"):
            state.save({"entity": {"created": True, "playerId": pid, "username": pid,
                                   "country": "country01", "level": 1},
                "decks": {"avatar": {"id": 1, "grade": 1}},
                "characters": {"1": {"baseId": "chara1_00001", "grade": 1}},
                "resources": {key: {"amount": 0, "maxAmount": 100} for key in ("gold", "wood", "food", "iron")}}, pid)
        self.reload()

    def reload(self):
        self.service = GameplayService(catalog=self.catalog)
        self.social = SocialServices(self.service, atomic_players=state.atomic_players, clock=lambda: self.now)
        self.social.table = lambda name: self.tables[name]
        self.registry = Registry()
        self.social.register(self.registry)
        self.inbox = SocialInboxServices(self.service)
        self.inbox.register(self.registry)

    def call(self, name, actor, target=None, **kw):
        if target:
            kw["friendPlayerId"] = target
        return self.registry.dispatch("friend/" + name, kw, {"playerId": actor})

    def snapshot(self):
        return {pid: state.load(pid) for pid in ("a", "b", "c")}

    def test_durable_lifecycle_retry_revision_and_service_restart(self):
        self.assertTrue(self.call("sendFriendOffer", "a", "b")[1]["result"])
        before = self.snapshot()
        self.assertTrue(self.call("sendFriendOffer", "a", "b")[1]["result"])
        self.assertEqual(before, self.snapshot())
        self.reload()
        self.assertEqual(self.call("getFriends", "b", option="receive")[1]["a"]["status"], "receive")
        self.assertTrue(self.call("feedbackFriendOffer", "b", "a", reply="ok")[1]["result"])
        self.reload()
        self.assertEqual(state.load("a")["friends"], {"b": {}})
        self.assertEqual(state.load("b")["friends"], {"a": {}})
        self.assertTrue(self.call("dissolutionFriend", "a", "b")[1]["result"])
        self.assertEqual(self.call("updateFriendData", "b")[1]["remove"], {"a": "dissolved"})

    def test_second_update_and_commit_failure_roll_back_real_sql(self):
        for fault in ("second-update", "commit"):
            with self.subTest(fault=fault):
                before = self.snapshot()
                self.fail_update = 2 if fault == "second-update" else None
                self.fail_commit = fault == "commit"
                self.assertEqual(self.call("sendFriendOffer", "a", "b")[0], 500)
                self.fail_update, self.fail_commit = None, False
                self.assertEqual(before, self.snapshot())
        self.assertTrue(self.call("sendFriendOffer", "a", "b")[1]["result"])

    def test_two_service_instances_competing_accept_cannot_exceed_capacity(self):
        self.call("sendFriendOffer", "a", "b")
        self.call("sendFriendOffer", "c", "b")
        first = self.registry
        self.reload()  # distinct in-process lock sets, same durable store
        second = self.registry
        self.tables["playerLevel"]["1"]["friend"] = 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reg.dispatch, "friend/feedbackFriendOffer",
                       {"friendPlayerId": target, "reply": "ok"}, {"playerId": "b"})
                       for reg, target in ((first, "a"), (second, "c"))]
            results = [f.result(10) for f in futures]
        self.assertEqual(sum(result[1]["result"] for result in results), 1)
        self.assertEqual(len(state.load("b")["friends"]), 1)

    def test_expiry_transaction_conflicts_with_stale_single_player_save(self):
        self.call("sendFriendOffer", "a", "b")
        stale = state.load("a")
        self.now += 604800
        self.assertEqual(self.social.notifications({"playerId": "b"})["friendOffer"], 0.)
        self.assertEqual(state.load("a")["socialOffers"], {})
        with self.assertRaises(state.StateConflictError):
            state.save(stale, "a")

    def test_issuance_and_claim_rollback_and_persistent_retry(self):
        args = dict(issuance_id="admin-test-1", source={"kind": "administrator", "authority": "test",
                    "reference": "isolated"}, rewards={"item11_0000101": 7}, created_time=self.now)
        with state.atomic_players(("a",)) as rows:
            parcel = self.inbox.stage_parcel(rows["a"], **args)
        before = state.load("a")
        self.fail_commit = True
        with self.assertRaises(RuntimeError):
            with state.atomic_players(("a",)) as rows:
                self.inbox.resolve(rows["a"], {"responses": {parcel: "accept"}})
        self.fail_commit = False
        self.assertEqual(before, state.load("a"))
        with state.atomic_players(("a",)) as rows:
            self.inbox.resolve(rows["a"], {"responses": {parcel: "accept"}})
        self.reload()
        with state.atomic_players(("a",)) as rows:
            self.assertEqual(self.inbox.stage_parcel(rows["a"], **args), parcel)
            self.assertEqual(self.inbox.resolve(rows["a"], {"responses": {parcel: "accept"}})
                             ["successful"][parcel]["rewards"], {})
        self.assertEqual(state.load("a")["resources"]["gold"]["amount"], 7)

    def test_registered_inbox_concurrent_claim_single_delta_and_relogin_badge(self):
        with state.atomic_players(("a",)) as rows:
            parcel = self.inbox.stage_parcel(rows["a"], issuance_id="registry-claim",
                source={"kind": "administrator", "authority": "test", "reference": "race"},
                rewards={"item11_0000101": 7}, created_time=self.now)
        first = self.registry
        self.reload()
        second = self.registry
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda index: (first if index % 2 else second).dispatch(
                "inbox/resolveParcels", {"responses": {parcel: "accept"}}, {"playerId": "a"}), range(12)))
        deltas = [body.get("successful", {}).get(parcel, {}).get("rewards", {}).get("item11_0000101", 0)
                  for _, body in results]
        self.assertEqual(sum(deltas), 7)
        self.assertEqual(state.load("a")["resources"]["gold"]["amount"], 7)
        self.reload()
        self.assertEqual(self.social.notifications({"playerId": "a"})["inboxParcel"], 0.)


class _MysqlCursor:
    def __init__(self, connection):
        self.connection = connection
        self.cur = connection.con.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cur.close()

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE players"):
            self.connection.updates += 1
            if self.connection.owner.fail_update == self.connection.updates:
                raise RuntimeError("injected second MySQL UPDATE failure")
        return self.cur.execute(sql, params)

    def fetchone(self):
        return self.cur.fetchone()


class _MysqlConnection(_SqlConnection):
    def __init__(self, owner, real):
        self.owner, self.con, self.updates = owner, real, 0

    def cursor(self):
        return _MysqlCursor(self)


@unittest.skipUnless(hasattr(state, "atomic_players") and os.environ.get("ONI_E_MYSQL_TEST") == "1",
                     "explicit disposable loopback MySQL opt-in required")
class Research331EMySQLTest(Research331EIAdapterTest):
    @classmethod
    def setUpClass(cls):
        port = int(os.environ["ONI_E_TEST_PORT"])
        if port == 3306 or not 1024 <= port <= 65535:
            raise RuntimeError("nondefault disposable loopback MySQL port required")
        cls.database = "oni_e_test_" + uuid.uuid4().hex
        cls.env = patch.dict(os.environ, {
            "ONI_DB_HOST": "127.0.0.1", "ONI_DB_PORT": str(port), "ONI_DB_NAME": cls.database,
            "ONI_DB_USER": os.environ.get("ONI_E_TEST_USER", "root"),
            "ONI_DB_PASSWORD": os.environ.get("ONI_E_TEST_PASSWORD", ""),
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                cur.execute(f"CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
                cur.execute("SELECT VERSION() AS version")
                cls.version = cur.fetchone()["version"]
        cls.addClassCleanup(cls.cleanup_database)
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("CREATE TABLE players (player_id VARCHAR(64) PRIMARY KEY, "
                            "state_json LONGTEXT NOT NULL, updated_at DOUBLE NOT NULL) ENGINE=InnoDB")
        print(f"E isolated MySQL {cls.version}; fresh UUID database", flush=True)

    @classmethod
    def cleanup_database(cls):
        if not re.fullmatch(r"oni_e_test_[0-9a-f]{32}", cls.database):
            raise RuntimeError("unexpected cleanup target")
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                cur.execute(f"DROP DATABASE `{cls.database}`")

    def setUp(self):
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM players")
        self.fail_update, self.fail_commit = None, False
        real_connect = db._connect
        connector = patch.object(db, "_connect", side_effect=lambda **kw:
                                 _MysqlConnection(self, real_connect(**kw)))
        connector.start()
        self.addCleanup(connector.stop)
        self.seed()
