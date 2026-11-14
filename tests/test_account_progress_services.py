"""H APIs explicitly mounted in memory; no shared server or client touched."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.account_progress_services import AccountProgressServices
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"


class AccountProgressTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("H-account")
        self.service.create_player({"username": "H-account", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)

    def reload(self):
        tables = FIXTURES / "gameplay" / "tables"
        self.service = GameplayService(catalog=TableCatalog(tables, tables / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.h = AccountProgressServices(self.service, clock=lambda: 1000,
            revisions={"server": 11, "unity": 22, "table": 33, "root": 44})
        self.registry = self.service.register(Registry())
        self.h.register(self.registry)
        self.registry.register_contract_defaults()

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def saved(self):
        return self.states.load(self.session["playerId"])

    def entitled(self):
        player = self.saved()
        player["accountProgress"] = {"pluginExpiresAt": 2000}
        self.states.save(player, self.session["playerId"])

    def setting(self):
        return json.loads((FIXTURES / "account_progress" / "plugin-setting.json").read_text())

    def test_revisions_prelogin_and_no_invented_defaults(self):
        body = self.registry.dispatch("common/getRevisions", {"root": 999}, None)[1]
        self.assertEqual([body[k] for k in ("server", "unity", "table", "root")], [11, 22, 33, 44])
        self.assertIn("no stub response", AccountProgressServices(self.service).get_revisions({}, None)["errorReason"])
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                AccountProgressServices(self.service, revisions=dict.fromkeys(("server", "unity", "table", "root"), value))

    def test_cogid_uses_session_not_target_parameter(self):
        before = self.saved()
        result = self.call("common/getPlayerCogid", playerId="other", cogid="other")
        self.assertEqual(result["playerId"], self.session["playerId"])
        self.assertEqual(self.saved(), before)

    def test_all_account_routes_require_authentication(self):
        for api in ("common/getPlayerCogid", "plugin/getPluginData", "plugin/setPluginData",
                    "plugin/getPluginLog", "plugin/addPluginLog"):
            result = self.registry.dispatch(api, {}, None)[1]
            self.assertIn("errorReason", result)

    def test_no_entitlement_or_initial_resource_grant_on_reads(self):
        player = self.saved()
        player["resources"]["gold"]["amount"] = 0
        player["actionPoints"]["missionPoint"]["point"] = 77
        self.states.save(player, self.session["playerId"])
        before = self.saved()
        for _ in range(2):
            self.assertEqual(self.call("plugin/getPluginData")["pluginTime"], {"pluginTime": 0.0})
            self.assertEqual(self.call("plugin/getPluginLog")["logdatas"], {})
            self.reload()
        self.assertEqual(self.saved(), before)

    def test_settings_replace_retry_and_relogin(self):
        self.entitled()
        setting = self.setting()
        self.assertTrue(self.call("plugin/setPluginData", pluginSetting=setting)["succeeded"])
        before = self.saved()
        self.call("plugin/setPluginData", pluginSetting=setting)
        self.assertEqual(self.saved(), before)
        setting.clear()
        self.reload()
        self.session, _ = self.service._issue_login("H-account")
        self.assertEqual(self.call("plugin/getPluginData")["pluginData"], self.setting())

    def test_expired_or_malformed_setting_does_not_write(self):
        before = self.saved()
        self.assertIn("errorReason", self.call("plugin/setPluginData", pluginSetting={}))
        self.assertEqual(self.saved(), before)
        self.entitled()
        before = self.saved()
        for setting in (None, [], {"pluginTime": 999999}, {"politic": []},
                        {"politic": {"x": {}}}, {"politic": {"x": float("nan")}},
                        {"politic": {"x": 10**400}}, {"politic": {"x": "x"*65537}}):
            self.assertIn("errorReason", self.call("plugin/setPluginData", pluginSetting=setting))
            self.assertEqual(self.saved(), before)

    def test_log_cannot_grant_rewards_or_change_entitlement(self):
        before = self.saved()
        log = {"action": "diagnostic only", "reward": {"item11_0000301": 5000}, "time": -100}
        for _ in range(2):
            self.call("plugin/addPluginLog", logdata=log, playerId="other")
        self.reload()
        logs = self.call("plugin/getPluginLog")["logdatas"]
        self.assertEqual(set(logs), {"1", "2"})  # no request nonce: append-only diagnostic retries
        self.assertEqual(logs["1"]["time"], 1000)
        after = self.saved()
        after.pop("accountProgress")
        self.assertEqual(after, before)
        logs.clear()
        self.assertEqual(len(self.call("plugin/getPluginLog")["logdatas"]), 2)

    def test_log_invalid_batch_rolls_back(self):
        before = self.saved()
        for log in ({}, {"action": "x", "reward": {"ok": 1, "bad": -1}},
                    {"action": "x", "reward": {"bad": True}},
                    {"action": "x", "reward": {}, "pluginTime": 99999}):
            self.assertIn("errorReason", self.call("plugin/addPluginLog", logdata=log))
            self.assertEqual(self.saved(), before)

    def test_account_isolation(self):
        self.entitled()
        self.call("plugin/setPluginData", pluginSetting=self.setting())
        self.call("plugin/addPluginLog", logdata={"action": "private", "reward": {}})
        other, _ = self.service._issue_login("H-other")
        for api, key in (("plugin/getPluginData", "pluginData"), ("plugin/getPluginLog", "logdatas")):
            self.assertEqual(self.registry.dispatch(api, {"playerId": self.session["playerId"]}, other)[1][key], {})

    def test_concurrent_logs_and_retention(self):
        def append(index):
            return self.call("plugin/addPluginLog", logdata={"action": str(index), "reward": {}})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(append, range(205)))
        self.assertTrue(all(row["succeeded"] for row in results))
        logs = self.call("plugin/getPluginLog")["logdatas"]
        self.assertEqual(set(logs), {str(i) for i in range(6, 206)})

    def test_revision_conflict_does_not_commit_and_retry_succeeds(self):
        self.entitled()
        before = self.saved()
        with patch.object(self.service, "_save", side_effect=state.StateConflictError("conflict")):
            result = self.call("plugin/setPluginData", pluginSetting=self.setting())
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.call("plugin/setPluginData", pluginSetting=self.setting())["succeeded"])

    def test_not_mounted_by_default(self):
        registry = self.service.register(Registry()).register_contract_defaults()
        self.assertNotEqual(registry._handlers["plugin/getPluginData"].__module__,
                            "app.business.account_progress_services")


if __name__ == "__main__":
    unittest.main()
