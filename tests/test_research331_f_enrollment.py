"""Isolated durable adapter contract tests; NOT a production database adapter.

Only temporary files and synthetic event times/allocations are used. Gameplay
and enrollment use the same player store. No campaign is declared in production.
"""
import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from app import state
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.war_campaigns_commands import enroll_turf_war
from app.business.war_campaigns_events import (
    close_turf_war, declare_turf_war, replay_turf_war, turf_war_phase,
)
from app.business.war_campaigns_services import WarEnrollmentServices
from app.business.war_campaigns_views import turf_enrollment
from app.tables import TableCatalog
from tools.gameplay_smoke import MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"
WAR = FIXTURES / "research331" / "f-war"
FIELD = "battlefield_0000101"
OTHER_FIELD = "battlefield_0000201"


def table(name):
    return json.loads((WAR / (name + ".json")).read_text(encoding="utf-8"))[name]


def declaration(**changes):
    values = dict(event_id="isolated-war", opens_at=100, closes_at=200, now=50,
                  country_teams={"country01": "east", "country02": "west"},
                  authorization_ref="isolated-test-only", countries=table("country_setting"),
                  battlefields=table("turf_war_battlefield"), catalogue=table("turf_war_battlefield_catalog"))
    values.update(changes)
    return declare_turf_war(**values)


class DurableTestStore:
    """Atomic replace of ONE temporary document, serialized across test services.

    Not a multi-process DB implementation. I must provide real shared locking.
    Crash/power-loss durability and MySQL are deliberately not claimed here.
    """
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.RLock()
        self.failure = None
        if not self.path.exists():
            self._commit({"players": {}, "events": {}})

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _commit(self, rows):
        if self.failure:
            raise self.failure
        pending = self.path.with_suffix(".pending")
        pending.write_text(json.dumps(rows, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(pending, self.path)

    def load(self, pid):
        with self.lock:
            return self._read()["players"].get(pid, {})

    def save(self, player, pid):
        with self.lock:
            db = self._read()
            previous = db["players"].get(pid, {})
            if player.get("_revision", 0) != previous.get("_revision", 0):
                raise state.StateConflictError("test player changed")
            saved = copy.deepcopy(player)
            saved["_revision"] = previous.get("_revision", 0) + 1
            db["players"][pid] = saved
            self._commit(db)
            player["_revision"] = saved["_revision"]

    def insert(self, event):
        with self.lock:
            replay_turf_war(event)
            db = self._read()
            key = event["plan"]["eventId"]
            if key in db["events"]:
                raise ValueError("event ID already used")
            db["events"][key] = event
            self._commit(db)

    @contextmanager
    def atomic(self, event_id, player_id):
        with self.lock:
            db = self._read()
            draft = {"event": db["events"].get(event_id), "player": db["players"].get(player_id)}
            before = copy.deepcopy(db)
            yield draft
            if db != before:
                self._commit(db)

    def event(self):
        with self.lock:
            return self._read()["events"]["isolated-war"]


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DurableTestStore(Path(tmp.name) / "isolated.json")
        self.sessions = MemorySessions()
        self.now = 100
        self.service, self.registry = self.services()
        self.session, _ = self.service._issue_login("research331-f")
        self.service.create_player({"username": "research331-f", "countryId": "country01",
                                   "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        self.pid = self.session["playerId"]
        self.store.insert(declaration())

    def services(self, **options):
        tables = FIXTURES / "gameplay" / "tables"
        service = GameplayService(catalog=TableCatalog(tables, tables / "table_list.tsv"),
                                  load_state=self.store.load, save_state=self.store.save,
                                  session_store=self.sessions)
        registry = Registry().register_contract_defaults()
        values = dict(event_id="isolated-war", atomic=self.store.atomic, clock=lambda: self.now)
        values.update(options)
        WarEnrollmentServices(service, **values).register(registry)
        return service, registry

    def call(self, api="turfWar/entryWar", params=None, *, session=True, registry=None):
        status, body = (registry or self.registry).dispatch(
            api, params or {}, self.session if session is True else session)
        self.assertEqual(status, 200)
        return body

    def select(self, field=FIELD, **kwargs):
        return self.call("turfWar/entryBattlefield", {"battlefield": field}, **kwargs)

    def test_real_entry_selection_reopen_and_expiry_without_combat_or_rewards(self):
        initial_player = self.store.load(self.pid)
        self.assertEqual(turf_enrollment(self.store.event(), self.pid, 100)["selfBelong"],
                         {"team": "none", "battlefield": "none"})
        self.assertEqual(self.call()["team"], "east")
        self.assertTrue(self.select()["succeeded"])
        # Reopen the durable store and service, issue a new login; no seeded snapshot.
        self.store = DurableTestStore(self.store.path)
        self.service, self.registry = self.services()
        self.session, _ = self.service._issue_login("research331-f")
        actual = turf_enrollment(self.store.event(), self.session["playerId"], 101)
        self.assertEqual(actual, {"selfBelong": {"team": "east", "battlefield": FIELD},
                                  "isMovable": False})
        self.assertEqual([e["kind"] for e in self.store.event()["journal"]], ["entered", "selected"])
        self.now = 200
        self.assertFalse(self.call()["succeeded"])
        self.assertFalse(self.select()["succeeded"])
        with self.store.atomic("isolated-war", self.pid) as draft:
            close_turf_war(draft["event"], 200)
            close_turf_war(draft["event"], 201)
        self.assertEqual(len(self.store.event()["journal"]), 3)
        self.assertEqual(turf_war_phase(self.store.event(), 201), "closed")
        self.assertEqual(self.store.load(self.pid), initial_player)
        self.assertNotIn("winner", self.store.event())
        self.assertNotIn("rewards", self.store.event())

    def test_absent_adapter_event_and_wrong_event_do_not_create_data(self):
        before = self.store.path.read_bytes()
        for values in ({"atomic": None}, {"event_id": None}, {"event_id": "absent"}):
            _, registry = self.services(**values)
            response = self.call(registry=registry)
            self.assertFalse(response["succeeded"])
            self.assertIn("no stub response", response["errorReason"])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_opening_and_closing_boundaries_and_clock_rollback(self):
        self.now = 99.999
        self.assertFalse(self.call()["succeeded"])
        self.assertEqual(self.store.event()["journal"], [])
        self.now = 100
        self.assertTrue(self.call()["succeeded"])
        self.now = 199.999
        self.assertTrue(self.select()["succeeded"])
        self.now = 199
        self.assertIn("backwards", self.call()["errorReason"])
        self.now = 200
        self.assertFalse(self.select()["succeeded"])
        for value in (True, float("nan"), float("inf"), -1):
            self.now = value
            self.assertFalse(self.call()["succeeded"])

    def test_query_and_retries_have_no_resource_deltas_or_extra_events(self):
        self.call()
        self.select()
        before = self.store.path.read_bytes()
        for _ in range(3):
            entered, selected = self.call(), self.select()
            self.assertEqual(set(entered), {"team", "succeeded", "now"})
            self.assertEqual(set(selected), {"succeeded", "now"})
            fragment = turf_enrollment(self.store.event(), self.pid, 100)
            fragment["selfBelong"]["team"] = "west"
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_selection_requires_entry_and_cannot_bypass_movement(self):
        self.assertFalse(self.select()["succeeded"])
        self.call()
        for field in ("battlefield01", "battlefield_0000102", "none", "", [], 1):
            self.assertFalse(self.select(field)["succeeded"])
        self.assertTrue(self.select()["succeeded"])
        self.assertIn("movement", self.select(OTHER_FIELD)["errorReason"])
        self.assertEqual(len(self.store.event()["journal"]), 2)

    def test_authentication_selectors_and_other_players_are_rejected(self):
        before = self.store.path.read_bytes()
        self.assertFalse(self.call(session=None)["succeeded"])
        for params in ({"country": "country02"}, {"team": "west"}, {"eventId": "other"},
                       {"now": 150}, {"playerId": self.pid}):
            self.assertFalse(self.call(params=params)["succeeded"])
        self.assertFalse(self.call(session={"playerId": "missing"})["succeeded"])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_second_player_enrolls_from_own_country_and_has_no_first_player_field(self):
        second, _ = self.service._issue_login("research331-f-2")
        self.service.create_player({"username": "research331-f-2", "countryId": "country01",
                                   "navigatorId": "navi8000101", "colorIndex": "color1"}, second)
        player = self.store.load(second["playerId"])
        player["entity"]["country"] = "country02"
        self.store.save(player, second["playerId"])
        self.call()
        self.select()
        self.assertEqual(self.call(session=second)["team"], "west")
        self.assertEqual(turf_enrollment(self.store.event(), second["playerId"], 100)["selfBelong"],
                         {"team": "west", "battlefield": "none"})

    def test_country_changes_do_not_reallocate_existing_enrollment(self):
        self.call()
        player = self.store.load(self.pid)
        player["entity"]["country"] = "country02"
        self.store.save(player, self.pid)
        before = self.store.path.read_bytes()
        self.assertIn("country changed", self.call()["errorReason"])
        self.assertIn("country changed", self.select()["errorReason"])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_concurrent_services_make_one_entry_and_one_choice(self):
        _, second = self.services()
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda i: self.call(registry=second if i % 2 else self.registry), range(24)))
        self.assertTrue(all(r["succeeded"] and r["team"] == "east" for r in replies))
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda i: self.select(FIELD if i % 2 else OTHER_FIELD,
                                                         registry=second if i % 2 else self.registry), range(24)))
        self.assertEqual(sum(r["succeeded"] for r in replies), 12)
        self.assertEqual(len(self.store.event()["journal"]), 2)

    def test_commit_failure_and_conflict_do_not_send_success_or_partially_save(self):
        before = self.store.path.read_bytes()
        self.store.failure = OSError("injected before atomic replace")
        status, response = self.registry.dispatch("turfWar/entryWar", {}, self.session)
        self.assertEqual(status, 500)
        self.assertIsNot(response.get("succeeded"), True)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.failure = state.StateConflictError("injected revision conflict")
        self.assertFalse(self.call()["succeeded"])
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.failure = None
        self.assertTrue(self.call()["succeeded"])
        self.assertEqual(len(self.store.event()["journal"]), 1)

    def test_closed_id_cannot_be_reused_and_closure_is_not_settlement(self):
        with self.assertRaises(ValueError):
            self.store.insert(declaration())
        with self.store.atomic("isolated-war", self.pid) as draft:
            close_turf_war(draft["event"], 200)
        with self.assertRaises(ValueError):
            self.store.insert(declaration())
        self.assertEqual(replay_turf_war(self.store.event()), ({}, True))
        self.assertEqual(self.store.event()["journal"], [{"seq": 1, "kind": "closed", "at": 200}])

    def test_no_automatic_normal_registration_or_other_war_routes(self):
        normal = self.service.register(Registry()).register_contract_defaults()
        for api in (*WarEnrollmentServices.APIS, "turfWar/moveBattlefield", "strategy/isAlive",
                    "turfWar/getSelfRecord", "turfWar/getSelfSituation", "turfWar/receiveTurfWarReward"):
            self.assertEqual(normal._handlers[api].__module__, "app.business.placeholders")
        registry = Registry()
        WarEnrollmentServices(self.service).register(registry, apis=frozenset())
        self.assertEqual(registry._handlers, {})
        with self.assertRaises(ValueError):
            WarEnrollmentServices(self.service).register(registry, apis=frozenset({"battle/getVsBattleLogs"}))

    def test_integration_patch_applies_to_fixed_baseline_and_is_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        patch = root / "docs/analysis/research-331/results/f-war/integration.patch"
        baseline = "8023c3fee8e525040d101fee8bf843b48b3256d3"
        with tempfile.TemporaryDirectory() as temp:
            sandbox = Path(temp)
            # Windows core.autocrlf may convert a checked-out .patch to CRLF.
            # Match the LF git blobs without depending on checkout configuration.
            normalized_patch = sandbox / "candidate.patch"
            normalized_patch.write_text(patch.read_text(encoding="utf-8"),
                                        encoding="utf-8", newline="\n")
            for name in ("app/business/turf_war.py", "docs/api_schema.md"):
                original = subprocess.run(["git", "show", baseline + ":" + name], cwd=root,
                                          check=True, capture_output=True).stdout
                target = sandbox / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
            subprocess.run(["git", "apply", "--check", str(normalized_patch)], cwd=sandbox,
                           check=True, capture_output=True)
            subprocess.run(["git", "apply", str(normalized_patch)], cwd=sandbox,
                           check=True, capture_output=True)
            namespace = {"__name__": "isolated_candidate_turf_war"}
            exec(compile((sandbox / "app/business/turf_war.py").read_text(encoding="utf-8"),
                         "candidate_turf_war.py", "exec"), namespace)
            registry = Registry()
            namespace["register"](registry)
            self.assertEqual(registry.known(), {"turfWar/getWarSituation"})
            wire = namespace["register_enrollment_components"]
            with self.assertRaises(ValueError):
                wire(registry, self.service, event_id="isolated-war", atomic=None, clock=lambda: 100)
            wire(registry, self.service, event_id="isolated-war", atomic=self.store.atomic, clock=lambda: 100)
            self.assertEqual(registry.known(), {"turfWar/getWarSituation", *WarEnrollmentServices.APIS})
            self.assertTrue(self.call(registry=registry)["succeeded"])
            self.assertTrue(self.select(registry=registry)["succeeded"])


class DeclarationAndJournalTests(unittest.TestCase):
    def test_missing_asset_vs_bad_row_reference(self):
        with self.assertRaisesRegex(ValueError, "stub has no assets"):
            declaration(catalogue={})
        bad = table("turf_war_battlefield")
        bad["battlefield01"]["catalogId"] = "missing"
        with self.assertRaisesRegex(ValueError, "no stub response"):
            declaration(battlefields=bad)

    def test_no_default_schedule_allocation_or_historical_import(self):
        for change in ({"now": 100}, {"closes_at": 100}, {"opens_at": True},
                       {"opens_at": float("nan")}, {"country_teams": {}},
                       {"country_teams": {"country01": "east"}},
                       {"country_teams": {"country01": "east", "country02": "east"}},
                       {"authorization_ref": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                declaration(**change)

    def test_corrupt_journal_rejected_as_a_whole_without_repair(self):
        event = declaration()
        player = {"entity": {"playerId": "p", "created": True, "country": "country01"}}
        enroll_turf_war(event, player, "p", now=100)
        enroll_turf_war(event, player, "p", now=101, battlefield=FIELD)
        bad_events = []
        for key, value in (("seq", 7), ("at", 200), ("battlefield", "none"), ("kind", "battleWon")):
            bad = copy.deepcopy(event)
            bad["journal"][1][key] = value
            bad_events.append(bad)
        bad = copy.deepcopy(event)
        bad["plan"]["countryTeams"]["country01"] = "west"
        bad_events.append(bad)
        bad = copy.deepcopy(event)
        bad["journal"][0]["playerId"] = "someone-else"
        bad_events.append(bad)
        bad = copy.deepcopy(event)
        bad["journal"].append({"seq": 3, "kind": "entered", "at": 102, "playerId": "p", "country": "country01"})
        bad_events.append(bad)
        for bad in bad_events:
            before = copy.deepcopy(bad)
            with self.assertRaises(ValueError):
                turf_enrollment(bad, "p", 102)
            self.assertEqual(bad, before)

    def test_no_early_close_and_read_does_not_write_closure(self):
        event = declaration()
        with self.assertRaises(ValueError):
            close_turf_war(event, 199)
        self.assertEqual(turf_war_phase(event, 200), "closed")
        self.assertEqual(event["journal"], [])
        close_turf_war(event, 200)
        self.assertEqual(len(event["journal"]), 1)


if __name__ == "__main__":
    unittest.main()
