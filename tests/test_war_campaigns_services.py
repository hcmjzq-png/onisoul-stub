"""Isolated saved-observation query tests; no live campaign or client used."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import Mock

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.war_campaigns_services import WarCampaignsServices, command_cost_terms, mercenary_hire_cost
from app.tables import TableCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"


class WarCampaignsTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("f-war-test")
        self.service.create_player({"username": "f-war-test", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        self.player_id = self.session["playerId"]

    def reload(self):
        tables = FIXTURES / "gameplay" / "tables"
        self.service = GameplayService(catalog=TableCatalog(tables, tables / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        WarCampaignsServices(self.service, clock=lambda: 100).register(self.registry)

    def seed(self, alive=True, **changes):
        player = self.states.load(self.player_id)
        record = dict(ownerId=self.player_id, observedAt=90, validUntil=110, isAlive=alive)
        record.update(changes)
        player["_warCampaigns"] = {"strategy": record}
        self.states.save(player, self.player_id)

    def call(self, params=None, session=True):
        status, body = self.registry.dispatch("strategy/isAlive", params or {}, self.session if session is True else session)
        self.assertEqual(status, 200)
        return body

    def test_both_boolean_states_survive_relogin_without_defaulting(self):
        for alive in (True, False):
            self.seed(alive)
            self.reload()
            self.session, _ = self.service._issue_login("f-war-test")
            result = self.call()
            self.assertIs(result["isAlive"], alive)
            self.assertEqual(set(result), {"isAlive", "succeeded", "now"})

    def test_unavailable_is_business_failure_not_asset_failure(self):
        result = self.call()
        self.assertFalse(result["succeeded"])
        self.assertIn("no stub response", result["errorReason"])

    def test_authentication_and_cross_account_isolation(self):
        self.seed()
        self.assertIn("authentication", self.call(session=None)["errorReason"])
        other, _ = self.service._issue_login("f-war-other")
        self.assertFalse(self.call(session=other)["succeeded"])
        self.assertFalse(self.call({"playerId": other["playerId"]})["succeeded"])
        self.seed(ownerId=other["playerId"])
        self.assertFalse(self.call()["succeeded"])

    def test_invalid_and_stale_observations_never_return_success(self):
        for change in ({"isAlive": 1}, {"isAlive": "false"}, {"validUntil": 100},
                       {"observedAt": 101}, {"observedAt": -1}, {"validUntil": float("inf")},
                       {"observedAt": True}, {"validUntil": None}):
            with self.subTest(change=change):
                self.seed(**change)
                self.assertFalse(self.call()["succeeded"])

    def test_client_cannot_supply_state_or_dates(self):
        self.seed(False)
        for param in ({"isAlive": True}, {"validUntil": 1000}, {"_warCampaigns": {}}, {"campaignId": "other"}):
            self.assertFalse(self.call(param)["succeeded"])
        self.assertIs(self.call()["isAlive"], False)

    def test_retries_concurrency_and_failures_never_write(self):
        self.seed()
        before = copy.deepcopy(self.states.load(self.player_id))
        self.service.save_state = Mock(side_effect=AssertionError("read tried to save"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call(), range(24)))
        self.assertTrue(all(row["isAlive"] for row in results))
        self.call({"playerId": "other"})
        self.service.save_state.assert_not_called()
        self.assertEqual(before, self.states.load(self.player_id))

    def test_default_registry_is_not_mounted(self):
        registry = self.service.register(Registry()).register_contract_defaults()
        for api in ("strategy/isAlive", "siege/getPairings", "strategy/getStrategyWinLossRecords"):
            self.assertEqual(registry._handlers[api].__module__, "app.business.placeholders")


class CostTermsTest(unittest.TestCase):
    def test_mercenary_quote_uses_original_define_without_mutation(self):
        defines = json.loads((FIXTURES / "war_campaigns" / "defines.json").read_text(encoding="utf-8"))["defines"]
        before = copy.deepcopy(defines)
        self.assertEqual(mercenary_hire_cost(defines, 3), 150)
        self.assertEqual(mercenary_hire_cost(defines, 0), 0)
        for count in (-1, True, 1.5, "3", 2147483647):
            with self.assertRaises(ValueError):
                mercenary_hire_cost(defines, count)
        self.assertEqual(defines, before)

    def test_original_small_sample_preserves_declarations(self):
        table = json.loads((FIXTURES / "war_campaigns" / "strategy_command.json").read_text(encoding="utf-8"))["strategy_command"]
        self.assertEqual(command_cost_terms(table, "changeBase"), (("gold", "fixed", 1000),))
        self.assertEqual(command_cost_terms(table, "march"), (("food", "force", 1),))
        self.assertEqual(command_cost_terms(table, "returnBase"), ())

    def test_asset_and_row_errors_are_distinct(self):
        with self.assertRaisesRegex(ValueError, "stub has no assets"):
            command_cost_terms({}, "march")
        with self.assertRaisesRegex(ValueError, "unknown strategy_command row"):
            command_cost_terms({"march": {}}, "missing")
        with self.assertRaisesRegex(ValueError, "invalid strategy_command cost arrays"):
            command_cost_terms({"march": {"costTypes": ["food"], "costCalculationTypes": [], "costAmounts": []}}, "march")


class CampaignRecordQueriesTest(unittest.TestCase):
    """Rows below are synthetic protocol tests, not original match outcomes."""

    setUp = WarCampaignsTest.setUp
    reload = WarCampaignsTest.reload

    def record_call(self, api, params=None, session=None):
        status, body = self.registry.dispatch(api, params or {}, session or self.session)
        self.assertEqual(status, 200, body)
        return body

    def seed_records(self, api, rows, **changes):
        player = self.states.load(self.player_id)
        record = dict(ownerId=self.player_id, observedAt=90, validUntil=110, complete=True, rows=rows)
        record.update(changes)
        player.setdefault("_warCampaigns", {}).setdefault("queries", {})[api] = record
        self.states.save(player, self.player_id)

    @staticmethod
    def history_rows():
        return [{"openTime": 12, "decisions": {"match_01": {
            "a": {"0": {"countryId": "country01", "rate": 123}},
            "b": {"0": {"countryId": "country02", "rate": 456},
                  "1": {"countryId": "country03", "rate": 789}},
            "winner": "b", "privateSettlementId": "not-wire"}}}]

    def test_siege_numeric_hierarchy_and_no_html_derived_fields(self):
        api = "siege/getPairings"
        rows = [{"defender": {"0": "country01"}, "attacker": {"0": "country02", "1": "country03"},
                 "isMe": 1, "def0Rank": 7}]
        self.seed_records(api, rows)
        result = self.record_call(api)
        self.assertEqual(result["pairings"], {"0": {"defender": rows[0]["defender"], "attacker": rows[0]["attacker"]}})
        self.assertEqual(set(result), {"pairings", "succeeded", "now"})

    def test_history_nonempty_nested_matches_survive_relogin(self):
        api = "strategy/getStrategyWinLossRecords"
        rows = self.history_rows() + self.history_rows()
        rows[1]["openTime"] = 24
        rows[1]["decisions"]["match_01"]["winner"] = "a"
        self.seed_records(api, rows)
        self.reload()
        self.session, _ = self.service._issue_login("f-war-test")
        result = self.record_call(api)
        self.assertEqual(result["totalCount"], 2)
        self.assertEqual(result["records"]["1"]["decisions"]["match_01"]["winner"], "a")
        match = result["records"]["0"]["decisions"]["match_01"]
        self.assertEqual(match["b"]["1"]["rate"], 789)
        self.assertEqual(match["winner"], "b")
        self.assertNotIn("privateSettlementId", match)
        self.assertEqual(result["records"]["0"]["openTime"], 12)

    def test_missing_incomplete_empty_and_expired_are_distinct(self):
        for api in ("siege/getPairings", "strategy/getStrategyWinLossRecords"):
            self.assertIn("no stub response", self.record_call(api)["errorReason"])
            self.seed_records(api, [], complete=False)
            self.assertFalse(self.record_call(api)["succeeded"])
            self.seed_records(api, [])
            self.assertTrue(self.record_call(api)["succeeded"])
            self.seed_records(api, [], validUntil=100)
            self.assertFalse(self.record_call(api)["succeeded"])

    def test_partial_bad_rows_rejected_without_truncating_history(self):
        api = "strategy/getStrategyWinLossRecords"
        invalid_rows = []
        for change in ({"openTime": float("nan")}, {"decisions": {"match_02": {}}}, {"openTime": True}):
            row = self.history_rows()[0]
            row.update(change)
            invalid_rows.append(row)
        row = self.history_rows()[0]
        row["decisions"]["match_01"]["a"]["0"]["rate"] = True
        invalid_rows.append(row)
        for row in invalid_rows:
            self.seed_records(api, self.history_rows() + [row])
            self.assertFalse(self.record_call(api)["succeeded"])
        self.seed_records("siege/getPairings", [{"defender": {"0": "country01"}, "attacker": {"1": "country02"}}])
        self.assertFalse(self.record_call("siege/getPairings")["succeeded"])

    def test_record_authentication_selectors_and_owner_isolation(self):
        for api in ("siege/getPairings", "strategy/getStrategyWinLossRecords"):
            self.seed_records(api, [])
            status, body = self.registry.dispatch(api, {}, None)
            self.assertEqual(status, 200)
            self.assertIn("authentication", body["errorReason"])
            other, _ = self.service._issue_login("f-record-other")
            self.assertFalse(self.record_call(api, session=other)["succeeded"])
            for params in ({"playerId": other["playerId"]}, {"rows": []}, {"complete": True}):
                self.assertFalse(self.record_call(api, params)["succeeded"])
            self.seed_records(api, [], ownerId=other["playerId"])
            self.assertFalse(self.record_call(api)["succeeded"])

    def test_record_retry_concurrency_no_write_or_reward_and_response_isolation(self):
        api = "strategy/getStrategyWinLossRecords"
        self.seed_records(api, self.history_rows())
        before = copy.deepcopy(self.states.load(self.player_id))
        self.service.save_state = Mock(side_effect=AssertionError("query saved state"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.record_call(api), range(16)))
        results[0]["records"]["0"]["decisions"]["match_01"]["winner"] = "changed"
        self.assertEqual(results[1]["records"]["0"]["decisions"]["match_01"]["winner"], "b")
        self.service.save_state.assert_not_called()
        self.assertEqual(before, self.states.load(self.player_id))


if __name__ == "__main__":
    unittest.main()
