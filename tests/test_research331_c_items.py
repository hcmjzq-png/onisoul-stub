"""Real table samples, original-request registry path, isolated player CAS."""
import copy
import itertools
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.card_growth_ninegrid import completed_lines
from app.business.card_growth_services import CardGrowthServices
from app.business.card_growth_transactions import OperationContext, request_digest
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import MissingTableError
from tests.test_card_growth_services import GrowthCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState

SAMPLES = Path(__file__).parent / "fixtures/research331/c-card-growth"
USE = "politic/support_item/useDopingItem"
REMOVE = "politic/support_item/useDopingRemoveItem"
CONTEXT = ContextVar("c_test_transport_context", default=None)


class ItemCatalog(GrowthCatalog):
    def __init__(self):
        super().__init__()
        self.item_samples = {name: json.loads((SAMPLES / (name + ".json")).read_text(
            encoding="utf-8"))[name] for name in ("potion", "characterLevel", "shop_item")}

    def load(self, name):
        if name == "characterLevel":
            return copy.deepcopy(self.item_samples[name])
        return {**super().load(name), **copy.deepcopy(self.item_samples.get(name, {}))}


class ItemTransactionsTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("research331-c")
        self.service.create_player(dict(username="C items", countryId="country01",
                                        navigatorId="navi8000101", colorIndex="color1"), self.session)
        player = self.saved()
        # Explicit isolated scenario: an existing unassigned card and saved stones.
        # These are not an implemented drop source or initial-player grants.
        player["characters"]["90"] = copy.deepcopy(player["characters"]["1"])
        player["items"].update({f"item07_004{i:04d}": 20 for i in range(1, 21)})
        player["resources"]["credit"]["amount"] = 2000
        player["missions"]["8"] = "C"
        self.save(player)
        self.original = copy.deepcopy(self.saved()["characters"]["90"])

    def reload(self):
        self.service = GameplayService(catalog=ItemCatalog(), load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        CardGrowthServices(self.service).register_mutations(self.registry, operation_context=CONTEXT.get)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def invoke(self, api, params=None, identity=None, context=None):
        params = params or {}
        if identity is not None:
            context = OperationContext(self.session["playerId"], api, identity, request_digest(api, params))
        marker = CONTEXT.set(context)
        try:
            status, response = self.registry.dispatch(api, params, self.session)
            self.assertEqual(status, 200, response)
            return response
        finally:
            CONTEXT.reset(marker)

    def use(self, identity="use-1", **changes):
        return self.invoke(USE, {"characterId": "90", "potionId": "potion0000401", "count": 1,
                                 **changes}, identity)

    def buy_bell(self):
        return self.invoke("politic/shop/buyShopItem", dict(shopItemId="shop0700013", index=0,
                                                           quantity=1, storetable="shop_item"))

    def remove(self, identity="remove-1"):
        return self.invoke(REMOVE, {"characterId": "90", "potionId": "potion0000201"}, identity)

    def test_actual_shop_use_refund_reload_loop(self):
        before = self.saved()
        bought = self.buy_bell()
        self.assertEqual(bought["resources"]["credit"]["amount"], 1850)  # credit overrides 300
        self.assertEqual(self.invoke("politic/support_item/getPotions")["potions"]["potion0000201"]["amount"], 1)
        used = self.use(potionId="potion0000416", count=5)
        for stat in ("atk", "def", "int"):
            self.assertEqual(used["character"][stat], self.original[stat] + 50)
            self.assertEqual(used["character"][stat + "Add"], 50)
        self.assertEqual(used["potion"], {"potion0000416": {"amount": 15.0}})
        self.assertEqual(self.saved()["resources"]["gold"], before["resources"]["gold"])
        result = self.remove()
        expected = {f"potion00004{i:02d}": 1.0 for i in (1, 4, 6, 9, 11, 14)}
        self.assertEqual(result["addItems"], expected)  # 50 = 40 + 10, no all-stat stone refund
        self.assertEqual(result["character"], self.original)
        self.assertEqual(result["changeItems"]["potion0000201"], {"amount": 0.0})
        for pid in expected:
            self.assertEqual(result["changeItems"][pid], {"amount": 21.0})
        committed = self.saved()
        self.reload()
        self.session, _ = self.service._issue_login("research331-c")
        self.assertEqual(self.invoke("common/getCharacters")["90"], self.original)
        self.assertIn("already committed", self.remove()["errorReason"])
        self.assertEqual(self.saved(), committed)

    def test_identical_intents_retry_and_lost_response_after_later_changes(self):
        self.assertTrue(self.use()["succeeded"])
        first = self.saved()
        self.assertIn("already committed", self.use()["errorReason"])
        self.assertEqual(self.saved(), first)
        self.assertTrue(self.use(identity="use-2")["succeeded"])
        self.reload()
        current = self.saved()
        # An old receipt must neither spend again nor return an old character snapshot.
        repeat = self.use()
        self.assertIn("errorReason", repeat)
        self.assertNotIn("character", repeat)
        self.assertEqual(self.saved(), current)
        self.assertEqual(current["characters"]["90"]["atkAdd"], 20)

    def test_context_required_and_bound_to_account_api_body(self):
        params = {"characterId": "90", "potionId": "potion0000401", "count": 1}
        before = self.saved()
        good = OperationContext(self.session["playerId"], USE, "context", request_digest(USE, params))
        for context in (None, OperationContext("other", USE, "context", good.body_digest),
                        OperationContext(good.player_id, REMOVE, "context", good.body_digest),
                        OperationContext(good.player_id, USE, "context", "wrong")):
            self.assertIn("errorReason", self.invoke(USE, params, context=context))
            self.assertEqual(self.saved(), before)
        self.assertTrue(self.invoke(USE, params, context=good)["succeeded"])
        self.assertIn("already used", self.use(identity="context", count=5)["errorReason"])

    def test_context_identity_cannot_cross_apis_and_legacy_tactic_receipts_still_block(self):
        self.use(identity="cross")
        p = self.saved(); p["tactics"] = {"card1_00001_01": {"amount": 10}}; self.save(p)
        params = {"tactics": {"card1_00001_01": 2}}
        self.assertIn("already used", self.invoke("deck/sellTactics", params, "cross")["errorReason"])
        self.assertEqual(self.saved(), p)
        old = CardGrowthServices(self.service).sell_tactics_with_receipt(params, self.session, operation_id="legacy")
        self.assertTrue(old["succeeded"])
        before = self.saved()
        self.assertIn("already committed", self.invoke("deck/sellTactics", params, "legacy")["errorReason"])
        self.assertEqual(self.saved(), before)
        result = self.invoke("deck/sellTactics", params, "new-sale")
        self.assertEqual(result["sellPrice"], 20)
        self.assertEqual(self.saved()["tactics"]["card1_00001_01"]["amount"], 6)

    def test_insufficient_items_and_unknown_batch_do_not_reserve_identity(self):
        for changes in ({"count": 0}, {"count": True}, {"count": 2}, {"count": 11},
                        {"count": 1.5}, {"potionId": "potion0000701"}, {"characterId": 999},
                        {"operation_id": "untrusted"}, {"potionId": []}):
            before = self.saved()
            self.assertIn("errorReason", self.use(**changes))
            self.assertEqual(self.saved(), before)
        player = self.saved(); player["items"]["item07_0040001"] = 0; self.save(player)
        before = self.saved()
        self.assertIn("insufficient", self.use()["errorReason"])
        self.assertEqual(self.saved(), before)
        player["items"]["item07_0040001"] = 1; self.save(player)
        self.assertTrue(self.use()["succeeded"])

    def test_cap_equal_allowed_excess_and_mixed_stats_reject_entire_batch(self):
        player = self.saved(); player["characters"]["90"]["atk"] = 3530; self.save(player)
        self.assertEqual(self.use()["character"]["atk"], 3540)
        before = self.saved()
        self.assertIn("over-cap", self.use(identity="excess")["errorReason"])
        self.assertIn("over-cap", self.use(identity="mixed", potionId="potion0000416")["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_protected_all_deck_kinds_avatar_and_store_are_preserved(self):
        baseline = self.saved()
        cases = []
        p = copy.deepcopy(baseline); p["protectedCards"] = {"characters": ["90"]}; cases.append(p)
        p = copy.deepcopy(baseline); p["decks"]["avatar"]["id"] = 90; cases.append(p)
        for kind in ("attack", "defense", "politic", "quest", "strategy", "siege"):
            p = copy.deepcopy(baseline); p["decks"][kind]["0"]["ids"]["0"] = 90; cases.append(p)
        p = copy.deepcopy(baseline); p["storedCharacters"] = {"90": p["characters"].pop("90")}; cases.append(p)
        p = copy.deepcopy(baseline); p["storedCharacters"] = {"90": p["characters"]["90"]}; cases.append(p)
        for p in cases:
            self.save(p)
            self.assertIn("errorReason", self.use())
            self.assertIn("errorReason", self.remove())
            self.assertEqual(self.saved(), p)

    def test_removal_zero_remainder_overflow_and_missing_bell_are_atomic(self):
        self.assertIn("insufficient", self.remove()["errorReason"])
        self.buy_bell()
        before = self.saved()
        self.assertIn("no removable", self.remove()["errorReason"])
        self.assertEqual(self.saved(), before)
        p = self.saved(); p["characters"]["90"]["atkAdd"] = 11; p["characters"]["90"]["atk"] += 11; self.save(p)
        self.assertIn("nonrepresentable", self.remove()["errorReason"])
        self.assertEqual(self.saved(), p)
        p["characters"]["90"]["atkAdd"] = 10; p["characters"]["90"]["atk"] -= 1
        p["items"]["item07_0040001"] = 2147483647; self.save(p)
        self.assertIn("out of range", self.remove()["errorReason"])
        self.assertEqual(self.saved(), p)

    def test_removal_conserves_each_exact_total_using_original_denominations(self):
        baseline = self.saved()
        for value in (10, 20, 30, 40, 50, 90, 100, 180, 990):
            p = copy.deepcopy(baseline)
            p["items"]["item07_0020001"] = 1
            for stat in ("atk", "def", "int"):
                p["characters"]["90"][stat] += value
                p["characters"]["90"][stat + "Add"] = value
            self.save(p)
            result = self.remove()
            self.assertEqual(result["character"], self.original)
            rows = self.service.catalog.load("potion")
            for stat in ("atk", "def", "int"):
                total = sum(amount * rows[pid]["effects"][0] for pid, amount
                            in result["addItems"].items() if rows[pid]["uses"] == [stat])
                self.assertEqual(total, value)

    def test_missing_currency_cannot_produce_bell_and_identity_survives_ledger_capacity(self):
        p = self.saved(); p["resources"]["credit"]["amount"] = 149; self.save(p)
        self.assertIn("errorReason", self.buy_bell())
        self.assertEqual(self.saved(), p)
        self.use()
        p = self.saved(); p["cardGrowthOperations"].update({f"old-{i}": {} for i in range(1023)}); self.save(p)
        self.assertIn("archive required", self.use(identity="new")["errorReason"])
        self.assertIn("already committed", self.use()["errorReason"])
        self.assertEqual(self.saved(), p)

    def test_missing_assets_bad_references_and_bad_ledger_are_distinct(self):
        before = self.saved(); original = self.service.catalog.load
        def broken(name):
            if name == "potion":
                raise MissingTableError("potion")
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=broken):
            self.assertIn("stub has no assets", self.use()["errorReason"])
        self.service.catalog.item_samples["characterLevel"] = {}
        self.assertIn("no stub response", self.use()["errorReason"])
        self.assertEqual(self.saved(), before)
        for value in ([], None, "bad"):
            p = copy.deepcopy(before); p["cardGrowthOperations"] = value; self.save(p)
            self.assertIn("invalid", self.use()["errorReason"])
            self.assertEqual(self.saved(), p)

    def test_concurrent_same_intent_single_commit(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.use(), range(8)))
        self.assertEqual(sum("errorReason" not in r for r in results), 1)
        self.assertEqual(self.saved()["items"]["item07_0040001"], 19)
        self.assertEqual(len(self.saved()["cardGrowthOperations"]), 1)

    def test_two_services_cas_conflict_and_retry_after_commit(self):
        baseline = self.saved(); barrier = threading.Barrier(2); lock = threading.Lock()
        def load(pid):
            p = self.states.load(pid); barrier.wait(timeout=5); return p
        def save(p, pid):
            with lock:
                old = self.states.load(pid)
                if p.get("_revision", 0) != old.get("_revision", 0):
                    raise state.StateConflictError("conflict")
                self.states.save({**p, "_revision": old.get("_revision", 0) + 1}, pid)
        services = [GameplayService(catalog=ItemCatalog(), load_state=load, save_state=save,
                                    session_store=self.sessions) for _ in range(2)]
        params = dict(characterId="90", potionId="potion0000401", count=1)
        context = OperationContext(self.session["playerId"], USE, "shared", request_digest(USE, params))
        def run(service):
            return CardGrowthServices(service).mutate(USE, lambda: context, params, self.session)
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(run, services))
        self.assertEqual(sum("errorReason" not in r for r in result), 1)
        after = self.saved()
        self.assertEqual(after["items"]["item07_0040001"], baseline["items"]["item07_0040001"] - 1)
        services[0].load_state = self.states.load
        self.assertIn("already committed", run(services[0])["errorReason"])
        self.assertEqual(self.saved(), after)

    def test_save_failure_rolls_back_and_allows_retry(self):
        before = self.saved()
        with patch.object(self.service, "save_state", side_effect=state.StateConflictError("conflict")):
            self.assertIn("errorReason", self.use())
        self.assertEqual(self.saved(), before)
        with patch.object(self.service, "save_state", side_effect=RuntimeError("disk")):
            params = dict(characterId="90", potionId="potion0000401", count=1)
            ctx = OperationContext(self.session["playerId"], USE, "failure", request_digest(USE, params))
            with self.assertRaises(RuntimeError):
                CardGrowthServices(self.service).mutate(USE, lambda: ctx, params, self.session)
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.use()["succeeded"])

    def test_default_registration_remains_closed(self):
        registry = self.service.register(Registry()).register_contract_defaults()
        for api in (USE, REMOVE, "deck/sellTactics", "politic/mypage/getNineGridInfo",
                    "politic/mypage/playNineGridGacha", "politic/mypage/claimReward"):
            self.assertEqual(registry._handlers[api].__module__, "app.business.placeholders")


class NineGridGeometryTest(unittest.TestCase):
    def test_all_512_boards_against_row_column_and_diagonal_geometry(self):
        for flags in itertools.product((False, True), repeat=9):
            board = [flags[i:i + 3] for i in (0, 3, 6)]
            expected = [i for i, row in enumerate(board) if all(row)]
            expected += [i + 3 for i in range(3) if all(row[i] for row in board)]
            if all(board[i][i] for i in range(3)): expected.append(6)
            if all(board[i][2 - i] for i in range(3)): expected.append(7)
            self.assertEqual(completed_lines(flags), tuple(expected))

    def test_inventory_or_truthy_strings_cannot_supply_flags(self):
        for value in ({}, [True] * 9, ("false",) * 9, (1,) * 9, (False,) * 8):
            with self.assertRaises(ValueError): completed_lines(value)


if __name__ == "__main__":
    unittest.main()
