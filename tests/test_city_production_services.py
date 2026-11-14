"""Group A isolated state tests; fixture values are original table subsets."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.city_production_services import CityProductionServices
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemorySessions, MemoryState


class CityProductionTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / "fixtures"
        base = TableCatalog(root / "gameplay/tables", root / "gameplay/tables/table_list.tsv")
        sample = TableCatalog(root / "city_production", root / "city_production/table_list.tsv")
        self.catalog = TableCatalog(root / "gameplay/tables", root / "gameplay/tables/table_list.tsv")
        self.catalog.load = lambda name: (sample if name in {"building", "itemIdToShopId", "shop_item_bg"} else base).load(name)
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.group = CityProductionServices(self.service)
        self.group.register(self.registry)
        self.session, _ = self.service._issue_login("group-a-isolated")
        self.service.create_player({"username": "group-a", "countryId": "country01",
                                    "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        p = self.saved()
        p["buildings"] = {str(i): {"instanceId": i, "buildingTypeId": "building200_041_01_01_1_1",
                                   "level": 1, "exp": 0, "status": "waiting", "deployedMapKey": "none"}
                          for i in (1, 2)}
        p["occupiedGrids"] = {}
        p["resources"]["gold"]["amount"] = 100
        p["backgroundOwnership"] = {"nearGround": ["item13_0000004", "item13_0000005"],
                                    "farGround": ["item14_1000048", "item14_1000049"]}
        self.save(p)
        self.call("politic/map/getBackgrounds")  # settle existing derived counters

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, p):
        self.states.save(p, self.session["playerId"])

    def call(self, api, **params):
        status, result = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return result

    def failed(self, api, **params):
        before = self.saved()
        result = self.call(api, **params)
        self.assertFalse(result["succeeded"], result)
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)
        return result

    def test_sale_exact_price_and_reload_retry(self):
        before = self.saved()
        result = self.call("politic/shop/sellBuildings", buildingIds=[1, 2])
        self.assertEqual(result["gainGold"], 100.0)
        self.assertEqual(set(result["buildings"]), {"1", "2"})
        self.assertEqual(result["buildingCount"], 0.0)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 200)
        self.assertEqual(self.saved()["actionPoints"], before["actionPoints"])
        self.session, _ = self.service._issue_login("group-a-isolated")
        self.failed("politic/shop/sellBuildings", buildingIds=[1, 2])
        self.assertEqual(self.saved()["buildings"], {})

    def test_sale_batch_invalid_ownership_and_parameters_rollback(self):
        for ids in ([1, 999], [1, 1], [], [True], [1.1], "1"):
            self.failed("politic/shop/sellBuildings", buildingIds=ids)
        p = self.saved(); p["buildings"]["2"]["deployedMapKey"] = "map001"; self.save(p)
        self.failed("politic/shop/sellBuildings", buildingIds=[1, 2])

    def test_sale_rejects_active_or_stale_map_reference(self):
        for key, value in (("status", "producing"), ("status", "building")):
            p = self.saved(); p["buildings"]["2"][key] = value; self.save(p)
            self.failed("politic/shop/sellBuildings", buildingIds=[1, 2])
        p["buildings"]["2"]["status"] = "waiting"
        p["produce"]["2"] = {"productId": "synthetic-active-record"}; self.save(p)
        self.failed("politic/shop/sellBuildings", buildingIds=[1, 2])
        p["produce"] = {}; p["occupiedGrids"] = {"10,10": "2"}; self.save(p)
        self.failed("politic/shop/sellBuildings", buildingIds=[1, 2])

    def test_sale_overflow_does_not_destroy_inventory(self):
        p = self.saved(); p["resources"]["gold"]["amount"] = p["resources"]["gold"]["maxAmount"]; self.save(p)
        self.failed("politic/shop/sellBuildings", buildingIds=[1])

    def test_missing_file_and_missing_row_have_different_diagnostics(self):
        load = self.catalog.load
        def missing(name):
            if name == "itemIdToShopId":
                raise MissingTableError(name)
            return load(name)
        with patch.object(self.catalog, "load", side_effect=missing):
            result = self.failed("politic/shop/sellBuildings", buildingIds=[1])
            self.assertIn("stub has no assets", result["errorReason"])
        with patch.object(self.catalog, "load", side_effect=lambda name: {} if name == "itemIdToShopId" else load(name)):
            result = self.failed("politic/shop/sellBuildings", buildingIds=[1])
            self.assertIn("no stub response", result["errorReason"])

    def test_unsellable_sentinel_is_synthetic_rule_test(self):
        load = self.catalog.load
        prices = copy.deepcopy(load("itemIdToShopId"))
        prices["item05_0200041"]["price"] = -1  # controlled mutation, not an original building price
        with patch.object(self.catalog, "load", side_effect=lambda name: prices if name == "itemIdToShopId" else load(name)):
            self.failed("politic/shop/sellBuildings", buildingIds=[1])

    def test_concurrent_sale_pays_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("politic/shop/sellBuildings", buildingIds=[1]), range(2)))
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 150)

    def test_save_conflict_rolls_back_and_retry_pays_once(self):
        with patch.object(self.service, "save_state", side_effect=state.StateConflictError("synthetic revision conflict")):
            self.failed("politic/shop/sellBuildings", buildingIds=[1])
        self.assertTrue(self.call("politic/shop/sellBuildings", buildingIds=[1])["succeeded"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 150)

    def test_background_query_does_not_grant_and_selection_survives_login(self):
        before = self.saved()
        result = self.call("politic/map/getBackgrounds")
        self.assertEqual(result["nearGround"], {"item13_0000004": {}, "item13_0000005": {}})
        self.assertEqual(self.saved(), before)
        params = dict(mapId=0, nearGround="item13_0000005", farGround="item14_1000049")
        self.assertTrue(self.call("politic/map/setBackground", **params)["succeeded"])
        after = self.saved()
        self.call("politic/map/setBackground", **params)
        self.assertEqual(self.saved(), after)
        self.session, _ = self.service._issue_login("group-a-isolated")
        self.assertEqual(self.group.selected_background(self.saved()), {k: v for k, v in params.items() if k != "mapId"})
        self.assertEqual(self.saved()["backgroundOwnership"], before["backgroundOwnership"])
        self.assertEqual(self.saved()["resources"], before["resources"])

    def test_background_invalid_category_unowned_submap_and_empty_rollback(self):
        good = dict(mapId=0, nearGround="item13_0000004", farGround="item14_1000048")
        for bad in ({"mapId": 1}, {"mapId": True}, {"nearGround": "item14_1000048"},
                    {"farGround": "unknown"}, {"nearGround": []}):
            self.failed("politic/map/setBackground", **(good | bad))
        p = self.saved(); p["backgroundOwnership"]["nearGround"] = []; self.save(p)
        self.failed("politic/map/getBackgrounds")
        self.failed("politic/map/setBackground", **good)
        del p["backgroundOwnership"]; self.save(p)
        self.failed("politic/map/getBackgrounds")

    def test_background_conflict_and_concurrent_pairs_are_atomic(self):
        params = dict(mapId=0, nearGround="item13_0000004", farGround="item14_1000048")
        with patch.object(self.service, "save_state", side_effect=state.StateConflictError("synthetic revision conflict")):
            self.failed("politic/map/setBackground", **params)
        pairs = [params, dict(mapId=0, nearGround="item13_0000005", farGround="item14_1000049")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: self.call("politic/map/setBackground", **p), pairs))
        self.assertTrue(all(r["succeeded"] for r in results))
        self.assertIn(self.group.selected_background(self.saved()), [{k: v for k, v in p.items() if k != "mapId"} for p in pairs])

    def test_authentication_and_cross_account_ownership(self):
        for api in ("politic/shop/sellBuildings", "politic/map/getBackgrounds", "politic/map/setBackground"):
            self.assertFalse(self.registry.dispatch(api, {}, None)[1]["succeeded"])
        owner = self.session
        self.session, _ = self.service._issue_login("other-a-account")
        self.service.create_player({"username": "other-a", "countryId": "country01"}, self.session)
        self.failed("politic/shop/sellBuildings", buildingIds=[1], playerId=owner["playerId"])
        self.failed("politic/map/getBackgrounds", playerId=owner["playerId"])


if __name__ == "__main__":
    unittest.main()
