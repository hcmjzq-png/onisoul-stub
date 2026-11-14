"""Persisted player operations and purchase invariants, not just response shapes."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures" / "gameplay" / "tables"


class PlayerServicesTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("player-services")
        self.assertTrue(self.service.create_player({"username": "player-services", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)["succeeded"])

    def reload(self):
        self.service = GameplayService(catalog=TableCatalog(FIXTURES, FIXTURES / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def fund(self, amount=5000, credit=100):
        player = self.saved()
        player["resources"]["gold"]["amount"] = amount
        player["resources"]["credit"]["amount"] = credit
        self.save(player)

    def buy(self, **changes):
        return self.call("politic/shop/buyShopItem", **{**dict(shopItemId="shop0000041", index=0,
            quantity=1, storetable="shop_item"), **changes})

    def test_protection_roundtrip_idempotence_and_release(self):
        api = "deck/setCharacterProtect"
        self.assertEqual(self.call(api, characterIds=["1", 2], enable=True), {})
        self.assertEqual(self.call(api, characterIds=[1], enable=True), {})
        self.reload()
        self.assertEqual(set(self.call("deck/getProtectedCharacterIds").values()), {"1", "2"})
        self.assertEqual(self.call(api, characterIds=["1"], enable=False), {})
        self.assertEqual(set(self.call("deck/getProtectedCharacterIds").values()), {"2"})

    def test_protection_rejects_invalid_or_unowned_batch_without_partial_write(self):
        before = self.saved()
        for ids, enabled in [([1, 999], True), ([1], "false"), ([], True), ([True], True), ([1.5], True)]:
            self.assertIn("errorReason", self.call("deck/setCharacterProtect", characterIds=ids, enable=enabled))
            self.assertEqual(self.saved(), before)

    def test_equipment_and_warehouse_records_are_bare_maps_and_separate_from_owned_characters(self):
        player = self.saved()
        player["equips"] = {"7": {"baseId": "existing-equip", "grade": 1.0}}
        player["tactics"] = {"card1_00001_01": {"amount": 3.0}}
        player["storedCharacters"] = {"12": copy.deepcopy(player["characters"]["1"])}
        self.save(player)
        self.assertEqual(self.call("common/getEquips"), player["equips"])
        self.assertEqual(self.call("common/getTactics"), player["tactics"])
        self.assertEqual(self.call("deck/getCharactersInStore"), player["storedCharacters"])
        self.assertNotIn("12", self.call("common/getCharacters"))
        self.assertEqual(self.call("deck/setEquipProtect", equipIds=[7], enable=True), {})
        self.assertEqual(set(self.call("deck/getProtectedEquipIds").values()), {"7"})
        self.assertEqual(self.call("deck/setCharacterProtect", characterIds=[12], enable=True), {})

    def test_storage_info_has_client_required_timestamps_and_counts(self):
        result = self.call("deck/getCharacterStoreInfo")
        for field in ("characterCount", "extendSlot", "extendLimit", "lastOpenDate", "nextOpenLimit", "now"):
            self.assertIsInstance(result[field], float)
        self.assertEqual(result["characterCount"], 0.0)

    def test_deck_bonus_has_actual_formation_ids_without_fake_active_events(self):
        result = self.call("deck/getDeckBonus")
        expected = self.call("deck/getDecks")
        for kind, slots in result["deck"].items():
            for index, row in slots.items():
                self.assertEqual(row["id"], expected[kind]["0"]["ids"][index])
                self.assertEqual(row["bonus"], {})
        self.assertNotIn("countryRankId", result)

    def test_profile_and_main_map_name_persist_across_reload(self):
        habits = {"0": "habit0000101", "1": "habit0100101", "2": "none"}
        self.assertTrue(self.call("politic/mypage/setSelfIntroduction", message="你好", habits=habits)["succeeded"])
        self.assertEqual(self.call("politic/map/setMapName2", mapId=0, mapName="我的城"), {})
        self.reload()
        profile = self.call("politic/mypage/getPlayerProfile")
        self.assertEqual(profile["selfIntroduction"], {"message": "你好", "habits": habits})
        self.assertEqual(profile["username"], "player-services")
        self.assertEqual(profile["characterCount"], 4.0)
        self.assertEqual(self.call("politic/map/getMapData")["map"]["name"], "我的城")
        self.assertNotIn("message", profile)  # nested in selfIntroduction, not a root field

    def test_text_and_habit_validation_uses_client_tables(self):
        before = self.saved()
        for params in [dict(message="x" * 121, habits={"0": "none", "1": "none", "2": "none"}),
                       dict(message="", habits={"0": "unknown", "1": "none", "2": "none"})]:
            self.assertFalse(self.call("politic/mypage/setSelfIntroduction", **params)["succeeded"])
        for name in ("", "x" * 11, "😀" * 6, "\ud800"):
            self.assertIn("errorReason", self.call("politic/map/setMapName2", mapId=0, mapName=name))
        self.assertIn("errorReason", self.call("politic/map/setMapName2", mapId=1, mapName="支城"))
        self.assertEqual(self.saved(), before)

    def test_lessons_list_uses_table_indexes_without_marking_unread_lessons_done(self):
        result = self.call("politic/mypage/getLessonStates")
        self.assertEqual(result["states"], {"1": "L", "2": "L"})
        player = self.saved(); player["lessonsDone"] = ["lesson_00001"]; self.save(player)
        self.assertEqual(self.call("politic/mypage/getLessonStates")["states"], {"1": "C", "2": "L"})

    def test_draft_purchase_deducts_table_cost_and_updates_existing_inventory_api(self):
        self.fund()
        result = self.buy(quantity=2)
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["resources"]["gold"]["amount"], 3000)
        self.assertEqual(result["result"]["item04_0200041"], 2.0)
        self.reload()
        self.assertEqual(self.call("politic/building/getDrafts")["draft2000041"]["amount"], 2.0)

    def test_credit_price_replaces_cost_amount_and_potions_reflect_balance(self):
        self.fund()
        result = self.buy(shopItemId="shop0700006", quantity=2)
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["resources"]["credit"]["amount"], 58)  # credit=21, not costAmounts=40 + 21
        self.assertEqual(result["result"], {"item07_0010002": 2.0})
        self.assertEqual(self.call("politic/support_item/getPotions")["potions"]["potion0000102"]["amount"], 2.0)

    def test_catalogue_initial_amount_is_not_a_free_potion_grant(self):
        self.assertEqual(self.call("politic/support_item/getPotions")["potions"],
                         {"potion0000102": {"amount": 0.0}})
        self.assertEqual(self.saved()["items"], {})

    def test_country_shop_item_resolves_before_grant(self):
        self.fund(amount=50000)
        result = self.buy(shopItemId="shop0000002")
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["result"], {"item04_0200001": 1.0})
        self.assertNotIn("countryshop_00001", self.saved()["items"])

    def test_purchase_rejections_do_not_deduct_or_grant_anything(self):
        self.fund(amount=500)
        before = self.saved()
        for changes in ({}, {"quantity": -1}, {"quantity": True}, {"quantity": 1.5},
                        {"shopItemId": "missing"}, {"shopItemId": "shop0000003"},
                        {"storetable": "unverified_sale"}, {"index": 1}, {"shopItemId": "shop0900001"}):
            self.assertFalse(self.buy(**changes)["succeeded"])
            self.assertEqual(self.saved(), before)

    def test_shop_listing_excludes_unavailable_and_free_items(self):
        draft = self.call("politic/shop/getShopItems", category="draft")
        self.assertIn("shop0000041", draft["shopItems"])
        self.assertNotIn("shop0000003", draft["shopItems"])
        self.assertEqual(draft["recommendedItems"], {})
        self.assertNotIn("shop0900001", self.call("politic/shop/getShopItems", category="consumable")["shopItems"])

    def test_missing_shop_dependency_is_reported_as_asset_failure(self):
        original = self.service.catalog.load
        def load(name):
            if name == "potion":
                raise MissingTableError("missing potion table")
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=load):
            result = self.call("politic/shop/getShopItems", category="draft")
        self.assertFalse(result["succeeded"])
        self.assertIn("stub has no assets", result["errorReason"])

    def test_concurrent_purchases_cannot_overspend_same_player(self):
        self.fund(amount=1000)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.buy(), range(2)))
        self.assertEqual(sum(result["succeeded"] for result in results), 1)
        self.assertEqual(self.saved()["items"]["item04_0200041"], 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 0)

    def test_other_account_cannot_read_or_change_protected_cards(self):
        self.call("deck/setCharacterProtect", characterIds=[1], enable=True)
        other, _ = self.service._issue_login("other")
        self.assertEqual(self.registry.dispatch("deck/getProtectedCharacterIds", {}, other)[1], {})
        denied = self.registry.dispatch("deck/setCharacterProtect", {"characterIds": [1], "enable": True}, other)[1]
        self.assertIn("errorReason", denied)
        self.assertEqual(set(self.call("deck/getProtectedCharacterIds").values()), {"1"})


if __name__ == "__main__":
    unittest.main()
