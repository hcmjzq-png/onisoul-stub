"""C-group isolated registration, real small table samples and state invariants."""
import copy
import json
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app import state
from app.business.card_growth_services import CardGrowthServices, SOUL_COLORS
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"


class GrowthCatalog(TableCatalog):
    def __init__(self):
        directory = FIXTURES / "gameplay" / "tables"
        super().__init__(directory, directory / "table_list.tsv")
        self.samples = {name: json.loads((FIXTURES / "card_growth" / (name + ".json")).read_text(encoding="utf-8"))[name]
                        for name in ("character", "equip", "defines", "tactics")}

    def load(self, name):
        if name in ("equip", "tactics"):
            return copy.deepcopy(self.samples[name])
        rows = super().load(name)
        return {**rows, **copy.deepcopy(self.samples.get(name, {}))}


class CardGrowthTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("c-card-growth")
        self.service.create_player(dict(username="C test", countryId="country01",
                                        navigatorId="navi8000101", colorIndex="color1"), self.session)
        p = self.saved()
        p["characters"]["90"] = copy.deepcopy(p["characters"]["1"])
        p["characters"]["91"] = copy.deepcopy(p["characters"]["1"])
        p["characters"]["90"]["baseId"] = "chara1_00001_01"
        p["characters"]["91"]["baseId"] = "chara1_00002_01"
        p["equips"] = {"80": {"baseId": "equip_00000_01", "grade": 1.0}}
        p["characterStore"] = {"nextOpenLimit": 3600, "lastOpenDate": 0}
        p["counters"]["characterCount"] = len(p["characters"])
        self.save(p)

    def reload(self):
        self.service = GameplayService(catalog=GrowthCatalog(), load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        CardGrowthServices(self.service).register(self.registry)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, value):
        self.states.save(value, self.session["playerId"])

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def transfer(self, into=None, out=None):
        return self.call("deck/transferStoreCharacters", toStoreIds=into or [], toCharacterIds=out or [])

    def test_sale_prices_ids_and_reload(self):
        before = self.saved()["resources"]["gold"]["amount"]
        result = self.call("deck/sellCharacters", characterIds=[90, "91"])
        self.assertEqual(result["sellPrice"], 600.0)
        self.assertEqual(result["characterIds"], {"0": 90.0, "1": 91.0})
        self.assertEqual(self.call("deck/sellEquips", equipIds=[80])["sellPrice"], 150.0)
        self.reload()
        self.assertNotIn("90", self.call("common/getCharacters"))
        self.assertEqual(self.call("common/getEquips"), {})
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], before + 750)

    def test_sale_retry_cannot_pay_twice_even_after_login(self):
        self.call("deck/sellCharacters", characterIds=[90])
        self.session, _ = self.service._issue_login("c-card-growth")
        before = self.saved()
        self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[90]))
        self.assertEqual(self.saved(), before)

    def test_invalid_batch_has_no_partial_sale(self):
        before = self.saved()
        for ids in ([90, 999], [90, "090"], [True], [90.5], [], "90", [90] * 9):
            self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=ids))
            self.assertEqual(self.saved(), before)

    def test_avatar_all_deck_kinds_and_protection_block_sale(self):
        for kind in ("attack", "defense", "politic", "quest", "strategy", "siege"):
            p = self.saved(); p["decks"][kind]["0"]["ids"]["0"] = 90.0; self.save(p)
            before = self.saved()
            self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[90]))
            self.assertEqual(self.saved(), before)
            p["decks"][kind]["0"]["ids"].pop("0"); self.save(p)
        self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[self.saved()["decks"]["avatar"]["id"]]))
        self.call("deck/setCharacterProtect", characterIds=[90], enable=True)
        self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[90]))
        self.call("deck/setEquipProtect", equipIds=[80], enable=True)
        self.assertIn("errorReason", self.call("deck/sellEquips", equipIds=[80]))

    def test_equipped_card_and_gold_overflow_atomic_rejection(self):
        p = self.saved(); p["decks"]["quest"]["0"]["equip"]["0"] = "80"; self.save(p)
        self.assertIn("errorReason", self.call("deck/sellEquips", equipIds=[80]))
        p["resources"]["gold"]["amount"] = p["resources"]["gold"]["maxAmount"]; self.save(p)
        before = self.saved()
        self.assertIn("overflow", self.call("deck/sellCharacters", characterIds=[90])["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_transfer_protected_card_preserves_record_and_reload(self):
        self.call("deck/setCharacterProtect", characterIds=[90], enable=True)
        original = self.saved()["characters"]["90"]
        with patch("app.business.card_growth_services.time.time", return_value=10000):
            result = self.transfer([90])
        self.assertEqual(result["characterCount"], 1.0)
        self.assertEqual(result["lastOpenDate"], 10000.0)
        self.assertEqual(result["nextOpenLimit"], 3600.0)
        self.reload()
        self.assertEqual(self.call("deck/getCharactersInStore")["90"], original)
        self.assertNotIn("90", self.call("common/getCharacters"))
        self.assertIn("90", self.call("deck/getProtectedCharacterIds").values())
        with patch("app.business.card_growth_services.time.time", return_value=13601):
            self.assertTrue(self.transfer(out=[90])["succeeded"])
        self.assertEqual(self.saved()["characters"]["90"], original)

    def test_cooldown_boundary_retry_and_atomic_swap(self):
        with patch("app.business.card_growth_services.time.time", return_value=10000):
            self.transfer([90])
            before = self.saved()
            self.assertIn("errorReason", self.transfer([90]))
            self.assertEqual(self.saved(), before)
        with patch("app.business.card_growth_services.time.time", return_value=13600):
            self.assertIn("cooling", self.transfer([91], [90])["errorReason"])
            self.assertEqual(self.saved(), before)
        with patch("app.business.card_growth_services.time.time", return_value=13601):
            self.assertTrue(self.transfer([91], [90])["succeeded"])
        self.assertEqual(set(self.saved()["storedCharacters"]), {"91"})

    def test_transfer_no_policy_paid_extension_and_bad_sources(self):
        before = self.saved()
        for into, out in (([90, 999], []), ([90], [90]), ([], [90]), ([], []), ([1], [])):
            self.assertIn("errorReason", self.transfer(into, out))
            self.assertEqual(self.saved(), before)
        for info in ({}, {"nextOpenLimit": 0}, {"nextOpenLimit": 3600, "extendSlot": 1}):
            p = self.saved(); p["characterStore"] = info; self.save(p)
            before = self.saved()
            self.assertIn("errorReason", self.transfer([90]))
            self.assertEqual(self.saved(), before)

    def test_capacity_both_directions_and_duplicate_inventory(self):
        p = self.saved()
        p["storedCharacters"] = {str(i): copy.deepcopy(p["characters"]["90"]) for i in range(1000, 1100)}
        self.save(p); before = self.saved()
        self.assertIn("capacity", self.transfer([90])["errorReason"])
        self.assertEqual(self.saved(), before)
        with patch.object(self.service, "_possession_limits", return_value={"character": {"result": 0}}):
            self.assertIn("capacity", self.transfer(out=[1000])["errorReason"])
        p["storedCharacters"]["90"] = copy.deepcopy(p["characters"]["90"]); self.save(p)
        self.assertIn("duplicate inventory", self.transfer([91])["errorReason"])
        before = self.saved()
        self.assertIn("duplicate inventory", self.call("deck/sellCharacters", characterIds=[90])["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_authentication_and_cross_account(self):
        before = self.saved()
        for api, params in (("deck/sellCharacters", {"characterIds": [90]}),
                            ("deck/transferStoreCharacters", {"toStoreIds": [90], "toCharacterIds": []}),
                            ("politic/lottery/getSouls", {})):
            self.assertIn("errorReason", self.registry.dispatch(api, params, None)[1])
        other, _ = self.service._issue_login("other-c-user")
        self.service.create_player(dict(username="other", countryId="country01", navigatorId="navi8000101", colorIndex="color1"), other)
        result = self.registry.dispatch("deck/sellCharacters", {"characterIds": [90], "playerId": self.session["playerId"]}, other)[1]
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)

    def test_concurrent_sale_or_transfer_serializes_one_winner(self):
        before_gold = self.saved()["resources"]["gold"]["amount"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("deck/sellCharacters", characterIds=[90]), range(2)))
        self.assertEqual(sum("errorReason" not in r for r in results), 1)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], before_gold + 300)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.transfer([91]), range(2)))
        self.assertEqual(sum("errorReason" not in r for r in results), 1)

    def test_revision_conflict_does_not_commit_or_report_success(self):
        before = self.saved()
        with patch.object(self.service, "save_state", side_effect=state.StateConflictError("conflict")):
            self.assertIn("errorReason", self.call("deck/sellCharacters", characterIds=[90]))
            self.assertIn("errorReason", self.transfer([90]))
        self.assertEqual(self.saved(), before)

    def test_missing_table_distinct_from_missing_row(self):
        before = self.saved()
        original = self.service.catalog.load
        def load(name):
            if name == "equip":
                raise MissingTableError("equip")
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=load):
            self.assertIn("stub has no assets", self.call("deck/sellEquips", equipIds=[80])["errorReason"])
        p = self.saved(); p["equips"]["80"]["baseId"] = "missing-row"; self.save(p)
        self.assertIn("no stub response", self.call("deck/sellEquips", equipIds=[80])["errorReason"])
        self.assertEqual(self.saved()["resources"], before["resources"])

    def test_souls_bare_numeric_balance_no_grants(self):
        p = self.saved(); p["souls"] = {"red": 17}; self.save(p)
        before = self.saved()
        result = self.call("politic/lottery/getSouls")
        self.assertEqual(set(result), set(SOUL_COLORS))
        self.assertEqual(result["red"], 17.0)
        self.assertTrue(all(type(v) is float for v in result.values()))
        self.assertEqual(sum(result.values()), 17.0)
        self.assertEqual(self.saved(), before)
        self.reload()
        self.assertEqual(self.call("politic/lottery/getSouls"), result)

    def seed_tactics(self):
        p = self.saved()
        p["tactics"] = {"card1_00001_01": {"amount": 10}, "card1_00002_01": {"amount": 3}}
        self.save(p)

    def tactic_sale(self, quantities=None, operation_id="sale-1", session=None):
        return CardGrowthServices(self.service).sell_tactics_with_receipt(
            {"tactics": quantities if quantities is not None else {"card1_00001_01": 2}},
            self.session if session is None else session, operation_id=operation_id)

    def test_tactic_sale_partial_batch_and_client_subtraction_roundtrip(self):
        self.seed_tactics()
        before = self.saved()
        result = self.tactic_sale({"card1_00001_01": 2, "card1_00002_01": 3})
        self.assertEqual(result["sellPrice"], 80.0)
        self.assertEqual(result["tactics"], {"card1_00001_01": 2.0, "card1_00002_01": 3.0})
        self.reload()
        self.session, _ = self.service._issue_login("c-card-growth")
        after = self.call("common/getTactics")
        for key, sold in result["tactics"].items():
            self.assertEqual(after[key]["amount"], before["tactics"][key]["amount"] - sold)
        self.assertEqual(self.call("politic/mypage/getPlayerProfile")["tacticCount"], 8.0)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], before["resources"]["gold"]["amount"] + 80)

    def test_tactic_receipt_survives_reload_replenishment_and_changed_table(self):
        self.seed_tactics()
        first = self.tactic_sale()
        p = self.saved(); p["tactics"]["card1_00001_01"]["amount"] = 100; self.save(p)
        self.reload()
        self.service.catalog.samples["tactics"]["card1_00001_01"]["sellPrice"] = 99
        before = self.saved()
        repeated = self.tactic_sale()
        self.assertEqual(repeated["sellPrice"], first["sellPrice"])
        self.assertEqual(repeated["tactics"], first["tactics"])
        self.assertEqual(self.saved(), before)
        # The same quantities are a valid second intent with a NEW trusted ID.
        self.assertEqual(self.tactic_sale(operation_id="sale-2")["sellPrice"], 198.0)
        self.assertEqual(self.saved()["tactics"]["card1_00001_01"]["amount"], 98)

    def test_tactic_receipt_id_cannot_be_reused_for_changed_quantities(self):
        self.seed_tactics(); self.tactic_sale()
        before = self.saved()
        self.assertIn("already used", self.tactic_sale({"card1_00001_01": 3})["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_tactic_invalid_batch_and_insufficient_stock_atomic(self):
        self.seed_tactics(); before = self.saved()
        for quantities in ({}, [], {"card1_00001_01": 0}, {"card1_00001_01": True},
                           {"card1_00001_01": 1.5}, {"card1_00001_01": -1},
                           {"card1_00001_01": 2, "card1_00002_01": 4},
                           {"card1_00001_01": 2, "unknown": 1}, {1: 1},
                           {str(i): 1 for i in range(9)}):
            self.assertIn("errorReason", self.tactic_sale(quantities))
            self.assertEqual(self.saved(), before)
        self.assertTrue(self.tactic_sale()["succeeded"])  # rejected attempt did not reserve ID

    def test_tactic_references_all_groups_and_gold_overflow(self):
        self.seed_tactics()
        for kind in ("attack", "defense", "politic", "quest", "strategy", "siege"):
            p = self.saved(); p["decks"][kind]["0"]["tactics"]["0"] = "card1_00001_01"; self.save(p)
            before = self.saved()
            self.assertIn("referenced", self.tactic_sale()["errorReason"])
            self.assertEqual(self.saved(), before)
            p["decks"][kind]["0"]["tactics"].pop("0"); self.save(p)
        p = self.saved(); p["resources"]["gold"]["amount"] = p["resources"]["gold"]["maxAmount"]; self.save(p)
        before = self.saved()
        self.assertIn("overflow", self.tactic_sale()["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_tactic_concurrent_same_receipt_and_distinct_intents(self):
        self.seed_tactics(); gold = self.saved()["resources"]["gold"]["amount"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.tactic_sale(), range(2)))
        self.assertTrue(all(r["succeeded"] for r in results))
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], gold + 20)
        self.assertEqual(len(self.saved()["cardGrowthTacticSales"]), 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda i: self.tactic_sale({"card1_00001_01": 5}, f"next-{i}"), range(2)))
        self.assertEqual(sum("errorReason" not in r for r in results), 1)
        self.assertEqual(self.saved()["tactics"]["card1_00001_01"]["amount"], 3)

    def test_tactic_conflict_and_save_failure_leave_no_receipt_or_spending(self):
        self.seed_tactics(); before = self.saved()
        with patch.object(self.service, "save_state", side_effect=state.StateConflictError("conflict")):
            self.assertIn("errorReason", self.tactic_sale())
        self.assertEqual(self.saved(), before)
        with patch.object(self.service, "save_state", side_effect=RuntimeError("storage unavailable")):
            with self.assertRaises(RuntimeError):
                self.tactic_sale()
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.tactic_sale()["succeeded"])

    def test_tactic_auth_account_scope_and_missing_identity(self):
        self.seed_tactics(); before = self.saved()
        for identity in (None, "", "has spaces", "x" * 129, 123, "中文"):
            self.assertIn("errorReason", self.tactic_sale(operation_id=identity))
        self.assertIn("errorReason", self.tactic_sale(session={}))
        other, _ = self.service._issue_login("other-tactic-user")
        self.service.create_player(dict(username="other", countryId="country01", navigatorId="navi8000101", colorIndex="color1"), other)
        self.assertIn("errorReason", self.tactic_sale(session=other))
        self.assertEqual(self.saved(), before)
        # Receipts are player-local; a matching ID cannot reveal another player's result.
        self.tactic_sale()
        self.assertIn("errorReason", self.tactic_sale(session=other))

    def test_tactic_missing_assets_and_missing_row_are_distinct(self):
        self.seed_tactics(); before = self.saved(); original = self.service.catalog.load
        def load(name):
            if name == "tactics":
                raise MissingTableError("tactics")
            return original(name)
        with patch.object(self.service.catalog, "load", side_effect=load):
            self.assertIn("stub has no assets", self.tactic_sale()["errorReason"])
        self.service.catalog.samples["tactics"].pop("card1_00002_01")
        self.assertIn("no stub response", self.tactic_sale({"card1_00001_01": 1, "card1_00002_01": 1})["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_tactic_ledger_limit_never_evicts_old_receipts(self):
        self.seed_tactics(); self.tactic_sale()
        p = self.saved()
        for i in range(1023):
            key = hashlib.sha256(f"historic-{i}".encode()).hexdigest()
            p["cardGrowthTacticSales"][key] = {"quantities": {}, "payload": {}}
        self.save(p); before = self.saved()
        self.assertIn("archive required", self.tactic_sale(operation_id="new-sale")["errorReason"])
        self.assertTrue(self.tactic_sale()["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_tactic_settlement_is_not_registered_as_public_handler(self):
        self.seed_tactics()
        handler = self.registry._handlers["deck/sellTactics"]
        self.assertEqual(handler.__module__, "app.business.placeholders")

    def test_tactic_two_service_instances_cas_loser_retries_from_receipt(self):
        self.seed_tactics(); before = self.saved()
        barrier, save_lock = threading.Barrier(2), threading.Lock()
        def synchronized_load(player_id):
            snapshot = self.states.load(player_id)
            barrier.wait(timeout=5)
            return snapshot
        def cas_save(player, player_id):
            with save_lock:
                current = self.states.load(player_id)
                revision = current.get("_revision", 0)
                if player.get("_revision", 0) != revision:
                    raise state.StateConflictError("competing instance committed")
                self.states.save({**player, "_revision": revision + 1}, player_id)
        instances = [GameplayService(catalog=GrowthCatalog(), load_state=synchronized_load,
                                     save_state=cas_save, session_store=self.sessions) for _ in range(2)]
        def run(service):
            return CardGrowthServices(service).sell_tactics_with_receipt(
                {"tactics": {"card1_00001_01": 2}}, self.session, operation_id="same-intent")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, instances))
        self.assertEqual(sum("errorReason" not in r for r in results), 1)
        committed = self.saved()
        self.assertEqual(committed["resources"]["gold"]["amount"], before["resources"]["gold"]["amount"] + 20)
        self.assertEqual(len(committed["cardGrowthTacticSales"]), 1)
        instances[0].load_state = self.states.load
        self.assertTrue(run(instances[0])["succeeded"])
        self.assertEqual(self.saved(), committed)


if __name__ == "__main__":
    unittest.main()
