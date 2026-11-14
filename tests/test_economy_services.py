"""D-group read semantics, protocol shape and absence of state side effects."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock

from app.business.economy_services import EconomyServices, ResourceListing, ResourceSnapshot
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
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


if __name__ == "__main__":
    unittest.main()
