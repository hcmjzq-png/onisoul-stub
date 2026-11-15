"""UoW contract tests; MemoryAtomic is isolated test code, not a DB adapter."""
import copy
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
from types import SimpleNamespace
import unittest

from app.business.economy_market_services import ResourceMarket, ResourceMarketRules, MARKET_KEY
from app.business.economy_services import EconomyServices


class MemoryAtomic:
    def __init__(self):
        self.players, self.records = {}, {MARKET_KEY: None}
        self.lock, self.fail_commit = threading.RLock(), False

    @contextmanager
    def atomic(self, *, player_ids=(), shared_keys=()):
        with self.lock:
            unit = SimpleNamespace(players={p: copy.deepcopy(self.players[p]) for p in player_ids},
                records={k: copy.deepcopy(self.records[k]) for k in shared_keys})
            yield unit
            if self.fail_commit: raise RuntimeError('isolated precommit failure')
            self.players.update(copy.deepcopy(unit.players))
            self.records.update(copy.deepcopy(unit.records))

    def read(self):
        with self.lock: return copy.deepcopy(self.records[MARKET_KEY])


class MarketTest(unittest.TestCase):
    def setUp(self):
        self.db, self.now = MemoryAtomic(), 1000
        for actor in ('seller', 'buyer', 'other'):
            self.db.players[actor] = {'entity': {'playerId': actor, 'created': True, 'level': 20},
                'resources': {k: {'amount': 10000, 'maxAmount': 100000} for k in ('gold', 'food', 'wood', 'iron', 'credit')}}
        self.rules = ResourceMarketRules('1000', '0.001', '1', 20, 3, (28800, 43200, 86400),
            'SYNTHETIC rates/limits for transaction tests; NOT recovered server rules', 'direct-refuse-overflow')
        self.reload()

    def reload(self):
        self.market = ResourceMarket(atomic=self.db.atomic, read_market=self.db.read,
            rules=self.rules, clock=lambda: self.now)

    def post(self, key='post-1', **kwargs):
        params = dict(num='1000', price='100', period='28800', resource_type='food', slot_id='0')
        params.update(kwargs)
        return self.market.post('seller', params, key)

    def state(self): return copy.deepcopy((self.db.players, self.db.records))

    def test_real_listing_to_search_to_purchase_settlement_and_reload(self):
        result = self.post(); listing = result['item_sn']
        self.assertEqual(self.db.players['seller']['resources']['food']['amount'], 9000)
        self.assertEqual(self.db.players['seller']['resources']['gold']['amount'], 8992)
        # Existing Browse/Search now gets a snapshot produced by actual posting.
        reader = EconomyServices(SimpleNamespace(), self.market.snapshot)
        rows = reader._resource_query(dict(page_index='0', item_per_page='300', sortby='credit', order='ascending',
            resource_type='food', price_min='100', price_max='100', amount_min='1000', amount_max='1000'), search=True)
        self.assertEqual(rows['0']['item_sn'], listing)
        self.reload()
        self.assertEqual(self.market.selling('seller')['0']['item_sn'], listing)
        self.assertEqual(set(self.market.selling('buyer')), {'params'})
        self.market.buy('buyer', listing, 'buy-1')
        self.assertEqual(self.db.players['buyer']['resources']['credit']['amount'], 9900)
        self.assertEqual(self.db.players['seller']['resources']['credit']['amount'], 10100)
        self.assertEqual(self.db.players['buyer']['resources']['food']['amount'], 11000)
        self.assertEqual(self.market.snapshot().listings, ())
        self.assertEqual(set(self.market.selling('seller')), {'params'})

    def test_gold_escrow_includes_fee(self):
        self.post(resource_type='gold')
        self.assertEqual(self.db.players['seller']['resources']['gold']['amount'], 7992)

    def test_expired_escrow_requires_owner_collection_and_keeps_slot(self):
        listing = self.post()['item_sn']; self.now = 29800
        self.assertEqual(self.market.snapshot().listings, ())
        self.assertEqual(self.market.selling('seller')['0']['remain_time'], '0')
        before = self.state()
        with self.assertRaises(ValueError): self.market.buy('buyer', listing, 'buy')
        with self.assertRaises(ValueError): self.post('post-2')
        self.assertEqual(self.state(), before)
        self.market.off_shelf('seller', listing, 'return')
        self.assertEqual(self.db.players['seller']['resources']['food']['amount'], 10000)
        self.assertEqual(self.db.players['seller']['resources']['gold']['amount'], 8992)
        self.post('post-2')

    def test_withdraw_owner_only_before_expiry(self):
        listing = self.post()['item_sn']; before = self.state()
        with self.assertRaises(ValueError): self.market.off_shelf('buyer', listing, 'theft')
        with self.assertRaises(ValueError): self.market.buy('seller', listing, 'self')
        self.assertEqual(self.state(), before)
        self.market.off_shelf('seller', listing, 'off')
        before = self.state()
        with self.assertRaises(ValueError): self.market.off_shelf('seller', listing, 'off-again')
        with self.assertRaises(ValueError): self.market.buy('buyer', listing, 'late')
        self.assertEqual(self.state(), before)

    def test_transport_receipt_prevents_replay_after_slot_reuse(self):
        listing = self.post()['item_sn']
        self.market.off_shelf('seller', listing, 'off')
        self.post('next'); before = self.state()
        with self.assertRaisesRegex(ValueError, 'already committed'): self.post()
        with self.assertRaisesRegex(ValueError, 'different intent'): self.post(num='2')
        self.assertEqual(self.state(), before)

    def test_concurrent_buyers_or_withdraw_only_one_winner(self):
        listing = self.post()['item_sn']
        def act(i):
            try:
                if i % 3 == 0: self.market.off_shelf('seller', listing, 'off-' + str(i))
                else: self.market.buy('buyer' if i % 3 == 1 else 'other', listing, 'buy-' + str(i))
                return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=12) as pool: results = list(pool.map(act, range(60)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(sum(p['resources']['food']['amount'] for p in self.db.players.values()), 30000)
        self.assertEqual(sum(p['resources']['credit']['amount'] for p in self.db.players.values()), 30000)

    def test_concurrent_duplicate_post_charges_once(self):
        def post(_):
            try: self.post(); return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(post, range(24)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.db.players['seller']['resources']['gold']['amount'], 8992)

    def test_commit_failure_rolls_back_all_participants_escrow_and_receipts(self):
        before = self.state(); self.db.fail_commit = True
        with self.assertRaises(RuntimeError): self.post()
        self.assertEqual(self.state(), before)
        self.db.fail_commit = False; listing = self.post()['item_sn']; before = self.state()
        self.db.fail_commit = True
        with self.assertRaises(RuntimeError): self.market.buy('buyer', listing, 'buy')
        self.assertEqual(self.state(), before)
        with self.assertRaises(RuntimeError): self.market.off_shelf('seller', listing, 'off')
        self.assertEqual(self.state(), before)
        self.db.fail_commit = False
        self.market.buy('buyer', listing, 'buy')

    def test_seller_overflow_rolls_back_buyer_debit_and_delivery(self):
        listing = self.post()['item_sn']
        self.db.players['seller']['resources']['credit']['amount'] = 2147483647
        before = self.state()
        with self.assertRaises(ValueError): self.market.buy('buyer', listing, 'buy')
        self.assertEqual(self.state(), before)

    def test_buyer_funds_capacity_and_return_capacity(self):
        listing = self.post()['item_sn']
        for actor, resource, value, action in [
            ('buyer', 'credit', 99, lambda: self.market.buy('buyer', listing, 'buy')),
            ('buyer', 'food', 100000, lambda: self.market.buy('buyer', listing, 'buy')),
            ('seller', 'food', 100000, lambda: self.market.off_shelf('seller', listing, 'off'))]:
            old = self.db.players[actor]['resources'][resource]['amount']
            self.db.players[actor]['resources'][resource]['amount'] = value
            before = self.state()
            with self.assertRaises(ValueError): action()
            self.assertEqual(self.state(), before)
            self.db.players[actor]['resources'][resource]['amount'] = old

    def test_invalid_post_and_fees_roll_back(self):
        for changes in ({'num': '0'}, {'price': '-1'}, {'period': '600'}, {'slot_id': '3'},
                        {'num': True}, {'resource_type': 'credit'}, {'resource_type': {}}, {'num': '10001'}):
            before = self.state()
            with self.assertRaises(ValueError): self.post(**changes)
            self.assertEqual(self.state(), before)
        self.db.players['seller']['resources']['gold']['amount'] = 1007
        before = self.state()
        with self.assertRaises(ValueError): self.post()
        self.assertEqual(self.state(), before)

    def test_missing_context_corrupt_listing_and_level_gates(self):
        with self.assertRaisesRegex(ValueError, 'no stub response'): ResourceMarket().snapshot()
        with self.assertRaisesRegex(ValueError, 'absent'): self.market.snapshot()
        self.db.players['seller']['entity']['level'] = 19
        with self.assertRaises(ValueError): self.post()
        self.db.players['seller']['entity']['level'] = 20
        listing = self.post()['item_sn']
        self.db.records[MARKET_KEY]['listings'][listing]['price'] = -100
        before = self.state()
        with self.assertRaises(ValueError): self.market.buy('buyer', listing, 'buy')
        self.assertEqual(self.state(), before)

    def test_frozen_proceeds_and_rule_validation(self):
        listing = self.post()['item_sn']
        self.market.rules = replace(self.rules, seller_ratio='0.5')
        self.market.buy('buyer', listing, 'buy')
        self.assertEqual(self.db.players['seller']['resources']['credit']['amount'], 10100)
        for changes in ({'base_tax': 'NaN'}, {'amount_multiplier': '-1'}, {'seller_ratio': '1.1'},
                        {'periods': ()}, {'delivery': ''}, {'evidence': ''}):
            self.market.rules = replace(self.rules, **changes)
            with self.assertRaises(ValueError): self.market.config()


if __name__ == '__main__': unittest.main()
