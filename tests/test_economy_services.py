"""D-group read semantics, protocol shape and absence of state side effects."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
import threading

from app.business.economy_services import EconomyServices, ResourceListing, ResourceSnapshot
from app.business.gameplay import GameplayService
from app.business.economy_shop_services import EconomyShopServices, NationalShopContext
from app.state import StateConflictError
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError, TableError
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"


class EconomyServicesTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.session = self.sessions.issue("economy-reader")
        self.other = self.sessions.issue("economy-other")
        self.states.save({"private": "reader", "resources": {"gold": {"amount": 11}}}, self.session["playerId"])
        self.states.save({"private": "other"}, self.other["playerId"])
        self.before = copy.deepcopy(self.states.rows)
        data = json.loads((FIXTURES / "economy" / "resource_snapshot.json").read_text())
        self.snapshot = ResourceSnapshot(data["observed_at"], tuple(ResourceListing(**row) for row in data["listings"]))
        self.provider = Mock(side_effect=lambda: self.snapshot)
        self.reload()

    def reload(self):
        tables = FIXTURES / "gameplay" / "tables"
        self.service = GameplayService(catalog=TableCatalog(tables, tables / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.economy = EconomyServices(self.service, self.provider)
        self.registry = Registry()
        self.economy.register(self.registry)

    def call(self, search=False, session=None, **params):
        request = dict(page_index="0", item_per_page="300", sortby="remain_time", order="ascending")
        if search:
            request.update(resource_type="all", price_min="1", price_max="9999", amount_min="1", amount_max="999999999")
        request.update(params)
        status, body = self.registry.dispatch("auction/auctionResource" + ("Search" if search else "Browse"),
                                             request, self.session if session is None else session)
        self.assertEqual(status, 200, body)
        return body

    def ids(self, result):
        return [row["item_sn"] for row in result.values()]

    def test_browse_bare_rows_no_expired_or_private_fields(self):
        result = self.call()
        self.assertEqual(self.ids(result), ["listing-b", "listing-c", "listing-a"])
        self.assertEqual(set(result), {"0", "1", "2"})
        for row in result.values():
            self.assertEqual(set(row), {"item_sn", "resource_type", "price", "num", "period", "remain_time"})
            self.assertTrue(all(isinstance(value, str) for value in row.values()))
        self.assertEqual(result["0"]["remain_time"], "10")
        self.assertEqual(self.provider.call_count, 1)

    def test_search_inclusive_ranges_and_resource_filter(self):
        result = self.call(True, resource_type="gold", price_min="99", price_max="100", amount_min="999", amount_max="1000")
        self.assertEqual(self.ids(result), ["listing-b", "listing-a"])
        self.assertEqual(self.ids(self.call(True, resource_type="food")), ["listing-c"])
        self.assertEqual(self.call(True, resource_type="iron"), {})

    def test_sort_before_paging_and_stable_ties(self):
        self.assertEqual(self.ids(self.call(sortby="credit", item_per_page="1", page_index="1")), ["listing-a"])
        self.assertEqual(self.ids(self.call(sortby="amount", order="descending")), ["listing-a", "listing-b", "listing-c"])
        self.assertEqual(self.call(page_index="10"), {})

    def test_invalid_inputs_never_read_market(self):
        for changes in ({"page_index": True}, {"page_index": "-1"}, {"page_index": "1e2"},
                        {"item_per_page": 0}, {"item_per_page": "301"}, {"page_index": 1.5},
                        {"page_index": "９"}, {"page_index": "1" * 20}, {"sortby": "grade"},
                        {"order": []}, {"page_index": float("nan")}):
            self.assertIn("errorReason", self.call(**changes))
        for changes in ({"price_min": ""}, {"price_min": "10000"}, {"resource_type": "credit"},
                        {"resource_type": {}}, {"amount_max": "0"}):
            self.assertIn("errorReason", self.call(True, **changes))
        self.provider.assert_not_called()

    def test_authentication_and_parameter_cannot_select_private_player(self):
        self.assertIn("errorReason", self.call(session={}))
        self.provider.assert_not_called()
        self.assertEqual(self.call(playerId=self.other["playerId"]), self.call(session=self.other))
        self.assertEqual(self.states.rows, self.before)

    def test_missing_provider_is_business_failure_not_empty_success_or_assets(self):
        self.economy.resource_snapshot = None
        body = self.call()
        self.assertIn("no stub response", body["errorReason"])
        self.assertNotIn("stub has no assets", body["errorReason"])

    def test_retries_reload_and_concurrency_do_not_write_or_normalize_accounts(self):
        expected = self.call()
        self.reload()
        self.assertEqual(self.call(), expected)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(), range(32)))
        self.assertTrue(all(result == expected for result in results))
        self.assertEqual(self.states.rows, self.before)

    def test_each_query_uses_one_snapshot_and_response_is_detached(self):
        result = self.call()
        result["0"]["price"] = "0"
        self.snapshot = replace(self.snapshot, observed_at=1010)
        self.assertEqual(self.ids(self.call()), ["listing-c", "listing-a"])
        self.assertEqual(self.snapshot.listings[1].price, 99)
        self.assertEqual(self.provider.call_count, 2)

    def test_corrupt_snapshot_rejected_without_partial_rows(self):
        first = self.snapshot.listings[0]
        for bad in (replace(first, num=0), replace(first, resource_type="credit"), first):
            self.snapshot = ResourceSnapshot(1000, (first, bad))
            self.assertEqual(set(self.call()), {"errorReason"})
        self.assertEqual(self.states.rows, self.before)

    def test_only_two_read_handlers_registered(self):
        self.assertEqual(self.registry.known(), {"auction/auctionResourceBrowse", "auction/auctionResourceSearch"})


class EconomyShopServicesTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.power, self.period, self.context_active = 20000, "test-period-1", False
        self.gate_lock = threading.RLock()
        self.reload()
        self.session, _ = self.service._issue_login("economy-shop")
        self.service.create_player(dict(username="economy", countryId="country01", navigatorId="navi8000101", colorIndex="color1"), self.session)
        player = self.saved()
        player["resources"]["credit"]["amount"] = 500
        player["resources"]["gold"]["amount"] = 5000
        self.states.save(player, self.session["playerId"])

    @contextmanager
    def gate(self, country):
        with self.gate_lock:
            self.context_active = True
            try:
                yield NationalShopContext(country, self.period, self.power)
            finally:
                self.context_active = False

    def reload(self):
        base = FIXTURES / "gameplay/tables"
        catalog = TableCatalog(base, base / "table_list.tsv")
        original = catalog.load
        self.samples = {p.stem: json.loads(p.read_text(encoding="utf-8"))[p.stem]
                        for p in (FIXTURES / "economy/shop_tables").glob("*.json")}
        def load(name):
            if name not in self.samples:
                return original(name)
            try:
                result = copy.deepcopy(original(name))
            except TableError:
                result = {}
            result.update(copy.deepcopy(self.samples[name]))
            return result
        catalog.load = load
        self.service = GameplayService(catalog=catalog, load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.shop = EconomyShopServices(self.service, static_background_sales=True, national_context=self.gate)
        self.registry = Registry()
        self.shop.register(self.registry)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def call(self, name, session=None, **params):
        status, body = self.registry.dispatch("politic/shop/" + name, params,
                                             self.session if session is None else session)
        self.assertEqual(status, 200, body)
        return body

    def background(self, **params):
        return self.call("buyBackgroundItem", **{**dict(shopItemId="bgstore_01_0001_0001"), **params})

    def national(self, **params):
        return self.call("buyShopItemFromNationalPower", **{**dict(shopItemId="np_shop0000001", index=-1, quantity=1), **params})

    def test_background_price_inventory_reload_and_retry(self):
        result = self.background()
        self.assertEqual(result["resources"]["credit"]["amount"], 332)
        self.assertEqual(self.saved()["items"]["item13_0000004"], 1)
        self.reload()
        before = self.saved()
        self.assertTrue(self.background()["succeeded"])
        self.assertEqual(self.saved(), before)
        self.assertNotIn("bgstore_01_0001_0001", self.call("getBackgroundItems", category="near")["shopItems"])
        result = self.background(shopItemId="bgstore_11_0001_0001")
        self.assertEqual(result["resources"]["credit"]["amount"], 164)
        self.assertEqual(self.saved()["items"]["item14_1000048"], 1)

    def test_background_disabled_invalid_missing_and_insufficient_never_write(self):
        for code in ("unknown", [], "bgstore_01_0001_0003"):
            before = self.saved()
            self.assertIn("errorReason", self.background(shopItemId=code))
            self.assertEqual(self.saved(), before)
        player = self.saved(); player["resources"]["credit"]["amount"] = 167
        self.states.save(player, self.session["playerId"])
        self.assertIn("errorReason", self.background())
        self.assertEqual(self.saved(), player)

    def test_auth_and_foreign_player_parameter_never_selects_another_account(self):
        other = self.sessions.issue("shop-other")
        self.states.save({"sentinel": "untouched"}, other["playerId"])
        before = copy.deepcopy(self.states.rows)
        self.assertIn("errorReason", self.call("buyBackgroundItem", session={}, shopItemId="bgstore_01_0001_0001"))
        self.assertEqual(self.states.rows, before)
        self.assertTrue(self.background(playerId=other["playerId"], countryId="country02")["succeeded"])
        self.assertEqual(self.states.load(other["playerId"]), {"sentinel": "untouched"})

    def test_sales_policies_default_closed(self):
        self.shop.static_background_sales = False
        self.shop.national_context = None
        before = self.saved()
        for result in (self.background(), self.national(), self.call("getBackgroundItems", category="near"),
                       self.call("getShopItemsFromNationalPower")):
            self.assertIn("no stub response", result["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_queries_do_not_write_and_failure_types_stay_distinct(self):
        before = self.saved()
        self.assertEqual(len(self.call("getBackgroundItems", category="far")["shopItems"]), 2)
        self.call("getShopItemsFromNationalPower")
        self.assertEqual(self.saved(), before)
        original = self.service.catalog.load
        def missing(name):
            if name == "item13":
                raise MissingTableError("test missing file")
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=missing):
            self.assertIn("stub has no assets", self.background()["errorReason"])
        self.samples["shop_item_bg"]["bgstore_01_0001_0001"]["itemIds"] = ["item13_missing"]
        result = self.background()
        self.assertIn("no stub response", result["errorReason"])
        self.assertNotIn("stub has no assets", result["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_wrong_country_context_and_save_failure_leave_no_grant(self):
        from contextlib import nullcontext
        before = self.saved()
        self.shop.national_context = lambda _: nullcontext(NationalShopContext("country02", "test", 99999))
        self.assertIn("errorReason", self.national())
        self.assertEqual(self.saved(), before)
        self.shop.national_context = self.gate
        with patch.object(self.service, "_save", side_effect=RuntimeError("simulated precommit failure")):
            status, _ = self.registry.dispatch("politic/shop/buyShopItemFromNationalPower",
                dict(shopItemId="np_shop0000001", index=-1, quantity=1), self.session)
            self.assertEqual(status, 500)
        self.assertFalse(self.context_active)
        self.assertEqual(self.saved(), before)

    def test_national_boundary_country_mapping_and_quota_persist(self):
        self.power = 19999
        before = self.saved()
        row = self.call("getShopItemsFromNationalPower")["shopItems"]["np_shop0000001"]
        self.assertEqual(row, {"state": "lock", "remain": 1.0})
        self.assertIn("errorReason", self.national())
        self.assertEqual(self.saved(), before)
        self.power = 20000
        expected_item = self.samples["shop_item_country"]["countryshop_00003"]["country01"]
        self.assertEqual(self.national()["resources"]["gold"]["amount"], 3000)
        self.assertEqual(self.saved()["items"][expected_item], 1)
        self.reload()
        before = self.saved()
        self.assertIn("already purchased", self.national()["errorReason"])
        self.assertEqual(self.saved(), before)
        row = self.call("getShopItemsFromNationalPower")["shopItems"]["np_shop0000001"]
        self.assertEqual(row, {"state": "open", "remain": 0.0})

    def test_national_country02_uses_its_own_draft(self):
        player = self.saved(); player["entity"]["country"] = "country02"
        self.states.save(player, self.session["playerId"])
        self.assertTrue(self.national(countryId="country01")["succeeded"])
        item = self.samples["shop_item_country"]["countryshop_00003"]["country02"]
        self.assertEqual(self.saved()["items"][item], 1)

    def test_national_bad_quantity_index_wider_quota_and_funds(self):
        before = self.saved()
        for params in ({"quantity": 0}, {"quantity": 2}, {"quantity": True}, {"index": 0},
                       {"index": -2}, {"shopItemId": "np_shop0000009"}):
            self.assertIn("errorReason", self.national(**params))
            self.assertEqual(self.saved(), before)
        player = self.saved(); player["resources"]["gold"]["amount"] = 1999
        self.states.save(player, self.session["playerId"])
        self.assertIn("errorReason", self.national())
        self.assertEqual(self.saved(), player)

    def test_national_capacity_and_missing_reference_fail_before_charge(self):
        item = self.samples["shop_item_country"]["countryshop_00003"]["country01"]
        player = self.saved(); player["items"][item] = 99
        self.states.save(player, self.session["playerId"])
        self.assertIn("capacity", self.national()["errorReason"])
        self.assertEqual(self.saved(), player)
        self.samples["national_power_shop_item"]["np_shop0000001"]["goal"] = "not-a-goal"
        result = self.national()
        self.assertIn("no stub response", result["errorReason"])
        self.assertNotIn("stub has no assets", result["errorReason"])

    def test_national_gate_pinned_through_save_and_only_explicit_new_period_resets(self):
        save = self.service._save
        def checked_save(player, player_id):
            self.assertTrue(self.context_active)
            save(player, player_id)
        with patch.object(self.service, "_save", side_effect=checked_save):
            self.assertTrue(self.national()["succeeded"])
        self.assertFalse(self.context_active)
        self.assertIn("errorReason", self.national(period="spoof", power=999999))
        self.period = "test-period-2"
        self.assertTrue(self.national()["succeeded"])
        self.period = "test-period-1"
        self.assertIn("errorReason", self.national())

    def test_conflict_rolls_back_currency_inventory_and_ledger(self):
        for purchase in (self.background, self.national):
            before = self.saved()
            with patch.object(self.service, "_save", side_effect=StateConflictError("test")):
                self.assertIn("errorReason", purchase())
            self.assertEqual(self.saved(), before)
            self.assertTrue(purchase()["succeeded"])

    def test_background_and_national_concurrent_retries_charge_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.background(), range(16)))
        self.assertTrue(all(r["succeeded"] for r in results))
        self.assertEqual(self.saved()["resources"]["credit"]["amount"], 332)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.national(), range(16)))
        self.assertEqual(sum(r.get("succeeded") is True for r in results), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 3000)


if __name__ == "__main__":
    unittest.main()
