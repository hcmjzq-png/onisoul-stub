"""Restaurant lifecycle, seven harvests to upgrade, replay and failure atomicity.

Original table subset; resources/ownership and clock are isolated prerequisites.
No test changes a live player's state or the production duration.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.restaurant_production import RestaurantProduction
from app.tables import TableCatalog, TableError
from tools.gameplay_smoke import MemorySessions, MemoryState

SAMPLE = json.loads((Path(__file__).parent / "fixtures/restaurant-production.json").read_text(encoding="utf-8"))
FIELD = RestaurantProduction.FIELD
START = "politic/task/submitProduceTask"
HARVEST = "politic/task/completeTasks"
UPGRADE = "politic/building/levelUpBuilding"


class RestaurantProductionTest(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).parent / "fixtures/gameplay/tables"
        self.catalog = TableCatalog(root, root / "table_list.tsv")
        original = self.catalog.load
        self.tables = copy.deepcopy(SAMPLE)

        def load(name: str) -> dict:
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
        self.session, _ = self.service._issue_login("restaurant-isolated")
        self.assertTrue(self.service.create_player({"username": "restaurant-isolated", "countryId": "country01",
                         "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)["succeeded"])
        player = self.saved()
        player["resources"]["gold"]["amount"] = 5000
        player["resources"]["food"]["amount"] = 3000
        player["actionPoints"]["politicPoint"]["point"] = 100
        player["buildings"] = {"1": {"instanceId": 1, "buildingTypeId": FIELD, "level": 1,
            "exp": 0, "status": "none", "durability": 10001, "deployedMapKey": "map001",
            "x": 10, "y": 10, "remainedClickCount": 0}}
        player["occupiedGrids"] = {"10,10": "1"}
        player["counters"].update(nextBuildingId=2, buildingCount=1)
        self.save(player)
        self.call("common/getPlayerParams")

    def mount(self) -> None:
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.service.restaurant_production.clock = lambda: self.now
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def saved(self) -> dict:
        return self.states.load(self.session["playerId"])

    def save(self, player: dict) -> None:
        self.states.save(player, self.session["playerId"])

    def call(self, api: str, **params) -> dict:
        status, result = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, result)
        return result

    def start(self) -> dict:
        return self.call(START, buildingId=1, productId=FIELD)

    def fails(self, api: str, **params) -> dict:
        before = self.saved()
        result = self.call(api, **params)
        self.assertFalse(result["succeeded"], result)
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)
        return result

    def test_restart_seven_harvests_upgrade_and_level_two_costs(self) -> None:
        before = self.saved()
        self.fails(UPGRADE, buildingId=1)
        for cycle in range(7):
            result = self.start()
            self.assertTrue(result["succeeded"], result)
            self.assertNotIn("errorReason", result)
            self.assertEqual(result["dueTime"] - result["createdTime"], 900)
            self.assertEqual(result["producings"]["1"]["productId"], FIELD)
            self.fails(START, buildingId=1, productId=FIELD)
            self.fails(UPGRADE, buildingId=1)
            if cycle == 0:
                self.now += 899
                self.fails(HARVEST, buildingIds=[1])
                self.mount()
                mapped = self.call("politic/map/getMapData")["producings"]["1"]
                self.assertEqual(mapped["dueTime"], result["dueTime"])
                self.now += 1
            else:
                self.now += 900
            result = self.call(HARVEST, buildingIds=[1])
            self.assertTrue(result["succeeded"], result)
            self.assertEqual(result["producings"]["1"]["reward"], {"item11_0000101": 125, "item11_0000501": 12})
            self.assertEqual(result["buildings"]["1"]["exp"], (cycle + 1) * 40)
            self.assertEqual(result["autoProducings"], {})
            after = self.saved()
            self.assertEqual(self.call(HARVEST, buildingIds=[1])["producings"], {})
            self.assertEqual(self.saved(), after)
        after = self.saved()
        self.assertEqual(after["resources"]["food"]["amount"], 2300)
        self.assertEqual(after["resources"]["gold"]["amount"], 5875)
        self.assertEqual(after["entity"]["exp"] - before["entity"]["exp"], 84)
        self.assertEqual(after["actionPoints"]["politicPoint"]["point"], 86)
        upgraded = self.call(UPGRADE, buildingId=1)
        self.assertTrue(upgraded["succeeded"], upgraded)
        self.assertNotIn("errorReason", upgraded)
        self.assertEqual((upgraded["building"]["level"], upgraded["building"]["exp"]), (2, 0))
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 5475)
        self.assertEqual(self.saved()["resources"]["food"]["amount"], 2200)
        self.mount()
        self.session, _ = self.service._issue_login("restaurant-isolated")
        self.assertEqual(self.call("politic/map/getMapData")["buildings"]["1"]["level"], 2)
        before = self.saved()
        self.assertTrue(self.start()["succeeded"])
        self.assertEqual(before["resources"]["food"]["amount"] - self.saved()["resources"]["food"]["amount"], 221)
        self.now += 900
        result = self.call(HARVEST, buildingIds=[1])
        self.assertEqual(result["producings"]["1"]["reward"]["item11_0000101"], 394)
        self.assertEqual(result["buildings"]["1"]["exp"], 40)

    def test_road_bonus_preserves_layout_and_unowned_deck_members_are_rejected(self) -> None:
        player = self.saved()
        road = {**player["buildings"]["1"], "instanceId": 2, "x": 11,
                "buildingTypeId": "building200_051_01_01_1_1"}
        player["buildings"]["2"] = road
        self.save(player)
        self.assertTrue(self.start()["succeeded"])
        self.now += 900
        self.assertEqual(self.call(HARVEST, buildingIds=[1])["producings"]["1"]["reward"]["item11_0000101"], 150)
        self.assertEqual(self.saved()["buildings"]["2"], road)
        player = self.saved()
        player["decks"]["politic"] = {"0": {"ids": {"0": 999999}}}
        self.save(player)
        self.fails(START, buildingId=1, productId=FIELD)

    def test_authoritative_recovery_matches_clock_and_debit_keeps_cadence(self) -> None:
        player = self.saved()
        player["actionPoints"]["politicPoint"].update(point=20, confirmTime=1000.0)
        self.save(player)
        with patch("app.business.gameplay._now", return_value=1120.0):
            params = self.call("common/getPlayerParams")
            self.assertEqual(params["actionPoints"]["politicPoint"]["point"], 21)
            self.assertTrue(self.start()["succeeded"])
            self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 20)
            before = self.saved()
            self.call("common/getPlayerParams")
            self.assertEqual(self.saved(), before)
        with patch("app.business.gameplay._now", return_value=1240.0):
            params = self.call("common/getPlayerParams")
            self.assertEqual(params["actionPoints"]["politicPoint"]["point"], 21)

    def test_concurrent_start_and_harvest_only_debit_and_credit_once(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.start(), range(16)))
        self.assertEqual(sum(result["succeeded"] for result in results), 1)
        self.now += 900
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(HARVEST, buildingIds=[1]), range(16)))
        self.assertEqual(sum(bool(result["producings"]) for result in results), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 5125)
        self.assertEqual(self.saved()["resources"]["food"]["amount"], 2900)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 98)

    def test_insufficient_cost_capacity_points_and_conflict_preserve_state(self) -> None:
        before = self.saved()
        for field, value in (("food", 99), ("points", 0)):
            player = copy.deepcopy(before)
            (player["resources"]["food"] if field == "food" else player["actionPoints"]["politicPoint"])["amount" if field == "food" else "point"] = value
            self.save(player)
            self.fails(START, buildingId=1, productId=FIELD)
        self.save(before)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(START, buildingId=1, productId=FIELD)
        self.assertTrue(self.start()["succeeded"])
        self.now += 900
        active = self.saved()
        for mutate in (lambda p: p["resources"]["gold"].update(amount=100000),
                       lambda p: p["actionPoints"]["politicPoint"].update(point=0)):
            player = copy.deepcopy(active)
            mutate(player)
            self.save(player)
            self.fails(HARVEST, buildingIds=[1])
        self.save(active)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("isolated conflict")):
            self.fails(HARVEST, buildingIds=[1])
        self.assertTrue(self.call(HARVEST, buildingIds=[1])["succeeded"])

    def test_ownership_recipe_active_state_and_unsupported_mode_do_not_write(self) -> None:
        self.fails(START, buildingId=999, productId=FIELD)
        self.fails(START, buildingId=1, productId="product060_023_01_01_1_1")
        before = self.saved()
        for change in ({"deployedMapKey": "none"}, {"status": "building"}, {"durability": 5},
                       {"buildingTypeId": "building200_036_02_01_1_1"}):
            player = copy.deepcopy(before)
            player["buildings"]["1"].update(change)
            self.save(player)
            self.fails(START, buildingId=1, productId=FIELD)
        self.save(before)
        self.assertTrue(self.start()["succeeded"])
        self.now += 900
        active = self.saved()
        active[RestaurantProduction.PLAN_KEY]["1"]["buildingLevel"] = 2
        self.save(active)
        self.fails(HARVEST, buildingIds=[1])


if __name__ == "__main__":
    unittest.main()
