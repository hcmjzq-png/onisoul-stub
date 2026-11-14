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
        self.assertEqual(registry._handlers["strategy/isAlive"].__module__, "app.business.placeholders")


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


if __name__ == "__main__":
    unittest.main()
