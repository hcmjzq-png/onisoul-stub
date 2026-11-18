"""Base kokudaka updates use the same installed buildings across reads/writes."""
import copy
import unittest

from app.business.city_kokudaka import KokudakaError, main_city_kokudaka
from tests import test_city_services as city


class CityKokudakaTest(unittest.TestCase):
    setUp = city.CityTest.setUp
    saved = city.CityTest.saved
    save = city.CityTest.save
    call = city.CityTest.call
    failed_without_writes = city.CityTest.failed_without_writes

    def test_old_zero_cache_is_rebuilt_on_login_queries(self):
        player = self.saved()
        player["kokudaka"] = 0
        self.save(player)
        result = self.call("common/getPlayerParams")
        self.assertEqual(result["kokudaka"], 20)
        self.assertEqual(self.saved()["kokudaka"], 20)
        self.assertEqual(self.call("politic/mypage/getPlayerProfile")["eachKokudaka"], {"0": 20.0})
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 20)

    def test_construction_completion_and_retry_do_not_double_count(self):
        placed = self.call("politic/task/submitBuildTask", draftId="draft2000041", originCoord=[20, 20])
        self.assertTrue(placed["succeeded"], placed)
        self.assertEqual(placed["kokudaka"], 20)
        result = self.call("politic/task/completeTasks", buildingIds=[placed["buildingId"]])
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["kokudaka"], 30)
        result = self.call("politic/task/completeTasks", buildingIds=[placed["buildingId"]])
        self.assertEqual(result["kokudaka"], 30)
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 30)

    def test_upgrade_storage_redeployment_and_move_refresh_same_score(self):
        player = self.saved()
        player["buildings"]["1"]["exp"] = 100
        self.save(player)
        result = self.call("politic/building/levelUpBuilding", buildingId=1)
        self.assertTrue(result["succeeded"], result)
        self.assertEqual(result["kokudaka"], 23)
        stored = self.call("politic/building/putInBuildings", buildingIds=[1])
        self.assertTrue(stored["succeeded"], stored)
        self.assertEqual(stored["kokudaka"], 10)
        deployed = self.call("politic/building/deployBuilding", buildingId=1, originCoord=[10, 10])
        self.assertTrue(deployed["succeeded"], deployed)
        self.assertEqual(deployed["kokudaka"], 23)
        moved = self.call("politic/map/relocateEnded", relocatedGrids={"x12y10": 1, "x16y10": 2})
        self.assertTrue(moved["succeeded"], moved)
        self.assertNotIn("kokudaka", moved)
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 23)

    def test_production_and_officer_assignment_do_not_remove_base_building_score(self):
        player = self.saved()
        player["buildings"]["1"]["status"] = "producing"
        player["decks"]["politic"]["0"]["ids"] = {"0": 1.0}
        self.save(player)
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 20)
        player = self.saved()
        player["buildings"]["1"]["status"] = "dead"
        self.save(player)
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 20)

    def test_storage_and_other_maps_do_not_count_as_installed_main_city(self):
        player = self.saved()
        player["buildings"]["1"]["deployedMapKey"] = "none"
        player["buildings"]["2"]["deployedMapKey"] = "map002"
        self.save(player)
        self.assertEqual(self.call("common/getPlayerParams")["kokudaka"], 0)

    def test_unknown_sources_or_invalid_levels_never_silently_become_zero(self):
        player = self.saved()
        rows = self.service._table("building")
        for field in ("grade", "kokudakaMin", "kokudakaMax"):
            bad = copy.deepcopy(rows)
            del bad[city.FIELD][field]
            with self.subTest(field=field), self.assertRaisesRegex(KokudakaError, "stub has no assets"):
                main_city_kokudaka(player, bad)
        for level in (None, 0, True, 1.5, 11):
            player["buildings"]["1"]["level"] = level
            with self.subTest(level=level), self.assertRaisesRegex(KokudakaError, "no stub response"):
                main_city_kokudaka(player, rows)


if __name__ == "__main__":
    unittest.main()
