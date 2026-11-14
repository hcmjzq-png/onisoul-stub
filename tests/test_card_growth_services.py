"""C-group isolated registration, real small table samples and state invariants."""
import copy
import json
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
                        for name in ("character", "equip", "defines")}

    def load(self, name):
        if name == "equip":
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


if __name__ == "__main__":
    unittest.main()
