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

    def test_typed_client_settings_reject_crashing_payloads(self):
        self.entitled()
        before = self.saved()
        bad = ({"battle": {}}, {"battle": {"DreamSpaceType": "2"}},
               {"battle": {"DreamSpaceType": True}}, {"battle": {"DreamSpaceType": 0.5}},
               {"battle": {"DreamSpaceType": "not-an-index"}},
               {"potion": {"PoliticPotion": "yes"}}, {"potion": {"QuestPoint": True}},
               {"potion": {"AllPotionID": 1}}, {"politic": {"Map0": 1}},
               {"politic": {"ManualCount0": "10"}}, {"politic": {"TradeType": False}},
               {"politic": {"HarvestCount": float("inf")}},
               {"politic": {"HarvestCount": 10**400}})
        for setting in bad:
            with self.subTest(setting=setting):
                self.assertIn("errorReason", self.call("plugin/setPluginData", pluginSetting=setting))
                self.assertEqual(self.saved(), before)

    def test_settings_accept_original_wire_types_without_executing_them(self):
        self.entitled()
        for index in ("0", "1", 0.0, 1.0):
            setting = {**self.setting(), "battle": {"DreamSpaceType": index, "Battle": False,
                       "BattleMoney": 25.0, "EventType": "quest_n_0001"},
                       "politic": {"Map0": True, "ManualBuilding0": "", "ManualProduce0": "",
                                   "ManualCount0": 0.0, "TradeType": ""}}
            before = self.saved()
            self.assertTrue(self.call("plugin/setPluginData", pluginSetting=setting)["succeeded"])
            self.assertEqual(self.call("plugin/getPluginData")["pluginData"], setting)
            self.assertEqual(self.saved()["resources"], before["resources"])
            self.assertEqual(self.saved()["actionPoints"], before["actionPoints"])

    def test_unsafe_imported_setting_is_not_returned_or_rewritten(self):
        self.entitled()
        player = self.saved()
        player["accountProgress"]["pluginSetting"] = {"battle": {}}
        self.states.save(player, self.session["playerId"])
        before = self.saved()
        result = self.call("plugin/getPluginData")
        self.assertIn("errorReason", result)
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

    def test_only_reviewed_account_subset_is_mounted(self):
        registry = self.service.register(Registry()).register_contract_defaults()
        for api in ("common/getRevisions", "plugin/setPluginData"):
            self.assertEqual(registry._handlers[api].__module__, "app.business.placeholders")
        self.assertEqual(registry.dispatch("plugin/getPluginData", {}, self.session)[1]["pluginTime"],
                         {"pluginTime": 0.0})



class AccountProgressTrophyTest(unittest.TestCase):
    setUp = AccountProgressTest.setUp
    call = AccountProgressTest.call
    saved = AccountProgressTest.saved

    def reload(self):
        AccountProgressTest.reload(self)
        original_load = self.service.catalog.load
        tables = FIXTURES / 'account_progress' / 'trophies'
        h_catalog = TableCatalog(tables, tables / 'table_list.tsv')
        self.trophy_tables = {entry.root_key: h_catalog.load(entry.root_key) for entry in h_catalog.entries}
        self.service.catalog.load = lambda name: self.trophy_tables[name] if name in self.trophy_tables else original_load(name)
        # Exercise the normal mounted whitelist, not explicit component registration.
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def level(self, level=4):
        player = self.saved()
        player['entity']['level'] = level
        self.service._apply_limits(player)
        self.states.save(player, self.session['playerId'])

    def claim(self, **extra):
        return self.call('trophy/completeTrophy', **{'access':'mypage','category':'playerLevel', **extra})

    def progress(self, **extra):
        return self.call('trophy/getTrophyProgress', **{'access':'mypage', **extra})

    def test_progress_uses_server_level_and_bare_root(self):
        before = self.saved()
        self.assertEqual(self.progress(level=99, point=999), {'playerLevel':{'level':1.0,'status':'accept','window':0.0}})
        self.assertEqual(self.saved(), before)
        self.level()
        self.assertEqual(self.progress()['playerLevel'], {'level':1.0,'status':'complete','window':1.0})

    def test_exact_original_reward_and_claim_ledger_persist_after_login(self):
        self.level()
        self.call('common/getPlayerParams')  # Initialize recovery after synthetic cap change.
        before = self.saved()
        result = self.claim(playerId='other', level=99, reward=99999)
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['rewards'], {'item11_0000101':100000.0,'item08_0102701':6.0})
        self.assertEqual(set(result) - {'succeeded','now'}, {'rewards','characters','equips','progress','toInBox'})
        self.assertEqual(result['toInBox'], {})
        self.assertEqual(result['progress']['playerLevel'], {'level':1.0,'status':'lock','window':0.0})
        self.reload()
        self.session, _ = self.service._issue_login('H-account')
        player = self.saved()
        self.assertEqual(player['resources']['gold']['amount'], before['resources']['gold']['amount']+100000)
        self.assertEqual(player['items']['item08_0102701'], 6)
        self.assertEqual(player['actionPoints'], before['actionPoints'])
        self.assertIn('playerLevel_001', player['accountProgress']['trophyClaims'])
        self.assertIn('errorReason', self.claim())
        self.assertEqual(self.saved(), player)

    def test_ineligible_cannot_claim_with_client_supplied_status(self):
        before = self.saved()
        self.assertIn('errorReason', self.claim(status='complete', level=99))
        self.assertEqual(self.saved(), before)

    def test_retries_never_advance_to_next_tier_even_after_query_or_level_up(self):
        self.level(5)
        self.assertTrue(self.claim()['succeeded'])
        self.assertEqual(self.progress()['playerLevel']['status'], 'lock')
        before = self.saved()
        for _ in range(3):
            self.assertIn('errorReason', self.claim())
            self.progress()
        self.assertEqual(self.saved(), before)
        self.level(6)
        before = self.saved()
        self.assertIn('errorReason', self.claim())
        self.assertEqual(self.saved(), before)

    def test_concurrent_first_claim_has_one_winner(self):
        self.level()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.claim(), range(24)))
        self.assertEqual(sum('errorReason' not in row for row in results), 1)
        self.assertEqual(self.saved()['items']['item08_0102701'], 6)
        self.assertEqual(len(self.saved()['accountProgress']['trophyClaims']), 1)

    def test_resource_overflow_rejects_whole_reward_then_allows_retry(self):
        self.level()
        player = self.saved()
        player['resources']['gold']['amount'] = 350001
        self.states.save(player,self.session['playerId'])
        before = self.saved()
        self.assertIn('overflow', self.claim()['errorReason'])
        self.assertEqual(self.saved(),before)
        player['resources']['gold']['amount'] = 300000
        self.states.save(player,self.session['playerId'])
        self.assertTrue(self.claim()['succeeded'])
        self.assertEqual(self.saved()['resources']['gold']['amount'],400000)

    def test_invalid_jewel_balance_does_not_partially_credit_gold(self):
        self.level()
        player = self.saved()
        player['items']['item08_0102701'] = 2147483647
        self.states.save(player,self.session['playerId'])
        before=self.saved()
        self.assertIn('errorReason',self.claim())
        self.assertEqual(self.saved(),before)

    def test_save_conflict_rolls_back_assets_and_claim_then_retry(self):
        self.level()
        before=self.saved()
        with patch.object(self.service,'_save',side_effect=state.StateConflictError('collision')):
            self.assertIn('errorReason',self.claim())
        self.assertEqual(self.saved(),before)
        self.assertTrue(self.claim()['succeeded'])

    def test_notification_ack_is_not_reward_and_is_retry_safe(self):
        api='trophy/messageWindowTrophy'
        self.assertIn('errorReason', self.call(api,access='mypage',category='playerLevel'))
        self.level()
        before=self.saved()
        for _ in range(2):
            self.assertTrue(self.call(api,access='mypage',category='playerLevel')['succeeded'])
        after=self.saved()
        self.assertEqual(after['resources'],before['resources'])
        self.assertEqual(after['items'],before['items'])
        self.assertNotIn('trophyClaims',after['accountProgress'])
        self.reload()
        self.assertEqual(self.progress()['playerLevel']['window'],0)
        self.assertTrue(self.claim()['succeeded'])

    def test_access_category_authentication_and_account_isolation(self):
        self.level()
        before=self.saved()
        for api in ('trophy/getTrophyProgress','trophy/completeTrophy','trophy/messageWindowTrophy'):
            for access in (None,'raidBoss','giganticRaidBoss','unknown'):
                self.assertIn('errorReason',self.call(api,access=access,category='playerLevel'))
            self.assertIn('errorReason',self.registry.dispatch(api,{'access':'mypage','category':'playerLevel'},None)[1])
        for category in ('totalWin','playerLevel_001',None,1):
            self.assertIn('errorReason',self.claim(category=category))
        self.assertEqual(self.saved(),before)
        other, _ = self.service._issue_login('H-trophy-other')
        self.service.create_player({'username':'other','countryId':'country01','navigatorId':'navi8000101','colorIndex':'color1'},other)
        result=self.registry.dispatch('trophy/completeTrophy',{'access':'mypage','category':'playerLevel','playerId':self.session['playerId']},other)[1]
        self.assertIn('errorReason',result)
        self.assertEqual(self.saved(),before)

    def test_missing_asset_is_distinct_from_broken_table_reference(self):
        from app.tables import MissingTableError
        self.level()
        before=self.saved()
        load=self.service.catalog.load
        def missing(name):
            if name=='reward06_trophy': raise MissingTableError('not installed')
            return load(name)
        with patch.object(self.service.catalog,'load',side_effect=missing):
            self.assertIn('stub has no assets',self.claim()['errorReason'])
        self.trophy_tables['reward06_trophy'].pop('reward06_playerLevel_001')
        self.assertIn('no stub response',self.claim()['errorReason'])
        self.assertEqual(self.saved(),before)

    def test_reward_selection_or_item_mutations_fail_atomically(self):
        import copy
        self.level()
        before=self.saved()
        original=copy.deepcopy(self.trophy_tables['reward06_trophy']['reward06_playerLevel_001'])
        for change in ({'ratio1min':50},{'count2max':7},{'group2':'A'},
                       {'itemId2':'item01_unknown'},{'count2min':-1,'count2max':-1},
                       {'itemId2':'none'}):
            self.trophy_tables['reward06_trophy']['reward06_playerLevel_001']={**original,**change}
            self.assertIn('errorReason',self.claim())
            self.assertEqual(self.saved(),before)

    def test_second_stage_is_not_advertised_or_marked_received(self):
        self.level(5)
        self.claim()
        self.assertEqual(self.progress(),{'playerLevel':{'level':1.0,'status':'lock','window':0.0}})
        self.assertIn('errorReason',self.claim())
        self.assertEqual(self.progress()['playerLevel']['level'],1.0)

    def test_malformed_ledger_cannot_grant_or_acknowledge(self):
        self.level()
        for bad in (None, [], {'trophyClaims': []}, {'levelTrophyNoticeSeen': 'false'}):
            player = self.saved()
            player['accountProgress'] = bad
            self.states.save(player, self.session['playerId'])
            before = self.saved()
            for api in ('trophy/getTrophyProgress', 'trophy/completeTrophy', 'trophy/messageWindowTrophy'):
                self.assertIn('migration required', self.call(api, access='mypage', category='playerLevel')['errorReason'])
            self.assertEqual(self.saved(), before)

    def test_two_service_instances_use_storage_cas_for_exactly_one_claim(self):
        import copy
        import threading
        self.level()
        rows = {self.session['playerId']: self.saved()}
        rows[self.session['playerId']]['_revision'] = 0
        lock, gate = threading.Lock(), threading.Barrier(2)
        def load(player_id):
            with lock:
                result = copy.deepcopy(rows[player_id])
            gate.wait(timeout=5)
            return result
        def save(player, player_id):
            with lock:
                if player.get('_revision', 0) != rows[player_id].get('_revision', 0):
                    raise state.StateConflictError('CAS conflict')
                result = copy.deepcopy(player)
                result['_revision'] = result.get('_revision', 0) + 1
                rows[player_id] = result
        services = [GameplayService(catalog=self.service.catalog,load_state=load,save_state=save,session_store=self.sessions) for _ in range(2)]
        registries = [Registry(), Registry()]
        for service, registry in zip(services,registries):
            AccountProgressServices(service).register(registry)
        def claim(registry):
            return registry.dispatch('trophy/completeTrophy',{'access':'mypage','category':'playerLevel'},self.session)[1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim,registries))
        self.assertEqual(sum('errorReason' not in result for result in results),1)
        saved = rows[self.session['playerId']]
        self.assertEqual(saved['_revision'],1)
        self.assertEqual(saved['resources']['gold']['amount'],105000)
        self.assertEqual(saved['items']['item08_0102701'],6)
        self.assertEqual(len(saved['accountProgress']['trophyClaims']),1)

    def test_original_sample_structure_is_not_a_synthetic_reward(self):
        row=self.trophy_tables['reward06_trophy']['reward06_playerLevel_001']
        self.assertEqual((row['group1'],row['group2']),('A','B'))
        self.assertEqual((row['count1min'],row['count2min']),(100000,6))
        self.assertEqual(self.trophy_tables['mypage_trophy']['playerLevel_001']['clearAmount'],4)
        self.assertEqual(self.trophy_tables['trophy_setting']['playerLevel']['maxLevel'],17)


if __name__ == "__main__":
    unittest.main()
