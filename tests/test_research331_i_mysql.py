"""Opt-in real MySQL tests. Create/drop only a new UUID-named test database.

Run results/i-infrastructure/run_mysql_validation.py against a disposable local
MySQL instance. Ordinary unittest discovery skips this module's database tests.
No production config, database, Unity client or network service is used.
"""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import re
import unittest
import uuid
from unittest.mock import patch

from app import db, state
from app.business.gameplay import GameplayService
from app.business.social_services import SocialServices


def transfer_worker(start, output, index, same_receipt=False):
    """spawn means independent interpreter, DB connection and process-local locks."""
    try:
        if not start.wait(15):
            raise RuntimeError("worker start timeout")
        for number in range(12):
            receipt = ("transfer", "once" if same_receipt else f"{index}-{number}")
            counter = ("transfer", "counter")
            with state.atomic(player_ids=("b", "a") if index % 2 else ("a", "b"),
                              shared_keys=(receipt, counter)) as unit:
                if unit.records[receipt] is not None:
                    continue
                unit.players["a"]["balance"] -= 1
                unit.players["b"]["balance"] += 1
                unit.records[receipt] = {"operation": "test-transfer", "amount": 1}
                shared = unit.records[counter]
                if shared is None:
                    shared = {"count": 0}
                    unit.records[counter] = shared
                shared["count"] += 1
        output.put(None)
    except BaseException as exc:
        output.put(f"{type(exc).__name__}: {exc}")


def hold_player_worker(ready, release, output):
    try:
        with state.atomic_players(("a",)):
            ready.set()
            if not release.wait(15):
                raise RuntimeError("lock release timeout")
        output.put(None)
    except BaseException as exc:
        output.put(f"{type(exc).__name__}: {exc}")


def stale_save_worker(ready, start, attempting, output):
    try:
        snapshot = state.load("a")
        ready.set()
        if not start.wait(15):
            raise RuntimeError("save start timeout")
        attempting.set()
        snapshot["balance"] += 100
        try:
            state.save(snapshot, "a")
        except state.StateConflictError:
            output.put("conflict")
        else:
            output.put("unexpected stale commit")
    except BaseException as exc:
        output.put(f"{type(exc).__name__}: {exc}")


@unittest.skipUnless(os.environ.get("ONI_I_MYSQL_TEST") == "1",
                     "isolated MySQL opt-in required; not an in-memory acceptance")
class MySQLTransactionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host = os.environ.get("ONI_I_TEST_HOST", "127.0.0.1")
        port = int(os.environ["ONI_I_TEST_PORT"])
        if host not in ("127.0.0.1", "::1") or not 1024 <= port <= 65535 or port == 3306:
            raise RuntimeError("use a disposable loopback MySQL on a nondefault port")
        cls.database = "oni_i_test_" + uuid.uuid4().hex
        cls.env = patch.dict(os.environ, {
            "ONI_DB_HOST": host, "ONI_DB_PORT": str(port), "ONI_DB_NAME": cls.database,
            "ONI_DB_USER": os.environ.get("ONI_I_TEST_USER", "root"),
            "ONI_DB_PASSWORD": os.environ.get("ONI_I_TEST_PASSWORD", ""),
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                # No IF NOT EXISTS: refuse a collision, never adopt another DB.
                cur.execute(f"CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4 "
                            "COLLATE utf8mb4_0900_ai_ci")
                cur.execute("SELECT VERSION() AS version")
                cls.version = cur.fetchone()["version"]
        cls.addClassCleanup(cls.drop_owned_database)
        db.init_schema()
        print(f"Real MySQL {cls.version}; fresh isolated database; spawn workers", flush=True)

    @classmethod
    def drop_owned_database(cls):
        if not re.fullmatch(r"oni_i_test_[0-9a-f]{32}", cls.database):
            raise RuntimeError("refusing unexpected cleanup target")
        with db.connection(select_database=False) as con:
            with con.cursor() as cur:
                cur.execute(f"DROP DATABASE `{cls.database}`")

    def setUp(self):
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM players")
                cur.execute("DELETE FROM shared_records")
        for pid in ("a", "b"):
            state.save({"entity": {"playerId": pid, "created": True, "level": 1},
                        "balance": 1000}, pid)

    def snapshot(self):
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT * FROM players ORDER BY player_id")
                players = cur.fetchall()
                cur.execute("SELECT * FROM shared_records ORDER BY namespace, record_key")
                return players, cur.fetchall()

    def workers(self, same_receipt=False):
        ctx = multiprocessing.get_context("spawn")
        start, output = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=transfer_worker,
                                args=(start, output, index, same_receipt)) for index in range(4)]
        try:
            for process in processes:
                process.start()
            start.set()
            results = [output.get(timeout=35) for _ in processes]
            self.assertEqual(results, [None] * 4)
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
            output.close()

    def test_01_reverse_order_multiprocess_transfer_shared_counter_and_reload(self):
        self.workers()
        self.assertEqual(state.load("a")["balance"], 952)
        self.assertEqual(state.load("b")["balance"], 1048)
        self.assertEqual(state.load("a")["_revision"], 49)
        with state.atomic(shared_keys=(("transfer", "counter"),)) as unit:
            self.assertEqual(unit.records[("transfer", "counter")]["count"], 48)
        self.assertEqual(len(self.snapshot()[1]), 49)

    def test_02_unique_receipt_race_applies_once(self):
        self.workers(same_receipt=True)
        self.assertEqual(state.load("a")["balance"], 999)
        self.assertEqual(state.load("b")["balance"], 1001)
        self.assertEqual(state.load("a")["_revision"], 2)
        self.assertEqual(len(self.snapshot()[1]), 2)

    def test_03_body_exception_rolls_back_players_and_new_record(self):
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with state.atomic(player_ids=("b", "a"), shared_keys=(("receipt", "x"),)) as unit:
                unit.players["a"]["balance"] -= 5
                unit.players["b"]["balance"] += 5
                unit.records[("receipt", "x")] = {"done": True}
                raise RuntimeError("abort")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(unit.players["a"]["_revision"], 1)

    def test_04_sql_failure_after_player_update_rolls_back_all(self):
        before = self.snapshot()
        original = db._connect

        def connect(**kwargs):
            con = original(**kwargs)
            original_cursor = con.cursor

            def cursor(*args, **kw):
                cur = original_cursor(*args, **kw)
                execute = cur.execute

                def fail(sql, params=()):
                    if sql.startswith("UPDATE shared_records"):
                        # Prior UPDATE players statements have reached real MySQL.
                        raise RuntimeError("injected SQL failure")
                    return execute(sql, params)
                cur.execute = fail
                return cur
            con.cursor = cursor
            return con

        with patch.object(db, "_connect", side_effect=connect):
            with self.assertRaisesRegex(RuntimeError, "SQL failure"):
                with state.atomic(player_ids=("a", "b"), shared_keys=(("receipt", "x"),)) as unit:
                    unit.players["a"]["balance"] -= 5
                    unit.players["b"]["balance"] += 5
                    unit.records[("receipt", "x")] = {"done": True}
        self.assertEqual(self.snapshot(), before)

    def test_05_commit_failure_before_commit_and_retry(self):
        before = self.snapshot()
        original = db._connect

        def connect(**kwargs):
            con = original(**kwargs)
            def fail():
                raise RuntimeError("injected commit failure")
            con.commit = fail
            return con

        with patch.object(db, "_connect", side_effect=connect):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                with state.atomic_players(("a", "b")) as rows:
                    rows["a"]["balance"] -= 5
                    rows["b"]["balance"] += 5
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(rows["a"]["_revision"], 1)
        with state.atomic_players(("a", "b")) as rows:
            rows["a"]["balance"] -= 5
            rows["b"]["balance"] += 5
        self.assertEqual(state.load("b")["balance"], 1005)

    def test_06_existing_single_writer_cas_and_expected_revisions(self):
        stale = state.load("a")
        with state.atomic_players(("a", "b")) as rows:
            rows["a"]["balance"] += 1
        before = self.snapshot()
        with self.assertRaises(state.StateConflictError):
            state.save(stale, "a")
        with self.assertRaises(state.StateConflictError):
            with state.atomic(player_ids=("a", "b"), expected_players={"a": 1}):
                self.fail("stale CAS admitted")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(state.load("b")["_revision"], 1)

    def test_07_nested_standalone_save_and_bad_payload_cannot_half_commit(self):
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "nested database"):
            with state.atomic_players(("a", "b")) as rows:
                rows["a"]["balance"] += 1
                state.save(rows["b"], "b")
        with self.assertRaises((ValueError, TypeError)):
            with state.atomic_players(("a", "b")) as rows:
                rows["a"]["balance"] += 1
                rows["b"]["not_json"] = object()
        self.assertEqual(self.snapshot(), before)

    def test_08_missing_player_and_key_set_changes_fail(self):
        before = self.snapshot()
        for ids in (("a", "missing"), ("A", "a"), ("a", "a")):
            with self.assertRaises(ValueError):
                with state.atomic_players(ids):
                    self.fail("invalid transaction admitted")
        with self.assertRaises(ValueError):
            with state.atomic_players(("a", "b")) as rows:
                del rows["b"]
        self.assertEqual(self.snapshot(), before)

    def test_09_lock_timeout_is_full_rollback_then_explicit_retry(self):
        ctx = multiprocessing.get_context("spawn")
        ready, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
        process = ctx.Process(target=hold_player_worker, args=(ready, release, output))
        process.start()
        original = db._connect
        def connect(**kwargs):
            con = original(**kwargs)
            with con.cursor() as cur:
                cur.execute("SET SESSION innodb_lock_wait_timeout = 1")
            return con
        try:
            self.assertTrue(ready.wait(10))
            with patch.object(db, "_connect", side_effect=connect):
                with self.assertRaises(state.RetryableTransactionError):
                    with state.atomic_players(("b", "a")):
                        self.fail("locked transaction admitted")
        finally:
            release.set()
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join()
        self.assertIsNone(output.get(timeout=5))
        output.close()
        with state.atomic_players(("a", "b")) as rows:
            rows["a"]["balance"] += 1
        self.assertEqual(state.load("a")["balance"], 1001)

    def test_10_social_offer_accept_reload_dissolve_uses_real_adapter(self):
        service = GameplayService(load_state=state.load, save_state=state.save)
        social = SocialServices(service, atomic_players=state.atomic_players, clock=lambda: 1000)
        # Original small fixtures already used by E; no new rule constants.
        fixtures = Path(__file__).parent / "fixtures" / "social"
        tables = {n: json.loads((fixtures / (n + ".json")).read_text(encoding="utf-8"))
                  for n in ("defines", "playerLevel")}
        social.table = lambda name: tables[name]
        for method, actor, target, extra in (
            ("sendFriendOffer", "a", "b", {}),
            ("feedbackFriendOffer", "b", "a", {"reply": "ok"}),
        ):
            self.assertTrue(social.mutate(method, {"friendPlayerId": target, **extra},
                                         {"playerId": actor})["result"])
        self.assertIn("b", state.load("a")["friends"])
        self.assertIn("a", state.load("b")["friends"])
        self.assertTrue(social.mutate("dissolutionFriend", {"friendPlayerId": "b"},
                                     {"playerId": "a"})["result"])
        self.assertEqual(state.load("a")["friends"], {})
        self.assertEqual(state.load("b")["friends"], {})

    def test_11_shared_binary_identity_revision_and_tombstone(self):
        keys = (("snapshot", "X"), ("snapshot", "x"))
        with state.atomic(shared_keys=keys, expected_records={k: 0 for k in keys}) as unit:
            for key in keys:
                unit.records[key] = {"period": key[1]}
        before = self.snapshot()
        self.assertEqual(len(before[1]), 2)
        with self.assertRaises(state.StateConflictError):
            with state.atomic(shared_keys=keys, expected_records={keys[0]: 0}):
                pass
        with self.assertRaises(ValueError):
            with state.atomic(shared_keys=keys) as unit:
                unit.records[keys[0]] = None
        self.assertEqual(self.snapshot(), before)

    def test_12_read_only_and_bad_revision_preserve_all_bytes(self):
        before = self.snapshot()
        with state.atomic_players(("b", "a")):
            pass
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(state.StateConflictError):
            with state.atomic_players(("a", "b")) as rows:
                rows["a"]["_revision"] = 500
        self.assertEqual(self.snapshot(), before)

    def test_13_legacy_save_competes_with_locked_multiwriter(self):
        ctx = multiprocessing.get_context("spawn")
        ready, start, attempting, output = ctx.Event(), ctx.Event(), ctx.Event(), ctx.Queue()
        process = ctx.Process(target=stale_save_worker, args=(ready, start, attempting, output))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            with state.atomic_players(("a", "b")) as rows:
                rows["a"]["balance"] += 1
                rows["b"]["balance"] -= 1
                start.set()
                self.assertTrue(attempting.wait(10))
            self.assertEqual(output.get(timeout=10), "conflict")
            self.assertEqual(state.load("a")["balance"], 1001)
        finally:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join()
            output.close()

    def test_14_lost_commit_ack_is_not_replayed_and_receipt_recovers_result(self):
        original = db._connect
        def connect(**kwargs):
            con = original(**kwargs)
            commit = con.commit
            def lose_ack():
                commit()  # A real committed transaction cannot be undone by rollback.
                raise ConnectionError("commit acknowledgement lost")
            con.commit = lose_ack
            return con
        key = ("receipt", "ack-loss")
        with patch.object(db, "_connect", side_effect=connect):
            with self.assertRaises(ConnectionError):
                with state.atomic(player_ids=("a",), shared_keys=(key,)) as unit:
                    unit.players["a"]["balance"] += 1
                    unit.records[key] = {"applied": True}
        self.assertEqual(unit.players["a"]["_revision"], 1)
        with state.atomic(player_ids=("a",), shared_keys=(key,)) as recovered:
            self.assertTrue(recovered.records[key]["applied"])
            self.assertEqual(recovered.players["a"]["balance"], 1001)
            # The caller sees the receipt and does not repeat the mutation.
        self.assertEqual(state.load("a")["_revision"], 2)

    def test_15_json_scalar_type_changes_are_not_suppressed_by_python_equality(self):
        with state.atomic_players(("a",)) as rows:
            rows["a"]["flag"] = 1
        with state.atomic_players(("a",)) as rows:
            rows["a"]["flag"] = True
        self.assertIs(state.load("a")["flag"], True)
        self.assertEqual(state.load("a")["_revision"], 3)


if __name__ == "__main__":
    unittest.main()
