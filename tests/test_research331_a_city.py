"""Isolated component tests. Facts/maps below are test scenarios, not player data."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.city_background_services import CityBackgroundServices, SubcityFacts, SubcityRule
from app.business.city_production_services import ManualProductionServices
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import MissingTableError, TableCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState

SAMPLE = json.loads((Path(__file__).parent / "fixtures/research331/a-city/original-tables.json").read_text("utf8"))
START = "politic/task/submitProduceTask"
BULK = "politic/task/submitBulkProduceTasks"
BG_APIS = frozenset({"politic/map/getBackgrounds", "politic/map/setBackground",
                     "politic/shop/getBackgroundItems", "politic/shop/buyBackgroundItem"})
FREE = "product060_023_01_01_1_1"
PAID = "product060_001_01_01_1_1"


class Harness(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "fixtures/gameplay/tables"
        self.catalog = TableCatalog(root, root / "table_list.tsv")
        original_load = self.catalog.load
        self.tables = copy.deepcopy(SAMPLE)
        self.catalog.load = lambda name: self.tables[name] if name in self.tables else original_load(name)
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.session, _ = self.service._issue_login("research331-a")
        self.service.create_player({"username": "research331-a", "countryId": "country01",
                                    "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        p = self.saved()
        p["entity"]["level"] = 15  # isolated test premise, never live mutation
        p["buildings"] = {str(i): {"instanceId": i, "buildingTypeId": ManualProductionServices.FIELD,
                                   "level": 1, "exp": 0, "status": "waiting", "durability": 10001,
                                   "deployedMapKey": "map001", "x": i * 4, "y": 4} for i in (1, 2)}
        p["occupiedGrids"] = {"4,4": "1", "8,4": "2"}
        p["resources"]["gold"]["amount"] = 500
        p["resources"]["credit"]["amount"] = 1000
        p["actionPoints"]["politicPoint"]["point"] = 25
        p["missions"]["306"] = "C"
        self.save(p)
        self.call("common/getPlayerParams")

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, p):
        self.states.save(p, self.session["playerId"])

    def call(self, api, **params):
        code, result = self.registry.dispatch(api, params, self.session)
        self.assertEqual(code, 200)
        return result

    def fails(self, api, **params):
        before = self.saved()
        result = self.call(api, **params)
        self.assertIn("errorReason", result)
        self.assertEqual(before, self.saved())
        return result


class ProductionStartTest(Harness):
    def setUp(self):
        super().setUp()
        self.now = 2000000000.9
        self.group = ManualProductionServices(self.service, clock=lambda: self.now)
        self.group.register(self.registry, apis=frozenset({START, BULK}))

    def test_real_free_recipe_due_relogin_no_payout_or_durability_loss(self):
        before = self.saved()
        result = self.call(START, buildingId=1, productId=FREE)
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["dueTime"], 2000000010)
        self.assertEqual(result["now"], 2000000000)
        self.now += 11
        self.session, _ = self.service._issue_login("research331-a")
        body = self.call("politic/map/getMapData")
        self.assertEqual(body["tasks"]["producings"]["1"],
                         {"productId": FREE, "createdTime": 2000000000, "dueTime": 2000000010})
        after = self.saved()
        self.assertEqual(after["resources"], before["resources"])
        self.assertEqual(after["entity"]["exp"], before["entity"]["exp"])
        self.assertEqual(after["buildings"]["1"]["exp"], 0)
        self.assertEqual(after["buildings"]["1"]["durability"], 10001)
        self.assertEqual(after["actionPoints"]["politicPoint"]["point"], 24)
        for _ in range(2):
            self.fails("politic/task/completeTasks", buildingIds=[1])

    def test_paid_batch_original_cost_time_and_client_increment_replay(self):
        result = self.call(BULK, buildingIds=[1, 2], productIds=[FREE, PAID])
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["producings"]["2"]["dueTime"], 2000000900)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 490)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 23)
        replay = self.fails(BULK, buildingIds=[1, 2], productIds=[FREE, PAID])
        self.assertEqual(replay["producings"], {})
        # GameRestarter.isError (70-90), installed at Start:64, stops the
        # responder on errorReason. succeeded alone would NOT prove this.
        client_gold = 500
        for body in (result, replay):
            if "errorReason" not in body:
                client_gold -= 10
        self.assertEqual(client_gold, 490)

    def test_all_validation_before_any_charge_including_direct_component(self):
        for params in ({"buildingIds": [1, 2], "productIds": [FREE, "missing"]},
                       {"buildingIds": [1, 1], "productIds": [FREE, FREE]},
                       {"buildingIds": [1, 2], "productIds": [FREE]},
                       {"buildingIds": [1, 999], "productIds": [FREE, FREE]},
                       {"buildingIds": [True], "productIds": [FREE]}):
            self.fails(BULK, **params)
            direct = self.saved(); before = copy.deepcopy(direct)
            with self.assertRaises(ValueError):
                self.group.submit(direct, params, bulk=True)
            self.assertEqual(before, direct)

    def test_cost_points_level_modifiers_finite_storage_and_event_gates(self):
        original = self.saved()
        mutations = [lambda p: p["resources"]["gold"].update(amount=9),
                     lambda p: p["actionPoints"]["politicPoint"].update(point=0),
                     lambda p: p["entity"].update(level=4),
                     lambda p: p["buildings"]["1"].update(durability=10),
                     lambda p: p["buildings"]["1"].update(deployedMapKey="none"),
                     lambda p: p["buildings"]["1"].update(status="event"),
                     lambda p: p["decks"].update(politic={"0": {"ids": {"0": 1}}})]
        for mutate in mutations:
            p = copy.deepcopy(original); mutate(p); self.save(p)
            self.fails(START, buildingId=1, productId=PAID)

    def test_concurrent_submissions_charge_once_and_conflict_saves_nothing(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: self.call(START, buildingId=1, productId=PAID), range(16)))
        self.assertEqual(sum(r["succeeded"] is True for r in replies), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 490)
        before = self.saved()
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("injected")):
            self.fails(START, buildingId=2, productId=PAID)
        self.assertEqual(before, self.saved())

    def test_missing_asset_vs_bad_reference_and_invalid_clock(self):
        load = self.catalog.load
        with patch.object(self.catalog, "load", side_effect=lambda n: (_ for _ in ()).throw(MissingTableError(n)) if n == "product" else load(n)):
            self.assertIn("stub has no assets", self.fails(START, buildingId=1, productId=FREE)["errorReason"])
        self.tables["product"].pop(FREE)
        self.assertIn("no stub response", self.fails(START, buildingId=1, productId=FREE)["errorReason"])
        field = self.tables["building"].pop(ManualProductionServices.FIELD)
        self.assertIn("no stub response", self.fails(START, buildingId=1, productId=PAID)["errorReason"])
        self.tables["building"][ManualProductionServices.FIELD] = field
        for value in (float("nan"), float("inf"), -1, True):
            self.now = value
            self.fails(START, buildingId=1, productId=PAID)

    def test_authentication_and_default_registry_remain_closed(self):
        code, body = self.registry.dispatch(START, {"buildingId": 1, "productId": FREE}, None)
        self.assertIn("errorReason", body)
        normal = self.service.register(Registry()).register_contract_defaults()
        before = self.saved()
        _, body = normal.dispatch(START, {"buildingId": 1, "productId": FREE}, self.session)
        self.assertIn("errorReason", body)
        self.assertEqual(before, self.saved())

    def test_road_is_preserved_and_mixed_construction_harvest_is_not_partially_saved(self):
        p = self.saved()
        p["buildings"]["3"] = {"instanceId": 3, "buildingTypeId": "building200_051_01_01_1_1",
                               "level": 1, "exp": 0, "status": "waiting", "durability": 10001,
                               "deployedMapKey": "map001", "x": 5, "y": 4}
        p["occupiedGrids"]["5,4"] = "3"
        p["buildings"]["2"].update(status="building", remainedClickCount=0)
        self.save(p)
        self.assertTrue(self.call(START, buildingId=1, productId=FREE)["succeeded"])
        self.assertEqual(self.saved()["buildings"]["3"], p["buildings"]["3"])
        self.assertEqual(self.saved()["occupiedGrids"], p["occupiedGrids"])
        self.fails("politic/task/completeTasks", buildingIds=[2, 1])
        self.assertEqual(self.saved()["buildings"]["2"]["status"], "building")


class SubcityBackgroundTest(Harness):
    def setUp(self):
        super().setUp()
        # Explicit artificial prerequisite scenario, no lambda True opener.
        self.facts = SubcityFacts(self.session["playerId"], 2, 5, 1, 7500, "map1",
                                 {"name": "隔离测试支城", "size": {"width": 40, "height": 40},
                                  "occupiedGrids": {}})
        self.group = CityBackgroundServices(self.service, acquire_facts=lambda p: self.facts,
                                            static_background_sales=True)
        self.group.register(self.registry, apis=BG_APIS)

    def test_original_rule_is_level15_chapter_completion_and_7500(self):
        rule = SubcityRule.from_table(self.tables["politicMission"])
        self.assertEqual((rule.index, rule.minimum_level, rule.quest, rule.chapter, rule.minimum_kokudaka),
                         ("306", 15, 2, 5, 7500))
        self.assertTrue(rule.qualifies(15, self.facts))
        self.assertFalse(rule.qualifies(14, self.facts))
        self.assertFalse(rule.qualifies(15, replace(self.facts, kokudaka=7499)))
        self.assertFalse(rule.qualifies(15, replace(self.facts, story_complete=0)))
        for facts in (True, replace(self.facts, story_complete=True), replace(self.facts, story_quest=5)):
            with self.assertRaises(ValueError):
                rule.qualifies(15, facts)

    def test_purchase_select_relogin_and_original_profile_projection(self):
        for shop in ("bgstore_01_0001_0001", "bgstore_11_0001_0001"):
            self.assertTrue(self.call("politic/shop/buyBackgroundItem", shopItemId=shop)["succeeded"])
        self.assertEqual(self.saved()["resources"]["credit"]["amount"], 664)
        result = self.call("politic/map/setBackground", mapId=1,
                           nearGround="item13_0000004", farGround="item14_1000048")
        self.assertTrue(result["succeeded"])
        self.session, _ = self.service._issue_login("research331-a")
        profile = self.group.map_profile(self.saved())
        self.assertEqual(profile, {"name": "隔离测试支城", "nearGround": "item13_0000004", "farGround": "item14_1000048"})
        self.assertNotIn("0", self.saved()["mapBackgrounds"])
        before = self.saved()
        self.call("politic/shop/buyBackgroundItem", shopItemId="bgstore_01_0001_0001")
        self.assertEqual(before, self.saved())

    def test_unknown_providers_legacy_bits_wrong_owner_and_missing_map_cannot_open(self):
        for facts in (True, replace(self.facts, player_id="other"), replace(self.facts, story_complete=0),
                      replace(self.facts, kokudaka=7499), replace(self.facts, map_key="map001"),
                      replace(self.facts, map_data={})):
            self.group.acquire_facts = lambda p, f=facts: f
            self.fails("politic/shop/buyBackgroundItem", shopItemId="bgstore_01_0001_0001")
        self.group.acquire_facts = None
        p = self.saved(); p["unlockBits"] = 0x0fffffff; self.save(p)
        for api in BG_APIS:
            self.fails(api, mapId=1)

    def test_latched_unlock_does_not_revoke_when_current_kokudaka_falls(self):
        self.assertTrue(self.call("politic/shop/getBackgroundItems", category="near")["succeeded"])
        self.facts = replace(self.facts, kokudaka=100)
        self.assertTrue(self.call("politic/shop/buyBackgroundItem", shopItemId="bgstore_01_0001_0001")["succeeded"])
        p = self.saved(); p["citySubcityAccessV1"]["kokudaka"] = 100; self.save(p)
        self.fails("politic/shop/getBackgroundItems", category="near")

    def test_bad_selection_empty_categories_and_purchase_failure_rollback(self):
        self.fails("politic/map/getBackgrounds")
        self.assertNotIn("citySubcityAccessV1", self.saved())
        self.fails("politic/map/setBackground", mapId=0, nearGround="item13_0000004", farGround="item14_1000048")
        p = self.saved(); p["resources"]["credit"]["amount"] = 167; self.save(p)
        self.fails("politic/shop/buyBackgroundItem", shopItemId="bgstore_01_0001_0001")
        self.assertNotIn("citySubcityAccessV1", self.saved())

    def test_mission_c_and_map_materialization_are_both_required(self):
        p = self.saved(); p["missions"]["306"] = "F"; self.save(p)
        self.fails("politic/shop/getBackgroundItems", category="near")
        self.assertNotIn("citySubcityAccessV1", self.saved())

    def test_purchase_concurrency_and_cas_conflict_no_double_charge(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.call("politic/shop/buyBackgroundItem", shopItemId="bgstore_01_0001_0001"), range(16)))
        self.assertEqual(self.saved()["resources"]["credit"]["amount"], 832)
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("injected")):
            self.fails("politic/shop/buyBackgroundItem", shopItemId="bgstore_11_0001_0001")


if __name__ == "__main__":
    unittest.main()
