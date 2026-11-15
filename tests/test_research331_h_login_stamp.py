"""Isolated schedules are test policy, never historical or deployment defaults."""
import copy
import datetime as dt
import json
import re
import subprocess
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.account_progress_daily import (
    APIS, CLIENT_SHA256, AccountProgressDaily, LoginStampPlan, StampReward, wire_date,
)
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import MissingTableError, TableCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"
START = int(dt.datetime(2026, 11, 14, 16, tzinfo=dt.timezone.utc).timestamp())
GET, CLAIM = "common/getLoginStampSheet", "common/stampLoginSheet"


def synthetic_plan():
    return LoginStampPlan("test-only-20261115", "fixture-v1", CLIENT_SHA256,
        "tests/test_research331_h_login_stamp.py (synthetic schedule; not historical evidence)",
        START, START + 7 * 86400, 16 * 3600, "preserve",
        (StampReward("item11_0000101", 100, "silver"),
         StampReward("item08_0102701", 2, "gold"),
         StampReward("item11_0000301", 200, "silver")))


class LoginStampTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.now = START
        self.plan = synthetic_plan()
        self.reload()
        self.session, _ = self.service._issue_login("research331-H")
        self.service.create_player({"username": "research331-H", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)

    def reload(self):
        directory = FIXTURES / "gameplay" / "tables"
        self.service = GameplayService(catalog=TableCatalog(directory, directory / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        original_load = self.service.catalog.load
        self.jewels = json.loads((FIXTURES / "research331/h-account/item08.json").read_text())['item08']
        self.service.catalog.load = lambda name: self.jewels if name == "item08" else original_load(name)
        self.daily = AccountProgressDaily(self.service, plan=self.plan, clock=lambda: self.now)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.daily.register(self.registry)

    def call(self, api=CLAIM, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def saved(self):
        return self.states.load(self.session['playerId'])

    def test_plan_is_disabled_by_default_and_not_in_normal_registry(self):
        default = AccountProgressDaily(self.service, clock=lambda: self.now)
        before = self.saved()
        for api in APIS:
            self.assertIn('no reviewed active', default.call(api, {}, self.session)['errorReason'])
        self.assertEqual(self.saved(), before)
        normal = self.service.register(Registry()).register_contract_defaults()
        for api in APIS:
            self.assertNotEqual(normal._handlers[api], self.registry._handlers[api])

    def test_browse_is_read_only_then_real_stamp_request_creates_eligibility_and_receipt(self):
        before = self.saved()
        for _ in range(3):
            result = self.call(GET)
            self.assertEqual(result['stampCount'], 0)
            self.assertEqual(result['nextStampDate'], wire_date(START))
        self.assertEqual(self.saved(), before)
        result = self.call()
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['stampCount'], 1)
        self.assertEqual(result['nextStampDate'], wire_date(START + 86400))
        after = self.saved()
        self.assertEqual(after['resources']['gold']['amount'], before['resources']['gold']['amount'] + 100)
        self.assertEqual(after['actionPoints'], before['actionPoints'])
        self.assertEqual(set(result) - {'succeeded', 'now'},
                         {'startDate', 'endDate', 'nextStampDate', 'stampCount', 'loginSheet'})

    def test_duplicate_success_is_not_replayed_to_incremental_client(self):
        local_gold = self.saved()['resources']['gold']['amount']
        for _ in range(3):
            result = self.call()
            if result.get('succeeded'):
                row = result['loginSheet']['day' + str(int(result['stampCount']))]
                local_gold += row['amount']  # UserStatus.addLoginBounus
            else:
                self.assertNotIn('loginSheet', result)
        self.assertEqual(local_gold, self.saved()['resources']['gold']['amount'])
        self.reload()
        self.session, _ = self.service._issue_login('research331-H')
        before = self.saved()
        self.assertEqual(self.call(GET)['stampCount'], 1)
        self.assertIn('already claimed', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_boundary_uses_injected_utc_offset_and_not_host_time_or_24h_since_claim(self):
        self.now = START + 86399
        self.assertTrue(self.call()['succeeded'])
        self.now += 1
        self.assertEqual(self.daily.next_stamp_date(self.saved()), wire_date(self.now))
        self.assertEqual(self.call()['stampCount'], 2)
        self.assertEqual(self.saved()['items']['item08_0102701'], 2)
        self.assertIn('already claimed', self.call()['errorReason'])

    def test_missed_days_preserve_counter_without_backfill(self):
        self.call()
        self.now += 3 * 86400
        self.assertEqual(self.call()['stampCount'], 2)
        ledger = self.saved()['accountProgress']['loginStampV1'][self.plan.campaign_id]
        self.assertEqual(len(ledger['claims']), 2)
        self.assertEqual(self.saved()['items']['item08_0102701'], 2)

    def test_explicit_reset_policy_and_completed_sheet_never_restart(self):
        self.plan = replace(self.plan, missed_day_policy='reset')
        self.reload()
        self.call()
        self.now += 2 * 86400
        self.assertEqual(self.call()['stampCount'], 1)
        self.now += 86400
        self.assertEqual(self.call()['stampCount'], 2)
        self.now += 86400
        self.assertEqual(self.call()['stampCount'], 3)
        self.assertEqual(self.daily.next_stamp_date(self.saved()), wire_date(self.plan.ends_at))
        before = self.saved()
        self.now += 2 * 86400
        self.assertIn('completed', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_schedule_start_and_end_are_half_open_and_never_create_a_campaign(self):
        before = self.saved()
        for now in (START - 1, self.plan.ends_at, self.plan.ends_at + 1):
            self.now = now
            for api in APIS:
                self.assertIn('no reviewed active', self.call(api)['errorReason'])
            self.assertIsNone(self.daily.next_stamp_date(self.saved()))
        self.assertEqual(self.saved(), before)

    def test_auth_created_role_and_no_client_control_of_date_or_award(self):
        before = self.saved()
        for api in APIS:
            self.assertIn('errorReason', self.registry.dispatch(api, {}, None)[1])
            for params in ({'date': START}, {'playerId': 'other'}, {'stampCount': 14},
                           {'reward': 99999}, {'campaign_id': 'forged'}):
                self.assertIn('errorReason', self.call(api, **params))
        uncreated, _ = self.service._issue_login('H-uncreated')
        self.assertIn('must be created', self.registry.dispatch(CLAIM, {}, uncreated)[1]['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_accounts_have_independent_stamps_and_no_shared_receipts(self):
        self.call()
        before = self.saved()
        other, _ = self.service._issue_login('H-second')
        self.service.create_player({'username': 'H-second', 'countryId': 'country01',
            'navigatorId': 'navi8000101', 'colorIndex': 'color1'}, other)
        self.assertEqual(self.registry.dispatch(GET, {}, other)[1]['stampCount'], 0)
        self.assertTrue(self.registry.dispatch(CLAIM, {}, other)[1]['succeeded'])
        self.assertEqual(self.saved(), before)

    def test_balance_overflow_rolls_back_receipt_and_can_retry(self):
        player = self.saved()
        player['resources']['gold']['amount'] = player['resources']['gold']['maxAmount']
        self.states.save(player, self.session['playerId'])
        before = self.saved()
        self.assertIn('overflow', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)
        player['resources']['gold']['amount'] -= 100
        self.states.save(player, self.session['playerId'])
        self.assertTrue(self.call()['succeeded'])

    def test_item_overflow_is_atomic(self):
        self.call()
        self.now += 86400
        player = self.saved()
        player['items']['item08_0102701'] = 2147483647
        self.states.save(player, self.session['playerId'])
        before = self.saved()
        self.assertIn('errorReason', self.call())
        self.assertEqual(self.saved(), before)

    def test_missing_table_and_bad_reference_are_distinct_and_fail_without_writes(self):
        before = self.saved()
        with patch.object(self.service.catalog, 'load', side_effect=MissingTableError('missing')):
            self.assertIn('stub has no assets', self.call()['errorReason'])
        self.jewels.clear()
        self.assertIn('no stub response', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_changed_schedule_and_overlapping_campaign_require_migration(self):
        self.call()
        before = self.saved()
        for change in ({'revision': 'v2'}, {'boundary_utc_seconds': 0},
                       {'missed_day_policy': 'reset'}, {'campaign_id': 'new-overlap'}):
            self.daily.plan = replace(self.plan, **change)
            for api in APIS:
                self.assertIn('migration required', self.call(api)['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_nonoverlapping_next_campaign_keeps_old_receipt(self):
        self.call()
        self.plan = replace(self.plan, campaign_id='test-next', starts_at=self.plan.ends_at,
                            ends_at=self.plan.ends_at + 7 * 86400)
        self.now = self.plan.starts_at
        self.reload()
        self.assertEqual(self.call()['stampCount'], 1)
        self.assertEqual(len(self.saved()['accountProgress']['loginStampV1']), 2)

    def test_corrupt_or_future_ledger_is_rejected_without_overwrite(self):
        self.call()
        valid = self.saved()
        for bad in (None, [], {'loginStampV1': []}, {'loginStampV1': {'x': {}}}):
            player = copy.deepcopy(valid)
            player['accountProgress'] = bad
            self.states.save(player, self.session['playerId'])
            before = self.saved()
            self.assertIn('migration required', self.call()['errorReason'])
            self.assertEqual(self.saved(), before)
        self.states.save(valid, self.session['playerId'])
        self.now -= 1
        # Still inside campaign but before a persisted claim.
        self.now = START + 1
        player = copy.deepcopy(valid)
        player['accountProgress']['loginStampV1'][self.plan.campaign_id]['claims'][0]['at'] += 2
        self.states.save(player, self.session['playerId'])
        self.assertIn('migration required', self.call()['errorReason'])

    def test_save_failure_or_cas_conflict_does_not_half_write(self):
        before = self.saved()
        with patch.object(self.service, '_save', side_effect=state.StateConflictError('race')):
            self.assertIn('retry', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)
        with patch.object(self.service, '_save', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.daily.call(CLAIM, {}, self.session)
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.call()['succeeded'])

    def test_parallel_requests_only_one_successful_delta(self):
        before = self.saved()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call(), range(24)))
        self.assertEqual(sum(r.get('succeeded', False) for r in results), 1)
        self.assertEqual(self.saved()['resources']['gold']['amount'], before['resources']['gold']['amount'] + 100)

    def test_two_services_use_persistence_cas_and_retry_does_not_reaward(self):
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
                result['_revision'] += 1
                rows[player_id] = result
        registries = []
        for _ in range(2):
            service = GameplayService(catalog=self.service.catalog, load_state=load,
                save_state=save, session_store=self.sessions)
            registry = Registry()
            AccountProgressDaily(service, plan=self.plan, clock=lambda: self.now).register(registry)
            registries.append(registry)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda reg: reg.dispatch(CLAIM, {}, self.session)[1], registries))
        self.assertEqual(sum(row.get('succeeded', False) for row in results), 1)
        self.assertEqual(rows[self.session['playerId']]['_revision'], 1)
        self.states.rows = rows
        self.reload()
        self.assertIn('already claimed', self.call()['errorReason'])

    def test_required_plan_fields_and_unsupported_reward_do_not_open_free_rewards(self):
        for changes in ({'evidence_ref': ''}, {'client_sha256': 'wrong'}, {'missed_day_policy': ''},
                        {'rewards': ()}, {'ends_at': START}, {'boundary_utc_seconds': -1}):
            with self.assertRaises(ValueError):
                replace(self.plan, **changes)
        self.daily.plan = replace(self.plan, rewards=(StampReward('item01_unknown', 1, 'gold'),))
        before = self.saved()
        self.assertIn('unsupported', self.call()['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_integration_patch_drives_original_login_trigger_and_relogin(self):
        # Apply the delivered unified diff in memory, never editing a shared file.
        root = Path(__file__).resolve().parents[1]
        source = subprocess.check_output(['git', 'show',
            '8023c3fee8e525040d101fee8bf843b48b3256d3:app/business/gameplay.py'], cwd=root).decode().splitlines(True)
        lines = (root / 'docs/analysis/research-331/results/h-account/integration.patch').read_text().splitlines(True)
        output, cursor = [], 0
        for line in lines[2:]:
            if line == '\n':  # git apply accepts unprefixed empty context lines.
                line = ' \n'
            if line.startswith('@@'):
                start = int(re.match(r'@@ -(\d+)', line).group(1)) - 1
                output.extend(source[cursor:start])
                cursor = start
            elif line.startswith((' ', '-')):
                self.assertEqual(source[cursor], line[1:])
                if line[0] == ' ':
                    output.append(line[1:])
                cursor += 1
            elif line.startswith('+'):
                output.append(line[1:])
        output.extend(source[cursor:])
        module = types.ModuleType('h_integration_gameplay')
        exec(compile(''.join(output), 'integration.patch/gameplay.py', 'exec'), module.__dict__)
        def service(plan):
            return module.GameplayService(catalog=self.service.catalog, load_state=self.states.load,
                save_state=self.states.save, session_store=self.sessions, login_stamp_plan=plan,
                login_stamp_clock=lambda: self.now)
        installed = service(self.plan)
        registry = installed.register(Registry()).register_contract_defaults()
        before = self.saved()
        params = registry.dispatch('common/getPlayerParams', {}, self.session)[1]
        self.assertEqual(params['loginStamp']['nextStampDate'], wire_date(START))
        self.assertEqual(params['nextStampDate'], wire_date(START))
        self.assertEqual(self.saved(), before)
        self.assertTrue(registry.dispatch(CLAIM, {}, self.session)[1]['succeeded'])
        params = service(self.plan).get_player_params({}, self.session)
        self.assertEqual(params['loginStamp']['nextStampDate'], wire_date(START + 86400))
        self.now += 86400
        params = service(self.plan).get_player_params({}, self.session)
        self.assertEqual(params['loginStamp']['nextStampDate'], wire_date(self.now))
        # Default construction does not attach the two candidate handlers.
        normal = service(None).register(Registry()).register_contract_defaults()
        for api in APIS:
            self.assertEqual(normal._handlers[api].__module__, 'app.business.placeholders')


if __name__ == '__main__':
    unittest.main()
