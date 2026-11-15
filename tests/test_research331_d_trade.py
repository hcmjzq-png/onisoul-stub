"""Real table subset; synthetic planner is NOT an original probability model."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.economy_trade_services import (DeparturePlan, EconomyTradeServices,
    TradeMember, STATE_KEY, PURPLE, JEWEL, assert_errantry_unlocked)
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.state import StateConflictError
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / 'fixtures'


class ErrantryTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.tables = json.loads((FIXTURES / 'research331/d-economy/trade_tables.json').read_text(encoding='utf-8'))
        self.now, self.intelligence, self.result = 1000, 1000, 'result_0011'
        self.planner_calls = 0
        self.reload()
        self.session, _ = self.service._issue_login('d-trade')
        self.service.create_player(dict(username='trade', countryId='country01', navigatorId='navi8000101', colorIndex='color1'), self.session)
        player = self.saved()
        card = next(iter(player['characters']))
        player['decks'] = {'politic': {'0': {'ids': {'0': float(card)}, 'tactics': {}, 'equip': {}}}}
        player['buildings']['1'] = dict(buildingTypeId='building200_000_01_01_1_1', deployedMapKey='map001', status='waiting')
        player['resources']['gold']['amount'] = 5000
        player['actionPoints']['politicPoint']['point'] = 25
        player['souls'] = {'purple': 0}  # Explicit isolated test balance.
        self.states.save(player, self.session['playerId'])

    def planner(self, player, rule):
        self.planner_calls += 1
        return DeparturePlan(tuple(TradeMember(s, k, self.intelligence, self.result)
            for s, k in EconomyTradeServices.deck(player).items()), self.intelligence, 'SYNTHETIC TEST SELECTOR; never production')

    def deck_provider(self, player):
        return {'totalIntelligence': self.intelligence, 'politicDeck': {
            slot: {**{f: player['characters'][key][f] for f in ('baseId', 'grade', 'voice')},
                   'int': self.intelligence, 'intAdd': 0}
            for slot, key in EconomyTradeServices.deck(player, allow_empty=True).items()}}

    def reload(self):
        base = FIXTURES / 'gameplay/tables'
        catalog = TableCatalog(base, base / 'table_list.tsv')
        original = catalog.load
        catalog.load = lambda name: copy.deepcopy(self.tables[name]) if name in self.tables else original(name)
        self.service = GameplayService(catalog=catalog, load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.trade = EconomyTradeServices(self.service, planner=self.planner,
            deck_provider=self.deck_provider, clock=lambda: self.now)
        self.registry = Registry()
        self.trade.register(self.registry)

    def saved(self):
        return self.states.load(self.session['playerId'])

    def call(self, name, **changes):
        params = dict(mapId=0)
        if name == 'send3': params.update(buildingId='1', errantryId='errantry_00001')
        params.update(changes)
        status, body = self.registry.dispatch('politic/errantry/' + name, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def test_departure_status_reload_due_boundary_receive(self):
        before = self.saved()
        result = self.call('send3', intelligence=999999, dueTime=0, reward={PURPLE: 999999})
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['dueTime'], 1900)
        self.assertEqual(result['buildingId'], 1)
        stored = self.saved()
        self.assertEqual(stored['resources']['gold']['amount'], 3000)
        self.assertEqual(stored['actionPoints']['politicPoint']['point'], 15)
        self.assertEqual(stored['souls'], before['souls'])
        self.reload()
        self.assertEqual(self.call('getStatus3')['0']['errantry']['dueTime'], 1900)
        self.assertEqual(self.saved(), stored)
        self.now = 1899
        self.assertIn('not due', self.call('receive3')['errorReason'])
        self.assertEqual(self.saved(), stored)
        self.now = 1900
        result = self.call('receive3')
        self.assertEqual(result['results'], {'0': {'resultId': 'result_0011', 'reward': {PURPLE: 200, JEWEL: 1}}})
        self.assertEqual(self.saved()['souls']['purple'], before['souls']['purple'] + 200)
        self.assertEqual(self.saved()['items'][JEWEL], 1)
        self.assertEqual(self.saved()['counters']['errantryTimes'], 1)
        self.assertEqual(self.planner_calls, 1)
        self.assertNotIn('resources', result)
        self.assertFalse(self.call('getStatus3')['0']['errantry']['isActive'])

    def test_no_provider_or_empty_deck_never_charges(self):
        before = self.saved()
        self.trade.planner = None
        self.assertIn('no stub response', self.call('send3')['errorReason'])
        self.assertEqual(self.saved(), before)
        self.trade.planner = self.planner
        before['decks']['politic']['0']['ids'] = {}
        self.states.save(before, self.session['playerId'])
        self.assertIn('empty', self.call('send3')['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_all_validation_failures_do_not_debit_or_create_record(self):
        for change in ({'mapId': 1}, {'mapId': True}, {'buildingId': 'other'}, {'buildingId': '999'},
                       {'errantryId': 'missing'}, {'errantryId': {}}, {'mapId': -1}):
            with self.subTest(change=change):
                before = self.saved()
                self.assertIn('errorReason', self.call('send3', **change))
                self.assertEqual(self.saved(), before)
        self.intelligence = 999
        self.assertIn('intelligence', self.call('send3')['errorReason'])
        self.assertNotIn(STATE_KEY, self.saved())

    def test_building_ownership_idle_and_catalogue(self):
        baseline = self.saved()
        for key, value in [('deployedMapKey', 'none'), ('status', 'building'), ('buildingTypeId', 'missing')]:
            player = copy.deepcopy(baseline); player['buildings']['1'][key] = value
            self.states.save(player, self.session['playerId'])
            self.assertIn('errorReason', self.call('send3'))
            self.assertEqual(self.saved(), player)
        self.states.save(baseline, self.session['playerId'])
        self.tables['building_errantry']['building200_000_01_01_1_1']['map0'] = 'errantry1hokuyou'
        self.assertIn('regional', self.call('send3')['errorReason'])
        self.assertEqual(self.saved(), baseline)

    def test_missing_table_vs_missing_reference(self):
        original = self.service.catalog.load
        def missing(name):
            if name == 'errantry_result_0001': raise MissingTableError('test')
            return original(name)
        before = self.saved()
        with patch.object(self.service.catalog, 'load', side_effect=missing):
            self.assertIn('stub has no assets', self.call('send3')['errorReason'])
        self.result = 'missing'
        body = self.call('send3')
        self.assertIn('no stub response', body['errorReason'])
        self.assertNotIn('stub has no assets', body['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_optional_random_reward_not_silently_dropped(self):
        self.result = 'result_0015'  # reward07_0002 has an optional 0..100 entry.
        before = self.saved()
        self.assertIn('errorReason', self.call('send3'))
        self.assertEqual(self.saved(), before)

    def test_failure_result_is_not_empty_reward(self):
        self.result = 'result_0001'
        self.assertTrue(self.call('send3')['succeeded'])
        self.now = 1900
        result = self.call('receive3')
        self.assertEqual(result['results']['0']['reward'], {JEWEL: 1})

    def test_concurrent_send_and_receive_deliver_once_and_no_success_replay(self):
        for name in ('send3', 'receive3'):
            if name == 'receive3': self.now = 1900
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: self.call(name), range(24)))
            self.assertEqual(sum(r.get('succeeded') is True for r in results), 1)
        before = self.saved()
        self.reload()
        self.assertIn('subsequent journeys', self.call('send3')['errorReason'])
        self.assertIn('errorReason', self.call('receive3'))
        self.assertEqual(self.saved(), before)
        self.assertEqual(before['resources']['gold']['amount'], 3000)
        self.assertEqual(before['items'][JEWEL], 1)

    def test_save_conflict_and_exception_rollback_debit_and_grant(self):
        before = self.saved()
        with patch.object(self.service, '_save', side_effect=StateConflictError('test')):
            self.assertIn('errorReason', self.call('send3'))
        self.assertEqual(self.saved(), before)
        self.call('send3'); self.now = 1900; before = self.saved()
        with patch.object(self.service, '_save', side_effect=RuntimeError('precommit')):
            status, _ = self.registry.dispatch('politic/errantry/receive3', {'mapId': 0}, self.session)
            self.assertEqual(status, 500)
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.call('receive3')['succeeded'])

    def test_receive_overflow_keeps_claim_and_all_rewards_unspent(self):
        self.call('send3'); self.now = 1900
        player = self.saved(); player['souls']['purple'] = 60000
        self.states.save(player, self.session['playerId'])
        self.assertIn('overflow', self.call('receive3')['errorReason'])
        self.assertEqual(self.saved(), player)
        player['souls']['purple'] = 59800
        self.states.save(player, self.session['playerId'])
        self.assertTrue(self.call('receive3')['succeeded'])
        self.assertEqual(self.saved()['souls']['purple'], 60000)

    def test_frozen_outcome_not_rerolled_by_receive_or_table_reload(self):
        self.call('send3'); self.now = 1900
        self.result = 'missing'
        self.tables['reward07_errantry'].clear()
        self.assertEqual(self.call('receive3')['results']['0']['reward'][PURPLE], 200)
        self.assertEqual(self.planner_calls, 1)

    def test_integration_guard_and_corrupt_state(self):
        self.call('send3'); player = self.saved()
        with self.assertRaises(ValueError): assert_errantry_unlocked(player, building_id='1')
        with self.assertRaises(ValueError): assert_errantry_unlocked(player, politic_deck=True)
        assert_errantry_unlocked(player, building_id='2')
        player[STATE_KEY]['results']['0']['reward'][PURPLE] = -1
        self.states.save(player, self.session['playerId'])
        self.now = 1900
        self.assertIn('errorReason', self.call('receive3'))
        self.assertEqual(self.saved(), player)

    def test_protocol_registration_scope(self):
        self.assertEqual(self.registry.known(), {'politic/errantry/' + s for s in ('send3', 'receive3', 'getStatus3')})
        self.assertIn('errorReason', self.registry.dispatch('politic/errantry/send3', {}, {})[1])

    def test_status_both_original_consumers_have_typed_fields_without_creating_trip(self):
        before = self.saved()
        view = self.call('getStatus3')['0']
        self.assertFalse(view['errantry']['isActive'])
        self.assertEqual(view['totalIntelligence'], 1000)
        self.assertEqual(set(view['politicDeck']['0']), {'int', 'intAdd', 'grade', 'baseId', 'voice'})
        self.assertEqual(view['politicDeck']['0']['int'], 1000)
        self.assertEqual(self.saved(), before)
        self.trade.deck_provider = None
        self.assertIn('no stub response', self.call('getStatus3')['errorReason'])
        self.assertEqual(self.saved(), before)

    def test_bad_projection_and_disagreeing_planner_cannot_charge(self):
        before = self.saved()
        self.trade.deck_provider = lambda p: {'totalIntelligence': 1000, 'politicDeck': {}}
        self.assertIn('errorReason', self.call('getStatus3'))
        self.assertIn('errorReason', self.call('send3'))
        self.assertEqual(self.saved(), before)
        self.trade.deck_provider = self.deck_provider
        original = self.planner
        def bad(p, rule):
            plan = original(p, rule)
            return DeparturePlan(plan.members, 1001, plan.evidence)
        self.trade.planner = bad
        self.assertIn('differs', self.call('send3')['errorReason'])
        self.assertEqual(self.saved(), before)


if __name__ == '__main__': unittest.main()
