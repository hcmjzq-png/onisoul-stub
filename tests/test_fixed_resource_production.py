"""Original resource recipes: ownership, timers, balances and saved-task identity."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.fixed_resource_production import FixedResourceProduction, RESOURCE_ITEMS, PLAYER_EXP
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, TableError
from tools.gameplay_smoke import MemorySessions, MemoryState

FOLDER = Path(__file__).parent / "fixtures/fixed-resource-production"
TABLES = json.loads((FOLDER / "tables.json").read_text("utf-8"))
PROOF = json.loads((FOLDER / "source-proof.json").read_text("utf-8"))
START, HARVEST = "politic/task/submitProduceTask", "politic/task/completeTasks"


class ResourceProductionCase(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "fixtures/gameplay/tables"
        self.catalog = TableCatalog(root, root / "table_list.tsv")
        original = self.catalog.load
        self.tables = copy.deepcopy(TABLES)

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
        self.now = 2000000000.0
        self.mount()
        self.session, _ = self.service._issue_login("fixed-resource-isolated")
        self.assertTrue(self.service.create_player({"username": "fixed-resource-isolated", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)["succeeded"])
        self.baseline = self.saved()

    def mount(self):
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        for engine in (self.service.tutorial_production, self.service.restaurant_production,
                       self.service.fixed_production, self.service.automatic_production):
            engine.clock = lambda: self.now
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, api, **params):
        status, result = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, result)
        return result

    def place(self, bid, *, level=1, player_level=100):
        player = copy.deepcopy(self.baseline)
        row = self.tables["building"][bid]
        player["entity"]["level"] = player_level
        player["missions"].update({str(i): "C" for i in range(1, 6)})
        player["missionProgress"] = {}
        player["actionPoints"]["politicPoint"].update(point=1000, confirmTime=0.0)
        for box in player["resources"].values():
            # Isolated prerequisites: original level-100 caps are 10 million;
            # original high-grade base costs reach 3.3 million.
            box["amount"] = 5000000
        player["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": bid, "level": level,
            "exp": 0, "status": "none", "durability": row["durability"], "deployedMapKey": "map001",
            "x": 10, "y": 10, "remainedClickCount": 0}}
        player["occupiedGrids"] = {"10,10": "1"}
        player["produce"] = {}
        player["counters"].update(nextBuildingId=2, buildingCount=1)
        self.save(player)
        self.call("common/getPlayerParams")
        return self.saved()

    def fails(self, api, **params):
        before = self.saved()
        result = self.call(api, **params)
        self.assertFalse(result["succeeded"], result)
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)
        return result


class FixedResourceProductionTest(ResourceProductionCase):
    def test_catalogue_recipes_match_cost_timer_yield_and_availability(self):
        seen = set()
        withheld = 0
        for entry in PROOF["supported"]:
            bid = entry["building"]
            for code in entry["products"]:
                with self.subTest(building=bid, product=code):
                    before = self.place(bid)
                    product = TABLES["product"][code]
                    row = TABLES["building"][bid]
                    if row["name"] in ("田地", "植林地", "精炼炉") and product["dueInterval"] < 60:
                        self.assertNotIn(code, self.call("politic/building/getProductsByBuilding", buildingId=1)["products"])
                        self.fails(START, buildingId=1, productId=code)
                        withheld += 1
                        continue
                    result = self.call(START, buildingId=1, productId=code)
                    self.assertTrue(result["succeeded"], result)
                    self.assertNotIn("errorReason", result)
                    self.assertEqual(result["dueTime"] - result["createdTime"], product["dueInterval"])
                    active = self.saved()
                    step = TABLES["building_level"][row["levelUpTypeId"] + str(row["grade"] * 1000 + 1)]
                    self.assertEqual(step["costRatio"], 1)
                    for resource, amount in zip(product["costTypes"], product["costAmounts"]):
                        self.assertEqual(before["resources"][resource]["amount"] - active["resources"][resource]["amount"], amount)
                    self.fails(HARVEST, buildingIds=[1])
                    self.now += product["dueInterval"]
                    result = self.call(HARVEST, buildingIds=[1])
                    self.assertTrue(result["succeeded"], result)
                    original_reward = TABLES["reward01_politic"][product["rewardId"]]
                    expected = {}
                    # At level 1 the original interpolation equals the table minimum.
                    for i in range(1, 11):
                        if original_reward[f"ratio{i}min"] or original_reward[f"ratio{i}max"]:
                            item = original_reward[f"itemId{i}"]
                            expected[item] = expected.get(item, 0) + original_reward[f"count{i}min"]
                    self.assertEqual(result["producings"]["1"]["reward"], expected)
                    after = self.saved()
                    for item, resource in RESOURCE_ITEMS.items():
                        self.assertEqual(after["resources"][resource]["amount"] - active["resources"][resource]["amount"], expected.get(item, 0))
                    self.assertEqual(after["entity"]["exp"] - active["entity"]["exp"], expected.get(PLAYER_EXP, 0))
                    self.assertEqual(after["buildings"]["1"]["exp"], product["buildingExp"])
                    self.assertEqual(after["actionPoints"]["politicPoint"]["point"], before["actionPoints"]["politicPoint"]["point"] - 2)
                    self.assertEqual(self.call(HARVEST, buildingIds=[1])["producings"], {})
                    self.assertEqual(self.saved(), after)
                    seen.add(code)
        self.assertEqual(len(PROOF["supported"]), 50)
        self.assertEqual(withheld, 15)
        self.assertEqual(len(seen), 178)

    def test_higher_grade_uses_building_grade_even_when_recipe_has_lower_grade(self):
        bid = "building200_747_05_01_1_1"
        code = "product060_011_03_01_1_1"  # Original G5 building references a G3 recipe.
        self.place(bid, level=50)
        started = self.call(START, buildingId=1, productId=code)
        self.assertTrue(started["succeeded"], started)
        self.now += TABLES["product"][code]["dueInterval"]
        result = self.call(HARVEST, buildingIds=[1])
        reward = TABLES["reward01_politic"][TABLES["product"][code]["rewardId"]]
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["producings"]["1"]["reward"][reward["itemId1"]], reward["count1max"])

    def test_furniture_seven_harvests_upgrade_restart_and_next_level(self):
        bid = "building200_037_01_01_1_1"
        self.place(bid)
        for _ in range(7):
            self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
            self.now += 900
            self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])
        result = self.call("politic/building/levelUpBuilding", buildingId=1)
        self.assertTrue(result["succeeded"], result)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (2, 0))
        self.mount()
        self.assertEqual(self.call("politic/map/getMapData")["buildings"]["1"]["level"], 2)
        self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
        self.now += 900
        result = self.call(HARVEST, buildingIds=[1])
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000101"], 394)

    def test_start_and_due_time_survive_restart_and_do_not_pay_during_map_reads(self):
        bid = "building200_036_02_01_1_1"
        self.place(bid)
        started = self.call(START, buildingId=1, productId=bid)
        self.assertTrue(started["succeeded"], started)
        before = self.saved()
        self.mount()
        mapped = self.call("politic/map/getMapData")
        self.assertEqual(mapped["producings"]["1"]["dueTime"], started["dueTime"])
        self.now += 3600
        self.call("politic/map/getMapData")
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_concurrent_start_and_harvest_only_pay_each_task_once(self):
        bid = "building200_038_01_01_1_1"
        self.place(bid)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(START, buildingId=1, productId=bid), range(16)))
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        self.now += 900
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(HARVEST, buildingIds=[1]), range(16)))
        self.assertEqual(sum(bool(r["producings"]) for r in results), 1)

    def test_different_buildings_share_no_recipe_context_and_pay_once_each(self):
        wood, gold = "building200_039_01_01_1_1", "building200_037_01_01_1_1"
        self.place(wood)
        player = self.saved()
        player["buildings"]["2"] = {**player["buildings"]["1"], "instanceId": 2,
            "buildingTypeId": gold, "x": 20}
        player["occupiedGrids"]["20,10"] = "2"
        self.save(player)
        jobs = [(1, "product060_012_01_01_1_1"), (2, gold)] * 8
        with ThreadPoolExecutor(max_workers=8) as pool:
            starts = list(pool.map(lambda job: self.call(START, buildingId=job[0], productId=job[1]), jobs))
        self.assertEqual(sum(result["succeeded"] for result in starts), 2)
        self.now += 900
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda job: self.call(HARVEST, buildingIds=[job[0]]), jobs))
        rewards = {key: row["reward"] for result in results for key, row in result["producings"].items()}
        self.assertEqual(sum(bool(result["producings"]) for result in results), 2)
        self.assertEqual(rewards["1"]["item11_0000201"], 60)
        self.assertEqual(rewards["2"]["item11_0000101"], 125)

    def test_mixed_construction_and_generic_harvest_fail_or_commit_together(self):
        bid = "building200_037_01_01_1_1"
        self.place(bid)
        self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
        player = self.saved()
        player["buildings"]["2"] = {**player["buildings"]["1"], "instanceId": 2,
            "status": "building", "x": 20}
        self.save(player)
        self.fails(HARVEST, buildingIds=[2, 1])
        self.now += 900
        result = self.call(HARVEST, buildingIds=[2, 1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["completeCount"], 2)
        self.assertEqual(self.saved()["buildings"]["2"]["status"], "none")

    def test_unknown_selection_missing_row_and_manual_start_of_auto_do_not_charge(self):
        for name, entry in PROOF["excluded"].items():
            if name == "finite":
                continue  # Finite manual/single production is now supported.
            with self.subTest(reason=name):
                self.place(entry["building"])
                self.fails(START, buildingId=1, productId=entry["product"])

    def test_foreign_recipe_unowned_stored_and_locked_recipe_do_not_charge(self):
        bid = "building200_731_01_01_1_1"
        code = "product060_035_01_01_1_1"
        self.place(bid, player_level=1)
        self.fails(START, buildingId=1, productId=code)
        self.place(bid)
        self.fails(START, buildingId=999, productId=code)
        self.fails(START, buildingId=1, productId="building200_036_01_01_1_1")
        player = self.saved()
        player["buildings"]["1"]["deployedMapKey"] = "none"
        self.save(player)
        self.fails(START, buildingId=1, productId=code)

    def test_capacity_points_conflicts_and_corrupt_ledger_preserve_task(self):
        bid = "building200_038_01_01_1_1"
        self.place(bid)
        self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
        self.now += 900
        active = self.saved()
        for change in (lambda p: p["resources"]["gold"].update(amount=2147483647),
                       lambda p: p["actionPoints"]["politicPoint"].update(point=0),
                       lambda p: p[FixedResourceProduction.PLAN_KEY]["1"].update(buildingLevel=2),
                       lambda p: p["decks"].update(politic={"0": {"ids": {"0": 999999}}})):
            player = copy.deepcopy(active)
            change(player)
            self.save(player)
            self.fails(HARVEST, buildingIds=[1])
        self.save(active)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(HARVEST, buildingIds=[1])
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_unrelated_excess_resource_does_not_block_another_resource_harvest(self):
        bid, code = "building200_039_01_01_1_1", "product060_012_01_01_1_1"
        self.place(bid)
        self.assertTrue(self.call(START, buildingId=1, productId=code)["succeeded"])
        player = self.saved()
        player["resources"]["iron"]["amount"] = 2147483647
        self.save(player)
        self.now += 900
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])


if __name__ == "__main__":
    unittest.main()
