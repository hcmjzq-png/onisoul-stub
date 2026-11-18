"""Original item delivery, stable lottery, modifiers and building evolution."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.production_inventory import ProductionInventory
from app.business.production_rewards import resolve_rewards, reward_weight
from app.business.production_modifiers import ProductionModifiers
from tests.test_fixed_resource_production import ResourceProductionCase, START, HARVEST
from tests.test_production_lifecycle import EXTRA as LIFECYCLE

FOLDER = Path(__file__).parent / "fixtures/production-completion"
EXTRA = json.loads((FOLDER / "tables.json").read_text("utf-8"))
CASES = json.loads((FOLDER / "source-proof.json").read_text("utf-8"))["cases"]
EVOLVE = "politic/building/conflateBuilding"
RESTAURANT = "building200_036_01_01_1_1"


class CompletionCase(ResourceProductionCase):
    def setUp(self):
        super().setUp()
        for group in (LIFECYCLE, EXTRA):
            for name, rows in group.items():
                self.tables[name] = {**self.tables.get(name, {}), **copy.deepcopy(rows)}

    def ready(self, bid, *, level=1):
        self.place(bid, level=level)
        if self.tables["building"][bid]["produceType"] == "auto":
            self.call("politic/map/getMapData")
        else:
            code = self.tables["building"][bid]["products"][0]
            self.assertTrue(self.call(START, buildingId=1, productId=code)["succeeded"])
        self.now = self.saved()["produce"]["1"]["dueTime"]

    def pair(self, *, grade=1, wildcard=False):
        bid = f"building200_036_{grade:02}_01_1_1"
        self.place(bid, level=grade * 10)
        player = self.saved()
        player["buildings"]["1"]["deployedMapKey"] = "none"
        player["buildings"]["2"] = {**player["buildings"]["1"], "instanceId": 2}
        if wildcard:
            player["buildings"]["2"].update(buildingTypeId=CASES["wildcard"], level=1)
        player["occupiedGrids"] = {}
        player["counters"].update(nextBuildingId=3, buildingCount=2)
        self.save(player)


class ProductionCompletionTest(CompletionCase):
    def test_original_consumable_tactic_and_cannon_delivery_use_real_inventory_keys(self):
        for label, table, kind in (("shrine", "item07", "items"), ("tactics", "item03", "tactics"),
                                    ("cannon", "item15", "items")):
            self.ready(CASES[label])
            result = self.call(HARVEST, buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            reward = result["producings"]["1"]["reward"]
            code = next(k for k in reward if k.startswith(table + "_"))
            key = EXTRA[table][code]["parameterId"] if kind == "tactics" else code
            value = self.saved()[kind][key]
            self.assertEqual(value["amount"] if kind == "tactics" else value, reward[code])
            if kind == "tactics":
                self.assertNotIn(code, self.saved()["items"])
                self.assertEqual(self.call("common/getTactics")[key]["amount"], reward[code])
            if label == "cannon":
                self.assertEqual(reward[code], 1)  # Ammo count, not the displayed damage value.

    def test_soul_delivery_is_visible_to_original_lottery_query(self):
        player = self.place(RESTAURANT)
        ProductionInventory(self.service).grant(player, {"item11_0001101": 3, "item11_0001501": 4, "item11_0001701": 5})
        self.save(player)
        self.assertEqual(player["souls"], {"purple": 3, "green": 4, "white": 5})
        result = self.call("politic/lottery/getSouls")
        self.assertEqual((result["purple"], result["green"], result["white"]), (3, 4, 5))

    def test_lottery_is_fixed_for_task_across_failure_restart_and_retries(self):
        self.ready(CASES["castle"])
        original = self.saved()
        engine = self.service.automatic_production
        record = original["buildings"]["1"]
        row = self.tables["building"][record["buildingTypeId"]]
        plan = original[engine.PLAN_KEY]["1"]
        expected = engine.reward_plan(record, row, original["produce"]["1"]["productId"], seed=plan["generation"])["reward"]
        player = copy.deepcopy(original)
        for item in self.tables["item03"].values():
            player.setdefault("tactics", {})[item["parameterId"]] = {"amount": 2147483647}
        self.save(player)
        self.fails(HARVEST, buildingIds=[1])
        self.save(original)
        self.mount()
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["producings"]["1"]["reward"], expected)
        self.fails(HARVEST, buildingIds=[1])

    def test_decreasing_weights_and_missing_nanban_row_have_explicit_compatible_rules(self):
        self.assertEqual(reward_weight(5, 1, 60, 44), 60)
        self.assertEqual(reward_weight(5, 50, 60, 44), 44)
        self.ready(CASES["missing_reward"])
        plan = self.saved()["fixedResourceProductionV1"]["1"]
        self.assertEqual(plan["rewardSourceId"], "reward01_02_00026_01")
        self.assertEqual(self.tables["product"][CASES["missing_reward"]]["rewardId"], "reward01_02_00027_01")
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_skill_position_learning_and_priority_follow_original_rows(self):
        self.ready(RESTAURANT)
        player = self.saved()
        player["characters"]["1"].update(grade=1, int=0, intAdd=0, skills={
            "0": {"id": "skill1_10041_01", "learning": 1, "level": 1},
            "1": {"id": "skill1_10042_01", "learning": 1, "level": 1}})
        player["decks"]["politic"] = {"0": {"ids": {"4": 1}, "equip": {}, "tactics": {}}}
        player["buildings"]["2"] = {**player["buildings"]["1"], "instanceId": 2,
            "buildingTypeId": "building200_051_01_01_1_1", "status": "none", "x": 11}
        self.save(player)
        active, _ = ProductionModifiers(self.service).skills(player)
        self.assertEqual([v["id"] for v in active], ["skill1_10042_01"])
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000101"], 152)
        player["characters"]["1"]["skills"]["1"]["learning"] = 2
        self.assertEqual([v["id"] for v in ProductionModifiers(self.service).skills(player)[0]], ["skill1_10041_01"])
        player["decks"]["politic"]["0"]["ids"] = {"0": 1}
        self.assertEqual(ProductionModifiers(self.service).skills(player)[0], [])

    def test_nonempty_owned_deck_is_allowed_and_intelligence_is_compatible_bonus(self):
        self.ready(RESTAURANT)
        player = self.saved()
        player["characters"]["1"].update(int=1000, intAdd=0, skills={})
        player["decks"]["politic"] = {"0": {"ids": {"0": 1}, "equip": {}, "tactics": {}}}
        self.save(player)
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000101"], 126)

    def test_skill_description_applies_resource_and_tactic_bonuses(self):
        code = "skill1_10042_01"
        self.tables["skill"][code]["desc"] = "fixture_mixed"
        self.tables["skillMessage.json"]["fixture_mixed"] = {
            "tw": "测试：「粮食」的生产量上升20%；兵法书追加生产3册的机率上升100%；"
                  "城以外的建筑物生产之兵法书追加生产2～4册"}
        self.ready(RESTAURANT)
        player = self.saved()
        player["characters"]["1"].update(grade=1, int=0, intAdd=0, skills={
            "0": {"id": code, "learning": 1, "level": 1}})
        player["decks"]["politic"] = {"0": {"ids": {"4": 1}, "equip": {}, "tactics": {}}}
        tactic = next(iter(EXTRA["item03"]))
        reward = {"item11_0000301": 100, tactic: 10}
        modifiers = ProductionModifiers(self.service)
        with patch("app.business.production_modifiers.random.Random") as rng:
            rng.return_value.random.return_value = 0
            rng.return_value.randint.return_value = 2
            output, _ = modifiers.plan(player, "1", reward, seed="skill-coverage")
        self.assertEqual(output, {"item11_0000301": 120, tactic: 15})
        del self.tables["skillMessage.json"]["fixture_mixed"]
        self.assertEqual(modifiers.plan(player, "1", reward, seed="skill-coverage")[0], reward)

    def test_castle_updates_only_connected_house_experience_in_same_commit(self):
        self.ready(CASES["castle"])
        player = self.saved()
        template = copy.deepcopy(player["buildings"]["1"])
        for key, x in (("2", 11), ("3", 25)):
            player["buildings"][key] = {**template, "instanceId": int(key), "buildingTypeId": CASES["house"],
                                        "x": x, "status": "none", "exp": 0}
        self.save(player)
        result = self.call(HARVEST, buildingIds=[1])
        self.assertTrue(result["succeeded"], result)
        collaborators = result["producings"]["1"]["collaborator"]
        self.assertEqual(set(collaborators), {"2"})
        self.assertEqual(self.saved()["buildings"]["2"]["exp"], collaborators["2"]["exp"])
        self.assertEqual(self.saved()["buildings"]["3"]["exp"], 0)

    def test_evolution_identical_and_wildcard_consumes_two_and_creates_next_original_grade(self):
        for wildcard in (False, True):
            self.pair(wildcard=wildcard)
            before = self.saved()
            result = self.call(EVOLVE, first="1", second="2")
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["buildingId"], 3)
            self.assertEqual(result["building"]["buildingTypeId"], "building200_036_02_01_1_1")
            self.assertEqual((result["building"]["level"], result["building"]["exp"], result["building"]["deployedMapKey"]), (1, 0, "none"))
            self.assertEqual(set(self.saved()["buildings"]), {"3"})
            self.assertEqual(self.saved()["resources"], before["resources"])
            self.assertEqual(self.saved()["actionPoints"], before["actionPoints"])
            self.fails(EVOLVE, first="1", second="2")

    def test_evolution_potion_fee_failure_and_state_conflict_are_atomic(self):
        self.pair(grade=3)
        self.fails(EVOLVE, first="1", second="2")
        player = self.saved()
        rule = EXTRA["building_evolutions"]["building200_036_03_01_1_1"]
        item = EXTRA["potion"][rule["fabrics"][0]]["itemID"]
        player["items"][item] = rule["amount"][0]
        self.save(player)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(EVOLVE, first="1", second="2")
        result = self.call(EVOLVE, first="1", second="2")
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(self.saved()["items"][item], 0)
        self.assertEqual(result["potions"][rule["fabrics"][0]]["amount"], 0)

    def test_evolution_rejects_nonmax_placed_same_instance_and_unowned_material(self):
        self.pair()
        self.fails(EVOLVE, first="1", second="1")
        self.fails(EVOLVE, first="1", second="999")
        baseline = self.saved()
        for field, value in (("level", 1), ("deployedMapKey", "map001"), ("status", "producing")):
            player = copy.deepcopy(baseline)
            player["buildings"]["1"][field] = value
            self.save(player)
            self.fails(EVOLVE, first="1", second="2")
