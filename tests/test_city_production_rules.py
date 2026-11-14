"""Known calculations only; no test asserts unproven final harvest amounts."""
import copy
import json
from pathlib import Path
import unittest

from app.business.city_production_rules import (
    durability_kind, harvest_display_point_cost, preview_amount,
    production_costs, reward_slot,
)


class ProductionRulesTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).parent / "fixtures/city_production/production-rules.json").read_text("utf-8"))
        self.reward = self.data["reward01_politic"]["reward01_01_00001_01"]

    def test_original_resource_and_player_exp_slots_are_separate(self):
        food, exp = [reward_slot(self.reward, i) for i in (1, 2)]
        self.assertEqual((food.group, food.item_id, food.count_min, food.count_max), ("A", "item11_0000301", 13, 17))
        self.assertEqual((exp.group, exp.item_id, exp.count_min, exp.count_max), ("B", "item11_0000501", 2, 2))
        self.assertTrue(all(reward_slot(self.reward, i) is None for i in range(3, 11)))
        self.assertEqual(self.data["product"]["product060_023_01_01_1_1"]["buildingExp"], 10)

    def test_reward_groups_and_ranges_are_preserved_not_rolled(self):
        row = self.data["reward01_politic"]["reward01_01_00013_01"]
        first, second = reward_slot(row, 1), reward_slot(row, 2)
        self.assertEqual(first.group, second.group)
        self.assertEqual((first.ratio_min, first.ratio_max, first.count_min, first.count_max), (10, 20, 3, 5))
        self.assertEqual((second.count_min, second.count_max), (5, 10))

    def test_ratio_gate_matches_client_and_does_not_coerce_strings(self):
        # Controlled mutations: original parser treats nonnumeric ratios as 0.
        for value in (0, "1", True, None):
            row = dict(self.reward, ratio1min=value, ratio1max=value)
            self.assertIsNone(reward_slot(row, 1))
        row = dict(self.reward, ratio1min="1", ratio1max=2)
        self.assertEqual((reward_slot(row, 1).ratio_min, reward_slot(row, 1).ratio_max), (0, 2))
        with self.assertRaises(ValueError):
            reward_slot({}, 1)
        with self.assertRaises(ValueError):
            reward_slot(dict(self.reward, ratio1min=float("nan")), 1)

    def test_preview_uses_building_level_and_is_not_final_reward(self):
        self.assertEqual([preview_amount(1, lv, 13, 17) for lv in range(1, 11)], [13, 13, 13, 14, 14, 15, 15, 16, 16, 17])
        for args in ((0, 1, 13, 17), (1, 11, 13, 17), (1, 1, 17, 13), (True, 1, 13, 17)):
            with self.assertRaises(ValueError):
                preview_amount(*args)

    def test_original_cost_requires_float32_not_python_float64(self):
        product = self.data["product"]["building200_036_02_01_1_1"]
        level = self.data["building_level"]["product_store2003"]
        self.assertEqual(product["costAmounts"], [3800])
        self.assertEqual(level["costRatio"], 1.015)
        self.assertEqual(int(3800 * 1.015), 3856)  # float64 is one too small here
        self.assertEqual(list(production_costs(product, level).values()), [3857])
        field = self.data["product"]["product060_023_01_01_1_1"]
        self.assertEqual(production_costs(field, self.data["building_level"]["product_early1001"]), {"gold": 0})

    def test_bad_costs_cannot_become_free_production(self):
        for row in ({}, {"costTypes": ["gold"], "costAmounts": []},
                    {"costTypes": ["gold", "gold"], "costAmounts": [1, 2]},
                    {"costTypes": ["gold"], "costAmounts": [True]},
                    {"costTypes": ["gold"], "costAmounts": [-1]}):
            with self.assertRaises(ValueError):
                production_costs(row, {"costRatio": 1})
        for ratio in (None, True, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                production_costs({"costTypes": [], "costAmounts": []}, {"costRatio": ratio})

    def test_infinite_durability_is_exact_sentinel_not_a_decrement(self):
        defines = self.data["defines"]
        field = self.data["building"]["building200_041_01_01_1_1"]
        mine = self.data["building"]["building200_031_01_01_1_1"]
        self.assertEqual(durability_kind(field["durability"], defines), "infinite")
        self.assertEqual(durability_kind(mine["durability"], defines), "finite")
        self.assertEqual([durability_kind(v, defines) for v in (-1, 0, 1, 10000, 10001, 10002)],
                         ["dead", "dead", "finite", "finite", "infinite", "finite"])
        for value in (None, True, 1.5):
            with self.assertRaises(ValueError):
                durability_kind(value, defines)
        with self.assertRaises(ValueError):
            durability_kind(10001, {})

    def test_successful_harvest_display_debit_is_batch_not_per_building(self):
        self.assertEqual([harvest_display_point_cost(n, self.data["defines"]) for n in (1, 2, 10, 20)], [1, 10, 10, 10])
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                harvest_display_point_cost(count, self.data["defines"])
        with self.assertRaises(ValueError):
            harvest_display_point_cost(2, {})

    def test_all_helpers_leave_source_state_unchanged(self):
        before = copy.deepcopy(self.data)
        reward_slot(self.reward, 1)
        preview_amount(1, 3, 13, 17)
        production_costs(self.data["product"]["building200_036_02_01_1_1"], self.data["building_level"]["product_store2003"])
        durability_kind(10001, self.data["defines"])
        harvest_display_point_cost(2, self.data["defines"])
        self.assertEqual(self.data, before)


if __name__ == "__main__":
    unittest.main()
