"""Original opened -> finished branch, with server proofs and reward boundaries."""
import copy
import json
from pathlib import Path
import unittest

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, TableError
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FIXTURES / "mission-state-transitions.json").read_text("utf-8"))
CHANGE = "politic/mission/changeState"
REFINERY = "po_mission_00009"


class MissionStateTransitionsTest(unittest.TestCase):
    def setUp(self):
        folder = FIXTURES / "gameplay/tables"
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
        self.mount()
        self.session, _ = self.service._issue_login("mission-transitions-test")
        self.assertTrue(self.service.create_player({
            "username": "mission-transitions-test", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1",
        }, self.session)["succeeded"])

    def mount(self):
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, api, **params):
        status, result = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, result)
        return result

    def change(self, code, target):
        return self.call(CHANGE, missionIds=[code], states=[target])

    def prepare(self, code):
        # Isolated prerequisite snapshot, never a mutation of a running player.
        rows = self.service.missions.rows()
        player = self.saved()
        player.update(missions={"0": "C"}, missionProgress={}, missionChecks={},
                      missionRewards={}, buildings={}, occupiedGrids={})
        for prerequisite in rows[code].get("bootCheckData", []):
            player["missions"][str(rows[prerequisite]["index"])] = "C"
        self.save(player)
        self.assertTrue(self.change(code, "opened")["succeeded"])

    def fulfill(self, code, variant=0):
        row = self.service.missions.row(code)
        kind = row["conditionTypes1"][variant]
        target = row["conditionTargets1"][variant]
        amount = int(row["conditionArgs1"][variant])
        player = self.saved()
        if kind == "resourceCount":
            player["resources"][target]["amount"] = amount
        else:
            if kind == "categoryGradeCount":
                target = next(key for key, value in self.service._table("building").items()
                              if value.get("category") == target)
            for index in range(1, amount + 1):
                player["buildings"][str(index)] = {
                    "instanceId": index, "buildingTypeId": target, "status": "none",
                    "remainedClickCount": 0, "deployedMapKey": "map001",
                }
        self.save(player)

    def fails(self, code, target):
        before = self.saved()
        result = self.change(code, target)
        self.assertFalse(result["succeeded"], result)
        self.assertEqual(self.saved(), before)
        return result

    def test_precompleted_building_and_resource_missions_skip_acceptance(self):
        # Castle/category, three field types, food, roads, restaurant, forest,
        # and all three original refinery targets use the same phaseOpened.
        for number in (2, 4, 5, 6, 7, 8, 9):
            code = f"po_mission_{number:05d}"
            row = self.service.missions.row(code)
            for variant in range(len(row["conditionTargets1"])):
                with self.subTest(code=code, variant=variant):
                    self.prepare(code)
                    self.fulfill(code, variant)
                    result = self.change(code, "finished")
                    self.assertTrue(result["succeeded"], result)
                    self.assertNotIn("errorReason", result)
                    self.assertEqual(result["reward"], {})
                    self.assertEqual(self.saved()["missions"][str(number)], "F")

    def test_build_refinery_before_acceptance_reload_and_claim_once(self):
        self.prepare(REFINERY)
        player = self.saved()
        player["drafts"]["draft2000040"] = 1
        self.save(player)
        built = self.call("politic/task/submitBuildTask", draftId="draft2000040", originCoord=[14, 3])
        self.assertTrue(built["succeeded"], built)
        finished = self.call("politic/task/completeTasks", buildingIds=[built["buildingId"]])
        self.assertTrue(finished["succeeded"], finished)
        before = self.saved()
        self.mount()
        self.assertTrue(self.change(REFINERY, "finished")["succeeded"])
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.assertNotIn(REFINERY, self.saved()["missionRewards"])
        self.mount()
        progress = self.call("politic/mission/getMissionsInProgress")["missions"]
        self.assertEqual(progress[REFINERY]["state"], "finished")
        self.assertEqual(self.change(REFINERY, "finished")["reward"], {})
        claimed = self.change(REFINERY, "closed")
        self.assertTrue(claimed["succeeded"], claimed)
        self.assertEqual(claimed["reward"], {
            "item11_0000101": 2000.0, "item11_0000501": 50.0, "item11_0000401": 300.0,
        })
        after = self.saved()
        self.assertEqual(after["resources"]["gold"]["amount"], before["resources"]["gold"]["amount"] + 2000)
        self.assertEqual(after["resources"]["iron"]["amount"], before["resources"]["iron"]["amount"] + 300)
        self.mount()
        self.assertEqual(self.call("politic/mission/getStatesFromAllMissions")["states"]["9"], "C")
        self.assertEqual(self.change(REFINERY, "closed")["reward"], {})
        self.assertEqual(self.saved()["resources"], after["resources"])
        self.assertEqual(self.saved()["items"], after["items"])
        self.assertEqual(self.saved()["entity"]["exp"], after["entity"]["exp"])
        self.fails(REFINERY, "accepted")

    def test_skipping_acceptance_does_not_skip_conditions_or_prerequisites(self):
        self.prepare(REFINERY)
        self.fails(REFINERY, "finished")
        self.fulfill(REFINERY)
        self.fails(REFINERY, "closed")
        player = self.saved()
        player["missions"].pop("9")
        player["missionProgress"].pop(REFINERY)
        self.save(player)
        self.fails(REFINERY, "finished")
        self.assertTrue(self.change(REFINERY, "opened")["succeeded"])
        player = self.saved()
        player["missions"]["8"] = "A"
        self.save(player)
        self.fails(REFINERY, "finished")

    def test_self_acceptance_and_unknown_predicates_are_not_synthesized(self):
        self.prepare("po_mission_00001")
        self.fails("po_mission_00001", "finished")
        self.assertTrue(self.change("po_mission_00001", "accepted")["succeeded"])
        self.assertTrue(self.change("po_mission_00001", "finished")["succeeded"])
        self.prepare(REFINERY)
        self.tables["politicMission"][REFINERY]["conditionTypes1"] = ["unverified"] * 3
        result = self.fails(REFINERY, "finished")
        self.assertIn("unsupported", result["errorReason"])

    def test_mixed_completion_batch_is_atomic(self):
        self.prepare(REFINERY)
        self.fulfill(REFINERY)
        before = self.saved()
        result = self.call(CHANGE, missionIds=[REFINERY, "missing"], states=["finished", "accepted"])
        self.assertFalse(result["succeeded"])
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.change(REFINERY, "finished")["succeeded"])


if __name__ == "__main__":
    unittest.main()
