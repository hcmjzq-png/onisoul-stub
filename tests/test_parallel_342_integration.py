"""Review integration via normal registration, shared locks and persisted state."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.gameplay import GameplayService
from app.main import build_registry
from app.tables import TableCatalog
from tests.test_card_growth_services import GrowthCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState


MOUNTED = {
    "politic/shop/sellBuildings", "deck/sellCharacters", "deck/sellEquips",
    "politic/lottery/getSouls", "common/getPlayerCogid", "plugin/getPluginData",
    "plugin/getPluginLog", "plugin/addPluginLog",
}
HELD = {
    "politic/map/getBackgrounds", "politic/map/setBackground", "deck/transferStoreCharacters",
    "quest/getChapterData", "quest/getQuestCompleteFlags", "quest/getQuestProgress",
    "quest/getQuestRewardOpenFlags", "auction/auctionResourceBrowse", "auction/auctionResourceSearch",
    "friend/cancelFriendOffer", "friend/dissolutionFriend", "friend/feedbackFriendOffer",
    "friend/getFriendProfile", "friend/getFriends", "friend/sendFriendOffer", "friend/updateFriendData",
    "strategy/isAlive", "ranking/getRankersInKokudaka", "ranking/getBriefOfKokudaka",
    "common/getRevisions", "plugin/setPluginData",
    # Round 2 components still need producers, migration or runtime tables.
    "quest/getQuestEncountWorks", "quest/clearObstacle", "deck/sellTactics",
    "politic/shop/getBackgroundItems", "politic/shop/buyBackgroundItem",
    "politic/shop/getShopItemsFromNationalPower", "politic/shop/buyShopItemFromNationalPower",
    "inbox/getParcels", "inbox/resolveParcels", "siege/getPairings",
    "strategy/getStrategyWinLossRecords", "trophy/getTrophyProgress",
    "trophy/completeTrophy", "trophy/messageWindowTrophy",
}


class ParallelIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        root = Path(__file__).parent / "fixtures" / "city_production"
        city = TableCatalog(root, root / "table_list.tsv")
        self.catalog = GrowthCatalog()
        growth_load = self.catalog.load
        self.catalog.load = lambda name: (city.load(name) if name in {"building", "itemIdToShopId"}
                                         else growth_load(name))
        self.reload()
        self.session, _ = self.service._issue_login("integration-342")
        self.service.create_player({"username": "review", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        p = self.saved()
        p["resources"]["gold"]["amount"] = 100
        p["characters"]["90"] = {**copy.deepcopy(p["characters"]["1"]), "baseId": "chara1_00001_01"}
        p["equips"] = {"80": {"baseId": "equip_00000_01", "grade": 1.0}}
        p["buildings"] = {"20": {"instanceId": 20, "buildingTypeId": "building200_041_01_01_1_1",
            "level": 1, "exp": 0, "status": "waiting", "deployedMapKey": "none"}}
        p["occupiedGrids"] = {}
        p["souls"] = {"red": 7}
        self.states.save(p, self.session["playerId"])

    def reload(self):
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        with patch("app.main.GameplayService", return_value=self.service):
            self.registry = build_registry()

    def saved(self):
        return self.states.load(self.session["playerId"])

    def call(self, api, **params):
        code, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(code, 200, body)
        return body

    def test_only_ready_subset_overrides_placeholders(self):
        for api in MOUNTED:
            self.assertNotEqual(self.registry._handlers[api].__module__, "app.business.placeholders", api)
        for api in HELD:
            self.assertEqual(self.registry._handlers[api].__module__, "app.business.placeholders", api)
        self.assertEqual(sum(h.__module__ == "app.business.placeholders"
                             for h in self.registry._handlers.values()), 334)

    def test_shared_transactions_survive_concurrent_calls_and_relogin(self):
        before = self.saved()
        calls = [("politic/shop/sellBuildings", {"buildingIds": [20]}),
                 ("deck/sellCharacters", {"characterIds": [90]}),
                 ("deck/sellEquips", {"equipIds": [80]}),
                 ("plugin/addPluginLog", {"logdata": {"action": "diagnostic", "reward": {"gold": 99999}}})]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda args: self.call(args[0], **args[1]), calls))
        self.assertTrue(all(r["succeeded"] for r in results))
        gain = results[0]["gainGold"] + results[1]["sellPrice"] + results[2]["sellPrice"]
        self.reload()
        self.session, _ = self.service._issue_login("integration-342")
        after = self.saved()
        self.assertEqual(after["resources"]["gold"]["amount"], 100 + gain)
        self.assertEqual(after["actionPoints"], before["actionPoints"])
        self.assertNotIn("20", after["buildings"])
        self.assertNotIn("90", self.call("common/getCharacters"))
        self.assertNotIn("80", self.call("common/getEquips"))
        self.assertEqual(len(self.call("plugin/getPluginLog")["logdatas"]), 1)
        self.assertEqual(self.call("plugin/getPluginData")["pluginTime"], {"pluginTime": 0.0})
        self.assertEqual(self.call("politic/lottery/getSouls")["red"], 7.0)
        for api, params in calls[:3]:
            self.assertIn("errorReason", self.call(api, **params))
        self.assertEqual(self.saved(), after)

    def test_save_failure_and_invalid_batch_leave_all_groups_unchanged(self):
        before = self.saved()
        self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[90, 999]))
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("review conflict")):
            result = self.call("politic/shop/sellBuildings", buildingIds=[20])
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)

    def test_authentication_identity_and_soul_root_types(self):
        before = self.saved()
        for api in MOUNTED:
            self.assertIn("errorReason", self.registry.dispatch(api, {}, None)[1], api)
        self.assertEqual(self.saved(), before)
        result = self.call("politic/lottery/getSouls")
        self.assertEqual(set(result), {"red", "blue", "purple", "yellow", "green", "black", "white"})
        self.assertTrue(all(type(value) is float for value in result.values()))
        result = self.call("common/getPlayerCogid", playerId="other")
        self.assertEqual(result["playerId"], self.session["playerId"])


if __name__ == "__main__":
    unittest.main()
