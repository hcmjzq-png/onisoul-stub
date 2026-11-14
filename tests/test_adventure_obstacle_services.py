"""Synthetic authorized encounter; original disabled table rows are NOT enabled."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.adventure_obstacle_services import AdventureObstacleServices, section_at, displayed_cost
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
from app.state import StateConflictError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "event:23:1:1"


class ObstacleTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("B-obstacle-only")
        self.assertTrue(self.service.create_player(dict(username="obstacle", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), self.session)["succeeded"])
        player = self.saved()
        player["resources"]["gold"]["amount"] = 1500
        player["adventureV1"] = {"version": 1, "progress": {"event": {"last": {
            "quest": 23, "chapter": 1, "area": 1, "step": 1}}}, "obstacleReceipts": {}, "obstacles": {
                KEY: {"questType": "event", "quest": 23, "chapter": 1, "area": 1, "step": 1,
                      "eventId": "synthetic-instance-1", "section": 1, "eventSlot": 3, "status": "pending",
                      "resolution": {"category": "resource", "type": "gold", "needAmount": 1000,
                                     "reward": {}, "toInbox": {}}}}}
        self.save(player)

    def reload(self):
        self.service = GameplayService(catalog=TableCatalog(FIXTURES / "gameplay/tables",
            FIXTURES / "gameplay/tables/table_list.tsv"), load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.api = AdventureObstacleServices(self.service, authorize=lambda player, event: True)
        self.catalog = TableCatalog(FIXTURES / "adventure", FIXTURES / "adventure/table_list.tsv")
        self.api.table = self.catalog.load
        self.registry = Registry()
        self.api.register(self.registry)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, name="clearObstacle", **changes):
        params = dict(questType="event", questId=23, chapterId=1, areaId=1)
        params.update(changes)
        status, result = self.registry.dispatch("quest/" + name, params, self.session)
        self.assertEqual(status, 200, result)
        return result

    def test_pending_clear_relogin_retry_and_recovery(self):
        before = self.saved()
        info = self.call("getQuestEncountWorks")["obstacle"]["event"]
        self.assertEqual(info, dict(questId="quest_3_0023", chapter=1, area=1, step=1,
                                   category="resource", type="gold", needAmount=1000, amount=1500))
        result = self.call()
        self.assertTrue(result["isSuccess"])
        self.assertEqual(result["uses"], {"category": "resource", "gold": 1000})
        self.assertNotIn("reward", result)
        saved = self.saved()
        self.assertEqual(saved["resources"]["gold"]["amount"], 500)
        self.assertEqual(saved["adventureV1"]["progress"], before["adventureV1"]["progress"])
        self.assertEqual(saved["actionPoints"], before["actionPoints"])
        self.assertEqual(self.call("getQuestEncountWorks")["obstacle"], {})
        self.reload()
        self.session, _ = self.service._issue_login("B-obstacle-only")
        retry = self.call()
        self.assertEqual(retry["uses"], result["uses"])
        self.assertEqual(self.saved(), saved)

    def test_insufficient_and_exact_balance(self):
        player = self.saved()
        player["resources"]["gold"]["amount"] = 999
        self.save(player)
        self.assertFalse(self.call()["isSuccess"])
        self.assertEqual(self.saved(), player)
        player["resources"]["gold"]["amount"] = 1000
        self.save(player)
        self.assertTrue(self.call()["isSuccess"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 0)

    def test_parallel_requests_debit_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(), range(32)))
        self.assertTrue(all(result["isSuccess"] for result in results))
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 500)
        self.assertEqual(len(self.saved()["adventureV1"]["obstacleReceipts"]), 1)

    def test_default_denies_disabled_event_and_missing_authorization(self):
        before = self.saved()
        self.assertIs(self.catalog.load("quest_3_index")["23_1"]["enable"], False)
        for policy in (None, lambda p, e: False):
            self.api.authorize = policy
            self.assertIn("authorization", self.call()["errorReason"])
            self.assertEqual(self.saved(), before)

    def test_unowned_requests_and_untrusted_cost_fields(self):
        before = self.saved()
        for changes in ({"questId": 24}, {"areaId": 2}, {"questType": "story"}, {"questId": True}):
            self.assertIn("errorReason", self.call(**changes))
            self.assertEqual(self.saved(), before)
        self.assertTrue(self.call(needAmount=0, type="credit", playerId="victim")["isSuccess"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 500)
        status, body = self.registry.dispatch("quest/clearObstacle", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("authentication", body["errorReason"])
        other, _ = self.service._issue_login("B-other")
        _, body = self.registry.dispatch("quest/clearObstacle", dict(questType="event", questId=23,
            chapterId=1, areaId=1, playerId=self.session["playerId"]), other)
        self.assertIn("errorReason", body)

    def test_unsupported_or_corrupt_resolution_never_debits(self):
        baseline = self.saved()
        for field, value in (("reward", {"item": 1}), ("reward", None), ("toInbox", None),
                             ("category", "soul"), ("needAmount", 999), ("needAmount", True)):
            player = copy.deepcopy(baseline)
            player["adventureV1"]["obstacles"][KEY]["resolution"][field] = value
            self.save(player)
            self.assertIn("errorReason", self.call())
            self.assertEqual(self.saved(), player)

    def test_stale_location_and_replacement_are_not_new_payments(self):
        player = self.saved()
        player["adventureV1"]["progress"]["event"]["last"]["step"] = 2
        self.save(player)
        self.assertIn("errorReason", self.call())
        player["adventureV1"]["progress"]["event"]["last"]["step"] = 1
        self.save(player)
        self.assertTrue(self.call()["isSuccess"])
        player = self.saved()
        player["adventureV1"]["obstacles"][KEY]["eventId"] = "replacement"
        player["adventureV1"]["obstacles"][KEY]["status"] = "pending"
        self.save(player)
        self.assertIn("replacement unsupported", self.call()["errorReason"])
        self.assertEqual(self.saved(), player)

    def test_save_failure_and_revision_conflict_do_not_partial_commit(self):
        before = self.saved()
        for failure in (RuntimeError("storage failed"), StateConflictError("stale")):
            with patch.object(self.service, "save_state", side_effect=failure):
                status, body = self.registry.dispatch("quest/clearObstacle", dict(questType="event",
                    questId=23, chapterId=1, areaId=1), self.session)
            self.assertEqual(status, 200 if isinstance(failure, StateConflictError) else 500)
            self.assertEqual(self.saved(), before)
        self.assertTrue(self.call()["isSuccess"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 500)

    def test_original_section_boundaries_and_cost_inheritance(self):
        rows = self.catalog.load("quest_1_0000")
        for step in range(10):
            self.assertEqual(section_at(rows, 1, 1, step), (step + 1, 0))
            self.assertEqual(displayed_cost(rows, 1, 1, step + 1), 1)
        self.assertEqual(section_at(rows, 1, 1, 10), (10, 1))
        self.assertEqual(displayed_cost(rows, 1, 1, 10, correction=2), 3)
        with self.assertRaises(ValueError):
            section_at({}, 1, 1, 0)

    def test_preview_no_cost_is_unknown_not_free(self):
        self.assertEqual(displayed_cost({"1_1_1": {"cost": ""}}, 1, 1, 1), -1)
        self.assertEqual(displayed_cost({"1_1_1": {"cost": 0}}, 1, 1, 1), 0)

    def test_two_service_instances_use_storage_cas_not_shared_process_lock(self):
        first, first_registry = self.service, self.registry
        self.reload()
        second, second_registry = self.service, self.registry
        gate, lock = threading.Barrier(2), threading.Lock()
        loads = 0

        def load(pid):
            nonlocal loads
            with lock:
                result = self.states.load(pid)
                loads += 1
                wait = loads <= 2
            if wait:
                gate.wait(timeout=5)
            return result

        def save(player, pid):
            with lock:
                current = self.states.load(pid)
                if player.get("_revision", 0) != current.get("_revision", 0):
                    raise StateConflictError("stale isolated save")
                updated = copy.deepcopy(player)
                updated["_revision"] = current.get("_revision", 0) + 1
                self.states.save(updated, pid)

        for service in (first, second):
            service.load_state, service.save_state = load, save
        params = dict(questType="event", questId=23, chapterId=1, areaId=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reg.dispatch, "quest/clearObstacle", params, self.session)
                       for reg in (first_registry, second_registry)]
            results = [f.result() for f in futures]
        self.assertEqual(sum("errorReason" not in body for _, body in results), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 500)
        self.assertTrue(self.call()["isSuccess"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 500)


if __name__ == "__main__":
    unittest.main()
