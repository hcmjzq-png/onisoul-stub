"""Task 5 lifecycle, rollback, restart and original incremental reward consumers."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.tutorial_production import TutorialFieldProduction
from app.tables import MissingTableError, TableCatalog, TableError
from tools.gameplay_smoke import MemorySessions, MemoryState

START = "politic/task/submitProduceTask"
HARVEST = "politic/task/completeTasks"
MISSION = "po_mission_00005"
SAMPLE = json.loads((Path(__file__).parent / "fixtures/tutorial-production.json").read_text("utf-8"))


class TutorialProductionTest(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).parent / "fixtures/gameplay/tables"
        self.catalog = TableCatalog(folder, folder / "table_list.tsv")
        original = self.catalog.load
        self.tables = copy.deepcopy(SAMPLE)
        def load(name):
            try:
                base = original(name)
            except TableError:
                if name not in self.tables:
                    raise
                base = {}
            return {**base, **self.tables.get(name, {})}
        self.catalog.load = load
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.now = 2000000000.75
        self.mount()
        self.session, _ = self.service._issue_login("tutorial-production-test")
        self.assertTrue(self.service.create_player({"username": "tutorial-production-test", "countryId": "country01",
                            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)["succeeded"])
        p = self.saved()
        # Explicit isolated prerequisite: task 1-4 completed, field constructed.
        p["missions"].update({str(i): "C" for i in range(1, 5)})
        p["missionProgress"] = {}
        p["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": TutorialFieldProduction.FIELD,
             "level": 1, "exp": 0, "status": "none", "durability": 10001,
             "deployedMapKey": "map001", "x": 4, "y": 4, "remainedClickCount": 0}}
        p["occupiedGrids"] = {"4,4": "1"}
        p["actionPoints"]["politicPoint"]["point"] = 25
        self.save(p)
        self.change("accepted")

    def mount(self):
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.service.tutorial_production.clock = lambda: self.now
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def change(self, status):
        return self.call("politic/mission/changeState", missionIds=[MISSION], states=[status])

    def start(self):
        return self.call(START, buildingId=1, productId=TutorialFieldProduction.PRODUCT)

    def fails(self, api, **params):
        before = self.saved()
        result = self.call(api, **params)
        self.assertFalse(result["succeeded"], result)
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)
        return result

    def test_start_timer_harvest_mission_reward_and_relogin(self):
        before = self.saved()
        self.assertFalse(self.change("finished")["succeeded"])
        started = self.start()
        self.assertTrue(started["succeeded"])
        self.assertNotIn("errorReason", started)
        self.assertEqual(started["dueTime"], 2000000010)
        self.assertEqual(started["producings"]["1"]["productId"], TutorialFieldProduction.PRODUCT)
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 24)
        self.now += 9
        self.fails(HARVEST, buildingIds=[1])
        self.now += 1
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"])
        self.assertNotIn("errorReason", result)
        entry = result["producings"]["1"]
        self.assertEqual(entry["reward"], {"item11_0000301": 13, "item11_0000501": 2})
        self.assertEqual(entry["building"]["exp"], 10)
        self.assertEqual(entry["collaborator"], {})
        self.assertIn("1", result["buildings"])
        self.assertEqual(result["autoProducings"], {})
        after = self.saved()
        self.assertEqual(after["produce"], {})
        self.assertEqual(after["resources"]["food"]["amount"], 13)
        self.assertEqual(after["entity"]["exp"], before["entity"]["exp"] + 2)
        self.assertEqual(after["actionPoints"]["politicPoint"]["point"], 23)
        self.assertNotIn("item11_0000301", after["items"])
        for state_name in ("finished", "closed"):
            self.assertTrue(self.change(state_name)["succeeded"])
        claimed = self.saved()
        self.assertEqual(claimed["resources"]["food"]["amount"], 313)
        self.assertEqual(claimed["entity"]["exp"], before["entity"]["exp"] + 52)
        self.assertEqual(self.change("closed")["reward"], {})
        self.assertEqual(self.saved()["resources"], claimed["resources"])
        self.mount()
        self.session, _ = self.service._issue_login("tutorial-production-test")
        self.assertEqual(self.call("politic/mission/getStatesFromAllMissions")["states"]["5"], "C")
        self.assertEqual(self.call("politic/map/getMapData")["producings"], {})
        self.assertEqual(self.saved()["resources"]["food"]["amount"], 313)

    def test_restart_before_and_after_due_does_not_grant_until_harvest(self):
        self.start()
        before = self.saved()
        self.mount()
        self.assertEqual(self.call("politic/map/getMapData")["tasks"]["producings"], before["produce"])
        self.now += 11
        self.mount()
        self.call("politic/map/getMapData")
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_concurrent_start_and_harvest_pay_each_saved_task_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.start(), range(16)))
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        self.now += 10
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(HARVEST, buildingIds=[1]), range(16)))
        self.assertEqual(sum(bool(r["producings"]) for r in results), 1)
        self.assertEqual(self.saved()["resources"]["food"]["amount"], 13)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 23)

    def test_insufficient_capacity_points_and_save_conflict_keep_task(self):
        self.start(); self.now += 10
        original = self.saved()
        for mutate in (lambda p: p["resources"]["food"].update(amount=100000),
                       lambda p: p["actionPoints"]["politicPoint"].update(point=0)):
            p = copy.deepcopy(original); mutate(p); self.save(p)
            self.fails(HARVEST, buildingIds=[1])
        self.save(original)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("injected")):
            self.fails(HARVEST, buildingIds=[1])
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_malformed_duplicate_unknown_and_mixed_batch_never_partly_complete(self):
        self.start()
        p = self.saved()
        p["buildings"]["2"] = {**p["buildings"]["1"], "instanceId": 2,
                               "status": "building", "remainedClickCount": 0, "x": 9}
        self.save(p)
        for ids in ([2, 1], [1, 1], [999], [True], []):
            self.fails(HARVEST, buildingIds=ids)
        self.now += 10
        result = self.call(HARVEST, buildingIds=[2, 1])
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["completeCount"], 2)
        self.assertEqual(self.saved()["buildings"]["2"]["status"], "none")

    def test_unsupported_recipe_road_modifiers_and_locked_mission_do_not_charge(self):
        self.fails(START, buildingId=1, productId="product060_001_01_01_1_1")
        original = self.saved()
        for mutate in (lambda p: p["missions"].update({"5": "O"}),
                       lambda p: p["decks"].update(politic={"0": {"ids": {"0": 1}}}),
                       lambda p: p["buildings"].update({"2": {**p["buildings"]["1"],
                           "buildingTypeId": "building200_051_01_01_1_1"}})):
            p = copy.deepcopy(original); mutate(p); self.save(p)
            self.fails(START, buildingId=1, productId=TutorialFieldProduction.PRODUCT)

    def test_missing_assets_bad_reference_and_corrupt_ledger_are_distinct(self):
        load = self.catalog.load
        with patch.object(self.catalog, "load", side_effect=lambda n: (_ for _ in ()).throw(MissingTableError(n)) if n == "reward01_politic" else load(n)):
            self.assertIn("stub has no assets", self.fails(START, buildingId=1, productId=TutorialFieldProduction.PRODUCT)["message"])
        p = self.saved(); p[TutorialFieldProduction.PLAN_KEY] = []; self.save(p)
        self.assertIn("no stub response", self.fails(START, buildingId=1, productId=TutorialFieldProduction.PRODUCT)["message"])


if __name__ == "__main__":
    unittest.main()
