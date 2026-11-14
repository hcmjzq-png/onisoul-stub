"""Atomic city writes and original road/level rules against verified table subsets."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"
FIELD = "building200_041_01_01_1_1"


class CityTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        base = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        self.original = TableCatalog(FIXTURES / "city", FIXTURES / "city/table_list.tsv")
        catalog = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        catalog.load = lambda name: (self.original if name in {"building", "draft", "building_level", "defines"} else base).load(name)
        self.service = GameplayService(catalog=catalog, load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.session, _ = self.service._issue_login("city-test")
        self.service.create_player({"username": "city-test", "countryId": "country01", "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        p = self.saved()
        p["resources"]["gold"]["amount"] = 5000
        p["actionPoints"]["politicPoint"]["point"] = 50
        p["drafts"]["draft2000041"] = 3
        for position in [(10, 10), (14, 10)]:
            self.service._build_from_draft(p, "draft2000041", position, completed=True)
        self.save(p)
        self.call("common/getPlayerParams")  # settle existing derived counters

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, p):
        self.states.save(p, self.session["playerId"])

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def failed_without_writes(self, api, **params):
        before = self.saved()
        body = self.call(api, **params)
        self.assertFalse(body["succeeded"], body)
        self.assertEqual(self.saved(), before)
        return body

    def test_all_original_roads_are_free_even_at_zero_points_and_gold(self):
        p = self.saved(); p["resources"]["gold"]["amount"] = 0; p["actionPoints"]["politicPoint"]["point"] = 0; self.save(p)
        for i, code in enumerate(["draft2000051", "draft2000052", "draft2000053"]):
            self.assertTrue(self.call("politic/task/submitBuildAndComplete", draftId=code, originCoord=[20+i, 20])["succeeded"])
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], 0)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 0)
        self.assertFalse(any(code in self.saved()["drafts"] for code in ["draft2000051", "draft2000052", "draft2000053"]))

    def test_normal_build_requires_points_and_integral_coordinates(self):
        for pos in ([20.5, 20], [True, 20], [20, 20, 21]):
            self.failed_without_writes("politic/task/submitBuildTask", draftId="draft2000041", originCoord=pos)
        p = self.saved(); p["actionPoints"]["politicPoint"]["point"] = 0; self.save(p)
        self.failed_without_writes("politic/task/submitBuildTask", draftId="draft2000041", originCoord=[20, 20])

    def test_bulk_roads_match_client_coordinate_maps_and_retries_do_not_duplicate(self):
        api = "politic/task/submitBulkBuildAndComplete"
        params = {"draftId": "draft2000051", "originCoords": [[20, 20], [21, 20]]}
        before = self.saved()
        body = self.call(api, **params)
        self.assertEqual(body["originCoords"], {"3": {"0": 20.0, "1": 20.0}, "4": {"0": 21.0, "1": 20.0}})
        self.assertEqual(body["autoProducings"], {})
        self.assertEqual(set(body["buildings"]), {"3", "4"})
        self.assertEqual(self.saved()["actionPoints"], before["actionPoints"])
        self.assertEqual(self.saved()["resources"], before["resources"])
        after = self.saved(); self.call(api, **params); self.assertEqual(self.saved(), after)

    def test_serial_road_count_matches_original_numeric_row_consumer(self):
        body = self.call("politic/task/submitSerialBuildAndComplete", draftId="draft2000051", originCoords=[[20, 20], [21, 20]])
        self.assertEqual(set(body), {"0", "1", "autoProducings", "now"})
        self.assertEqual(len(body) - 2, 2)
        for index in range(len(body) - 2):
            self.assertIn("building", body[str(index)])
            self.assertEqual(body[str(index)]["x"], 20 + index)
        self.failed_without_writes("politic/task/submitSerialBuildAndComplete", draftId="draft2000051", originCoords=[[10, 10]])

    def test_bulk_road_rejects_partial_placement_invalid_shapes_and_other_drafts(self):
        api = "politic/task/submitBulkBuildAndComplete"
        for coords in ([[20, 20], [10, 10]], [[20, 20], [20, 20]], [[-1, 0]], [[20.1, 20]], [], [[10000, 20]]):
            self.failed_without_writes(api, draftId="draft2000051", originCoords=coords)
        self.failed_without_writes(api, draftId="draft2000041", originCoords=[[20, 20]])

    def test_relocation_can_swap_footprints_without_spending_and_survives_reload(self):
        p = self.saved()
        self.assertTrue(self.call("politic/map/relocateEnded", relocatedGrids={"x14y10": 1, "x10y10": 2})["succeeded"])
        after = self.saved()
        self.assertEqual(after["occupiedGrids"], {"14,10": "1", "10,10": "2"})
        self.assertEqual(after["resources"], p["resources"])
        self.assertEqual(after["actionPoints"], p["actionPoints"])
        self.assertEqual(self.call("politic/map/getMapData")["map"]["occupiedGrids"], after["occupiedGrids"])

    def test_relocation_rejects_overlap_omission_unknown_ids_and_outside_map_atomically(self):
        for value in ({"x14y10": 1}, {"x10y10": 1, "x11y10": 2}, {"x0y0": 1, "x14y10": 2},
                      {"x10y10": 1, "x14y10": 999}, {"x10y10": 1, "x14y10": 1}, {"10,10": 1, "x14y10": 2}):
            self.failed_without_writes("politic/map/relocateEnded", relocatedGrids=value)

    def test_storage_roundtrip_keeps_identity_and_frees_footprint(self):
        p = self.saved(); p["buildings"]["1"].update(exp=123, level=3); self.save(p)
        self.assertTrue(self.call("politic/building/putInBuildings", buildingIds=[1])["succeeded"])
        after = self.saved(); self.call("politic/building/putInBuildings", buildingIds=[1]); self.assertEqual(self.saved(), after)
        self.assertEqual(self.saved()["buildings"]["1"]["deployedMapKey"], "none")
        self.assertNotIn("10,10", self.saved()["occupiedGrids"])
        self.assertTrue(self.call("politic/task/submitBuildAndComplete", draftId="draft2000041", originCoord=[10, 10])["succeeded"])
        self.failed_without_writes("politic/building/deployBuilding", buildingId=1, originCoord=[10, 10])
        result = self.call("politic/building/deployBuilding", buildingId=1, originCoord=[20, 20])
        self.assertEqual(result["buildingId"], 1.0)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (3, 123))
        self.assertEqual(result["autoProducings"], {})
        after = self.saved(); self.call("politic/building/deployBuilding", buildingId=1, originCoord=[20, 20]); self.assertEqual(self.saved(), after)

    def test_active_production_is_not_moved_cancelled_or_put_in_storage(self):
        p = self.saved(); p["produce"]["1"] = {"productId": "in-progress", "dueTime": 9999999999}; self.save(p)
        self.failed_without_writes("politic/building/putInBuildings", buildingIds=[2, 1])
        self.failed_without_writes("politic/map/relocateEnded", relocatedGrids={"x14y10": 1, "x10y10": 2})
        self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)

    def test_road_storage_is_not_misrepresented_as_inventory(self):
        road = self.call("politic/task/submitBuildAndComplete", draftId="draft2000051", originCoord=[20, 20])
        self.failed_without_writes("politic/building/putInBuildings", buildingIds=[int(road["buildingId"])])

    def test_upgrade_consumes_original_per_level_experience_cost_and_point(self):
        p = self.saved(); p["buildings"]["1"]["exp"] = 120; self.save(p)
        result = self.call("politic/building/levelUpBuilding", buildingId=1)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (2, 100))
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], p["resources"]["gold"]["amount"] - 100)
        self.assertEqual(self.saved()["actionPoints"]["politicPoint"]["point"], p["actionPoints"]["politicPoint"]["point"] - 1)
        result = self.call("politic/building/levelUpBuilding", buildingId=1)
        self.assertEqual((result["building"]["level"], result["building"]["exp"]), (3, 0))
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], p["resources"]["gold"]["amount"] - 240)
        self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)

    def test_batch_and_collective_use_different_verified_response_roots(self):
        p = self.saved(); p["buildings"]["1"]["exp"] = 120; p["buildings"]["2"]["exp"] = 120; self.save(p)
        result = self.call("politic/building/levelUpBuildings", buildingIds=[1, 2])
        self.assertEqual(set(result["output_buildings"]), {"1", "2"})
        result = self.call("politic/building/levelUpBuildingCollectively", buildingIds=["1", "2"], levelUpTimes=[1, 1])
        self.assertEqual(result["totalUsedPoint"], 2.0)
        self.assertEqual(result["restResources"], self.saved()["resources"])
        self.assertEqual([r["level"] for r in result["resultBuildings"].values()], [3, 3])

    def test_upgrade_batch_failure_does_not_spend_or_partially_upgrade(self):
        p = self.saved(); p["buildings"]["1"]["exp"] = 120; self.save(p)
        self.failed_without_writes("politic/building/levelUpBuildings", buildingIds=[1, 2])
        self.failed_without_writes("politic/building/levelUpBuildingCollectively", buildingIds=[1], levelUpTimes=[3])
        for bad in ([True], [0], [-1], [1.1], [], [1, 2]):
            self.failed_without_writes("politic/building/levelUpBuildingCollectively", buildingIds=[1], levelUpTimes=bad)
        self.failed_without_writes("politic/building/levelUpBuildings", buildingIds=[1, 1])
        p = self.saved(); p["resources"]["gold"]["amount"] = 99; self.save(p)
        self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)
        p["resources"]["gold"]["amount"] = 1000; p["actionPoints"]["politicPoint"]["point"] = 0; self.save(p)
        self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)

    def test_maximum_level_and_missing_table_cannot_consume(self):
        p = self.saved(); p["buildings"]["1"].update(level=10, exp=999999); self.save(p)
        self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)
        original = self.service.catalog.load
        def load(name):
            if name == "building_level":
                raise MissingTableError(name)
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=load):
            result = self.failed_without_writes("politic/building/levelUpBuilding", buildingId=1)
            self.assertIn("stub has no assets", result["errorReason"])

    def test_concurrent_upgrade_cannot_reuse_same_experience(self):
        p = self.saved(); p["buildings"]["1"]["exp"] = 20; self.save(p)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("politic/building/levelUpBuilding", buildingId=1), range(2)))
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        self.assertEqual(self.saved()["buildings"]["1"]["level"], 2)

    def test_new_routes_require_authenticated_created_player(self):
        apis = [api for api in self.registry.known() if any(api.endswith(suffix) for suffix in
                ("relocateEnded", "putInBuildings", "deployBuilding", "levelUpBuilding", "levelUpBuildings", "levelUpBuildingCollectively", "submitBulkBuildAndComplete", "submitSerialBuildAndComplete"))]
        self.assertEqual(len(apis), 8)
        for api in apis:
            self.assertFalse(self.registry.dispatch(api, {}, None)[1]["succeeded"])
