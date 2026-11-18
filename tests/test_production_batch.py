"""Original batch PP rules, combined balances, atomic saves and old ledgers."""
import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app import state
from app.business.production_batch import ProductionBatch
from tests.test_fixed_resource_production import ResourceProductionCase, TABLES, START, HARVEST

BULK = "politic/task/submitBulkProduceTasks"
RESTAURANT = "building200_036_01_01_1_1"
FURNITURE = "building200_037_01_01_1_1"
FORESTRY = "building200_039_01_01_1_1"
FIELD = "building200_041_01_01_1_1"
WOOD_RECIPE = "product060_012_01_01_1_1"
FIELD_RECIPE = "product060_023_01_01_1_1"


class ProductionBatchTest(ResourceProductionCase):
    def place_many(self, bids):
        self.place(bids[0])
        player = self.saved()
        template = copy.deepcopy(player["buildings"]["1"])
        player["buildings"] = {}
        player["occupiedGrids"] = {}
        for index, bid in enumerate(bids, 1):
            key, x = str(index), 5 + index * 5
            player["buildings"][key] = {**template, "instanceId": index,
                "buildingTypeId": bid, "x": x, "durability": TABLES["building"][bid]["durability"]}
            player["occupiedGrids"][f"{x},10"] = key
        player["counters"].update(nextBuildingId=len(bids) + 1, buildingCount=len(bids))
        self.save(player)
        return self.saved()

    def test_mixed_engines_start_and_harvest_charge_original_batch_points(self):
        bids = [RESTAURANT, FURNITURE, FORESTRY, FIELD]
        codes = [RESTAURANT, FURNITURE, WOOD_RECIPE, FIELD_RECIPE]
        player = self.place_many(bids)
        player["missions"].pop("5")
        self.save(player)
        accepted = self.call("politic/mission/changeState", missionIds=["po_mission_00005"], states=["accepted"])
        self.assertTrue(accepted["succeeded"], accepted)
        before = self.saved()
        result = self.call(BULK, buildingIds=[1, 2, 3, 4], productIds=codes)
        self.assertTrue(result["succeeded"], result)
        self.assertNotIn("errorReason", result)
        self.assertEqual(set(result["producings"]), {"1", "2", "3", "4"})
        active = self.saved()
        self.assertEqual(active["actionPoints"]["politicPoint"]["point"], 996)
        costs = {}
        for index, code in enumerate(codes, 1):
            product = TABLES["product"][code]
            task = result["producings"][str(index)]
            self.assertEqual(task["dueTime"] - task["createdTime"], product["dueInterval"])
            for kind, amount in zip(product["costTypes"], product["costAmounts"]):
                costs[kind] = costs.get(kind, 0) + amount
        for kind, amount in costs.items():
            self.assertEqual(before["resources"][kind]["amount"] - active["resources"][kind]["amount"], amount)
        self.fails(BULK, buildingIds=[1, 2, 3, 4], productIds=codes)
        self.fails(HARVEST, buildingIds=[1, 2, 3, 4])
        self.now += 900
        self.mount()
        self.assertEqual(set(self.call("politic/map/getMapData")["producings"]), {"1", "2", "3", "4"})
        result = self.call(HARVEST, buildingIds=[1, 2, 3, 4])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["completeCount"], 4)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 986)
        for key, code in zip(("1", "2", "3", "4"), codes):
            self.assertEqual(result["producings"][key]["building"]["exp"], TABLES["product"][code]["buildingExp"])
        after = self.saved()
        self.assertEqual(after["produce"], {})
        self.assertEqual(self.call(HARVEST, buildingIds=[1, 2, 3, 4])["producings"], {})
        self.assertEqual(self.saved(), after)

    def test_bulk_start_bad_last_entry_and_combined_costs_are_atomic(self):
        baseline = self.place_many([FURNITURE, FURNITURE])
        for ids, codes in (([1, 1], [FURNITURE, FURNITURE]), ([1, 999], [FURNITURE, FURNITURE]),
                           ([1, 2], [FURNITURE]), ([1, 2], [FURNITURE, WOOD_RECIPE]),
                           ([1, 2], [FURNITURE, {}]), ([], [])):
            self.fails(BULK, buildingIds=ids, productIds=codes)
        for field, amount in (("point", 1), ("wood", 150)):
            player = copy.deepcopy(baseline)
            if field == "point":
                player["actionPoints"]["politicPoint"]["point"] = amount
            else:
                player["resources"][field]["amount"] = amount
            self.save(player)
            self.fails(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE])

    def test_early_or_corrupt_last_task_keeps_all_rewards_and_points(self):
        self.place_many([FORESTRY, FURNITURE])
        self.assertTrue(self.call(BULK, buildingIds=[1, 2], productIds=[WOOD_RECIPE, FURNITURE])["succeeded"])
        self.now += 10
        self.fails(HARVEST, buildingIds=[1, 2])
        self.now += 890
        active = self.saved()
        for change in (lambda p: p["fixedResourceProductionV1"]["2"].update(generation=""),
                       lambda p: p["buildings"]["2"].update(deployedMapKey="none")):
            player = copy.deepcopy(active)
            change(player)
            self.save(player)
            self.fails(HARVEST, buildingIds=[1, 2])

    def test_batch_harvest_uses_ten_pp_and_checks_combined_capacity(self):
        self.place_many([FURNITURE, FURNITURE])
        self.assertTrue(self.call(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE])["succeeded"])
        self.now += 900
        active = self.saved()
        for change in (lambda p: p["actionPoints"]["politicPoint"].update(point=9),
                       lambda p: p["resources"]["gold"].update(amount=p["resources"]["gold"]["maxAmount"] - 200),
                       lambda p: p["entity"].update(exp=2147483647 - 15)):
            player = copy.deepcopy(active)
            change(player)
            self.save(player)
            self.fails(HARVEST, buildingIds=[1, 2])
        player = copy.deepcopy(active)
        player["actionPoints"]["politicPoint"]["point"] = 10
        self.save(player)
        result = self.call(HARVEST, buildingIds=[1, 2])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 0)

    def test_eleven_harvests_need_ten_points_not_one_per_building(self):
        self.place_many([FORESTRY] * 11)
        self.assertTrue(self.call(BULK, buildingIds=list(range(1, 12)), productIds=[WOOD_RECIPE] * 11)["succeeded"])
        self.now += 900
        player = self.saved()
        player["actionPoints"]["politicPoint"]["point"] = 10
        self.save(player)
        result = self.call(HARVEST, buildingIds=list(range(1, 12)))
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["completeCount"], 11)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 0)

    def test_concurrent_batch_requests_and_cas_conflicts_never_pay_twice(self):
        self.place_many([FURNITURE, FURNITURE])
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE]), range(8)))
        self.assertEqual(sum(result["succeeded"] for result in results), 1)
        self.now += 900
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(HARVEST, buildingIds=[1, 2])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call(HARVEST, buildingIds=[1, 2]), range(8)))
        self.assertEqual(sum(bool(result["producings"]) for result in results), 1)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 988)

    def test_mixed_construction_and_batch_harvest_commit_once(self):
        self.place_many([FURNITURE, FURNITURE, FURNITURE])
        self.assertTrue(self.call(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE])["succeeded"])
        player = self.saved()
        player["buildings"]["3"].update(status="building", remainedClickCount=0)
        self.save(player)
        self.fails(HARVEST, buildingIds=[3, 1, 2])
        self.now += 900
        result = self.call(HARVEST, buildingIds=[3, 1, 2])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["completeCount"], 3)
        self.assertEqual(set(result["buildings"]), {"1", "2", "3"})
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 988)

    def test_direct_batch_component_preserves_input_on_failure(self):
        player = self.place_many([FURNITURE, FURNITURE])
        before = copy.deepcopy(player)
        with self.assertRaises(ValueError):
            ProductionBatch(self.service).start(player, {"buildingIds": [1, 999], "productIds": [FURNITURE, FURNITURE]})
        self.assertEqual(player, before)
        self.assertTrue(self.call(BULK, buildingIds=[1, 2], productIds=[FURNITURE, FURNITURE])["succeeded"])
        self.now += 900
        player = self.saved()
        player["fixedResourceProductionV1"]["2"]["generation"] = ""
        before = copy.deepcopy(player)
        with self.assertRaises(ValueError):
            ProductionBatch(self.service).harvest(player, ["1", "2"])
        self.assertEqual(player, before)

    def test_partly_harvested_batch_requires_reload_without_repricing_or_paying(self):
        self.place_many([FORESTRY, FORESTRY])
        self.assertTrue(self.call(BULK, buildingIds=[1, 2], productIds=[WOOD_RECIPE, WOOD_RECIPE])["succeeded"])
        self.now += 900
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])
        self.fails(HARVEST, buildingIds=[1, 2])
        self.assertTrue(self.call(HARVEST, buildingIds=[2])["succeeded"])
