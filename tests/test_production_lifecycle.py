"""Automatic renewal, finite exhaustion, cancellation and credit acceleration."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.automatic_production import AutomaticProduction
from app.business.city_production_rules import preview_amount
from tests.test_fixed_resource_production import ResourceProductionCase, START, HARVEST

FOLDER = Path(__file__).parent / "fixtures/production-lifecycle"
EXTRA = json.loads((FOLDER / "tables.json").read_text("utf-8"))
CASES = json.loads((FOLDER / "source-proof.json").read_text("utf-8"))["cases"]
CANCEL, ACCEL = "politic/task/cancelTasks", "politic/task/accelerateProduceTask"


class ProductionLifecycleTest(ResourceProductionCase):
    def setUp(self):
        super().setUp()
        for name, rows in EXTRA.items():
            self.tables[name] = {**self.tables.get(name, {}), **copy.deepcopy(rows)}

    def auto(self, label="infinite_auto"):
        bid = CASES[label]
        self.place(bid)
        before = self.saved()
        mapped = self.call("politic/map/getMapData")
        self.assertTrue(mapped["succeeded"], mapped)
        task = mapped["producings"]["1"]
        product = self.tables["product"][task["productId"]]
        self.assertEqual(task["dueTime"] - task["createdTime"], product["dueInterval"])
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.assertEqual(self.saved()["actionPoints"], before["actionPoints"])
        return task

    def test_auto_restores_once_waits_for_harvest_and_renews_from_collection_time(self):
        task = self.auto()
        active = self.saved()
        self.mount()
        self.now += 3 * 7200
        self.call("politic/map/getMapData")
        self.assertEqual(self.saved()["produce"]["1"], task)
        self.assertEqual(self.saved()["resources"], active["resources"])
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000301"], 1000)
        self.assertEqual(result["autoProducings"]["1"]["createdTime"], self.now)
        self.assertEqual(result["autoProducings"]["1"]["dueTime"], self.now + 7200)
        self.assertEqual(self.saved()["buildings"]["1"]["durability"], 10001)
        self.assertEqual(self.saved()["buildings"]["1"]["exp"], 100)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 999)
        self.fails(HARVEST, buildingIds=[1])

    def test_ten_original_goldmine_harvests_exhaust_and_remove_only_its_state(self):
        self.auto("finite_auto")
        for index in range(10):
            self.now = self.saved()["produce"]["1"]["dueTime"]
            result = self.call(HARVEST, buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["buildings"]["1"]["durability"], 9 - index)
            if index < 9:
                self.assertIn("1", result["autoProducings"])
            else:
                self.assertEqual(result["autoProducings"], {})
                self.assertEqual(result["buildings"]["1"]["status"], "dead")
        final = self.saved()
        self.assertEqual(final["buildings"], {})
        self.assertEqual(final["produce"], {})
        self.assertEqual(final[AutomaticProduction.PLAN_KEY], {})
        self.assertEqual(final["occupiedGrids"], {})
        self.assertEqual(final["counters"]["buildingCount"], 0)
        self.assertEqual(final["actionPoints"]["politicPoint"]["point"], 990)
        self.fails(HARVEST, buildingIds=[1])

    def test_finite_single_and_one_use_manual_consume_only_on_success(self):
        for label in ("finite_single", "one_use_manual"):
            bid = CASES[label]
            self.place(bid)
            code = self.tables["building"][bid]["products"][0]
            durability = self.saved()["buildings"]["1"]["durability"]
            self.assertTrue(self.call(START, buildingId=1, productId=code)["succeeded"])
            self.assertEqual(self.saved()["buildings"]["1"]["durability"], durability)
            self.fails(HARVEST, buildingIds=[1])
            self.now = self.saved()["produce"]["1"]["dueTime"]
            result = self.call(HARVEST, buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["buildings"]["1"]["durability"], durability - 1)
            self.assertEqual(result["autoProducings"], {})
            self.assertEqual("1" in self.saved()["buildings"], durability > 1)

    def test_mixed_auto_manual_and_last_harvest_charge_batch_pp_once(self):
        self.place(CASES["finite_auto"])
        player = self.saved()
        player["buildings"]["1"]["durability"] = 1  # Legitimate final-use state in an isolated account.
        template = copy.deepcopy(player["buildings"]["1"])
        for key, bid, x in (("2", CASES["infinite_auto"], 20), ("3", "building200_037_01_01_1_1", 30)):
            player["buildings"][key] = {**template, "instanceId": int(key), "buildingTypeId": bid,
                                        "durability": self.tables["building"][bid]["durability"], "x": x}
            player["occupiedGrids"][f"{x},10"] = key
        self.save(player)
        self.call("politic/map/getMapData")
        self.assertTrue(self.call(START, buildingId=3, productId="building200_037_01_01_1_1")["succeeded"])
        self.now += 7200
        result = self.call(HARVEST, buildingIds=[1, 2, 3])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["completeCount"], 3)
        self.assertEqual(set(result["autoProducings"]), {"2"})
        self.assertEqual(set(self.saved()["buildings"]), {"2", "3"})
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 989)

    def test_auto_storage_redeployment_and_relocation_keep_balances_and_identity(self):
        self.auto()
        active = self.saved()
        self.now += 100
        self.assertTrue(self.call("politic/building/putInBuildings", buildingIds=[1])["succeeded"])
        stored = self.saved()
        self.assertEqual(stored["produce"], {})
        self.assertEqual(stored["resources"], active["resources"])
        self.assertEqual(stored["actionPoints"], active["actionPoints"])
        self.now += 300
        self.call("politic/map/getMapData")
        self.assertEqual(self.saved()["produce"], {})
        deployed = self.call("politic/building/deployBuilding", buildingId=1, originCoord=[20, 20])
        self.assertTrue(deployed["succeeded"], deployed)
        task = deployed["autoProducings"]["1"]
        self.assertEqual(task["dueTime"], self.now + 7200)
        after = self.saved()
        self.call("politic/building/deployBuilding", buildingId=1, originCoord=[20, 20])
        self.assertEqual(self.saved(), after)
        moved = self.call("politic/map/relocateEnded", relocatedGrids={"x25y25": "1"})
        self.assertTrue(moved["succeeded"], moved)
        self.assertEqual(self.saved()["produce"]["1"], task)

    def test_auto_upgrade_uses_natural_experience_and_preserves_current_timer(self):
        self.auto()
        self.now += 7200
        first = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(first["succeeded"], first)
        timer = self.saved()["produce"]["1"]
        upgraded = self.call("politic/building/levelUpBuilding", buildingId=1)
        self.assertTrue(upgraded["succeeded"], upgraded)
        self.assertEqual((upgraded["building"]["level"], upgraded["building"]["exp"]), (2, 80))
        self.assertEqual(self.saved()["produce"]["1"], timer)
        self.now = timer["dueTime"]
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        reward = self.tables["reward01_politic"][self.tables["product"][timer["productId"]]["rewardId"]]
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000301"],
                         preview_amount(1, 2, reward["count1min"], reward["count1max"]))

    def test_unknown_auto_rewards_keep_timer_and_never_grant_or_consume_durability(self):
        for label in ("unsupported_selection_auto", "special_reward_auto"):
            task = self.auto(label)
            self.now = task["dueTime"]
            self.fails(HARVEST, buildingIds=[1])

    def test_auto_bad_ledger_capacity_and_save_conflicts_preserve_the_whole_cycle(self):
        task = self.auto()
        self.now = task["dueTime"]
        active = self.saved()
        for change in (lambda p: p["resources"]["food"].update(amount=p["resources"]["food"]["maxAmount"]),
                       lambda p: p[AutomaticProduction.PLAN_KEY]["1"].update(generation=""),
                       lambda p: p["buildings"]["1"].update(durability=1)):
            player = copy.deepcopy(active)
            change(player)
            self.save(player)
            self.fails(HARVEST, buildingIds=[1])
        self.save(active)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(HARVEST, buildingIds=[1])

    def test_cancel_manual_and_legacy_tasks_has_no_refund_reward_or_durability_debit(self):
        for bid in ("building200_036_01_01_1_1", "building200_041_01_01_1_1", CASES["finite_single"]):
            self.place(bid)
            code = self.tables["building"][bid]["products"][0]
            if bid == "building200_041_01_01_1_1":
                player = self.saved()
                player["missions"].pop("5")
                self.save(player)
                accepted = self.call("politic/mission/changeState", missionIds=["po_mission_00005"], states=["accepted"])
                self.assertTrue(accepted["succeeded"], accepted)
            self.assertTrue(self.call(START, buildingId=1, productId=code)["succeeded"])
            active = self.saved()
            result = self.call(CANCEL, buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            after = self.saved()
            self.assertEqual(after["produce"], {})
            self.assertEqual(after["resources"], active["resources"])
            self.assertEqual(after["actionPoints"], active["actionPoints"])
            self.assertEqual(after["buildings"]["1"]["durability"], active["buildings"]["1"]["durability"])
            self.fails(CANCEL, buildingIds=[1])

    def test_accelerate_legacy_generic_and_auto_updates_task_and_ledger_until_ready(self):
        for bid in ("building200_036_01_01_1_1", "building200_037_01_01_1_1", CASES["infinite_auto"]):
            self.place(bid)
            player = self.saved()
            player["resources"]["credit"]["amount"] = 100  # Isolated paid-currency prerequisite.
            self.save(player)
            if bid == CASES["infinite_auto"]:
                self.call("politic/map/getMapData")
            else:
                self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
            before = self.saved()
            result = self.call(ACCEL, buildingId=1, id="produce_accel_0001", count=1)
            self.assertTrue(result["succeeded"], result)
            task = result["producings"]["1"]
            self.assertEqual(task["dueTime"], before["produce"]["1"]["dueTime"] - 600)
            self.assertEqual(task["createdTime"], before["produce"]["1"]["createdTime"])
            self.assertEqual(self.saved()["resources"]["credit"]["amount"], 99)
            self.assertTrue(self.call(ACCEL, buildingId=1, id="produce_accel_0004", count=1)["succeeded"])
            self.assertEqual(self.saved()["produce"]["1"]["dueTime"], self.now)
            self.fails(ACCEL, buildingId=1, id="produce_accel_0001", count=1)
            self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_invalid_acceleration_and_cancel_batch_do_not_partially_write(self):
        self.auto()
        player = self.saved()
        player["resources"]["credit"]["amount"] = 0
        self.save(player)
        for params in ({"id": "none", "count": 1}, {"id": "produce_accel_0001", "count": 0},
                       {"id": "produce_accel_0001", "count": True}, {"id": "produce_accel_0001", "count": 1}):
            self.fails(ACCEL, buildingId=1, **params)
        self.fails(CANCEL, buildingIds=[1])
        self.fails(ACCEL, buildingId=999, id="produce_accel_0001", count=1)
        bid = "building200_037_01_01_1_1"
        self.place(bid)
        self.assertTrue(self.call(START, buildingId=1, productId=bid)["succeeded"])
        self.fails(CANCEL, buildingIds=[1, 999])
        self.assertEqual(self.saved()["produce"]["1"]["dueTime"] - self.now, 900)

    def test_normal_construction_starts_auto_but_manual_cannot_charge_an_auto_start(self):
        bid = CASES["finite_auto"]
        self.place(bid)
        player = self.saved()
        player["buildings"]["1"].update(status="building", remainedClickCount=0)
        self.save(player)
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["autoProducings"]["1"]["dueTime"], self.now + 3600)
        self.fails(START, buildingId=1, productId=bid)
