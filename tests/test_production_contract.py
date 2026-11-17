"""Original recipe unlocks and rejection of unimplemented production writes."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"
QUERY = "politic/building/getProductsByBuilding"
FIRST = "product060_023_01_01_1_1"
SECOND = "product060_001_01_01_1_1"
WRITES = ["politic/task/" + name for name in
          ("submitBulkProduceTasks", "cancelTasks", "accelerateProduceTask")]


class ProductionContractTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        base = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        city = TableCatalog(FIXTURES / "city", FIXTURES / "city/table_list.tsv")
        product = TableCatalog(FIXTURES / "production", FIXTURES / "production/table_list.tsv")
        catalog = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        catalog.load = lambda name: (product if name == "product" else city if name in {"building", "draft", "building_level", "defines"} else base).load(name)
        self.service = GameplayService(catalog=catalog, load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.session, _ = self.service._issue_login("production-test")
        created = self.service.create_player({"username": "production-test", "countryId": "country01",
                    "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        self.assertTrue(created["succeeded"])
        p = self.saved()
        p["drafts"]["draft2000041"] = 2
        self.service._build_from_draft(p, "draft2000041", (10, 10), completed=True)
        self.service._build_from_draft(p, "draft2000041", (14, 10), completed=False)
        self.save(p)
        self.call("common/getPlayerParams")

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, p):
        self.states.save(p, self.session["playerId"])

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def test_player_level_unlocks_recipes_independently_of_building_level(self):
        self.assertEqual(self.call(QUERY, buildingId=1)["products"], {FIRST: {}})
        p = self.saved(); p["buildings"]["1"]["level"] = 10; self.save(p)
        self.assertEqual(self.call(QUERY, buildingId=1)["products"], {FIRST: {}})
        p = self.saved(); p["entity"]["level"] = 5; p["buildings"]["1"]["level"] = 1; self.save(p)
        result = self.call(QUERY, buildingId=1)
        self.assertEqual(set(result["products"]), {FIRST, SECOND})
        # PoliticFSMProduct adds these keys itself with Hashtable.Add.
        self.assertNotIn("level", result)
        self.assertNotIn("buildingTypeId", result)

    def test_query_does_not_start_production_or_spend_and_survives_reload(self):
        before = self.saved()
        for _ in range(2):
            self.assertTrue(self.call(QUERY, buildingId=1)["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_query_requires_authentication_owned_deployed_building_and_integral_id(self):
        self.assertFalse(self.registry.dispatch(QUERY, {"buildingId": 1}, None)[1]["succeeded"])
        before = self.saved()
        for key in (True, 1.5, 0, 999, [], None):
            self.assertFalse(self.call(QUERY, buildingId=key)["succeeded"])
        self.assertEqual(self.saved(), before)
        p = self.saved(); p["buildings"]["1"]["deployedMapKey"] = "none"; self.save(p)
        self.assertFalse(self.call(QUERY, buildingId=1)["succeeded"])

    def test_missing_product_table_or_row_is_asset_error_not_empty_success(self):
        load = self.service.catalog.load
        for mode in ("table", "row"):
            def missing(name):
                if name != "product":
                    return load(name)
                if mode == "table":
                    raise MissingTableError("product")
                return {}
            with patch.object(self.service.catalog, "load", side_effect=missing):
                result = self.call(QUERY, buildingId=1)
                self.assertFalse(result["succeeded"])
                self.assertIn("stub has no assets", result["message"])

    def test_unverified_mission_gate_is_not_silently_unlocked(self):
        load = self.service.catalog.load
        products = copy.deepcopy(load("product")); products[FIRST]["openMission"] = "unverified"
        with patch.object(self.service.catalog, "load", side_effect=lambda name: products if name == "product" else load(name)):
            self.assertFalse(self.call(QUERY, buildingId=1)["succeeded"])

    def test_blocked_production_writes_stay_placeholders_and_never_change_state(self):
        before = self.saved()
        for api in WRITES:
            body = self.call(api, buildingId=1, buildingIds=[1], productId=FIRST, productIds=[FIRST])
            self.assertFalse(body["succeeded"])
            self.assertIn("no stub response", body["message"])
            self.assertEqual(body["errorReason"], body["message"])
            self.assertEqual(self.registry._handlers[api].__module__, "app.business.placeholders")
        self.assertEqual(self.saved(), before)

    def test_mixed_harvest_and_construction_batch_fails_before_any_completion(self):
        p = self.saved(); p["buildings"]["2"]["remainedClickCount"] = 0
        p["produce"]["1"] = {"productId": FIRST, "createdTime": 1, "dueTime": 2}
        self.save(p); before = self.saved()
        self.assertFalse(self.call("politic/task/completeTasks", buildingIds=[2, 1])["succeeded"])
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.call("politic/task/completeTasks", buildingIds=[2])["succeeded"])
        self.assertEqual(self.saved()["produce"], before["produce"])

    def test_producing_status_without_task_cannot_be_falsely_harvested(self):
        p = self.saved(); p["buildings"]["1"]["status"] = "producing"; self.save(p)
        before = self.saved()
        self.assertFalse(self.call("politic/task/completeTasks", buildingIds=[1])["succeeded"])
        self.assertEqual(self.saved(), before)


if __name__ == "__main__":
    unittest.main()
