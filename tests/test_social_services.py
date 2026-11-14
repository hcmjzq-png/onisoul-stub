"""Isolated lifecycle tests. AtomicMemory is a contract test adapter, not a DB adapter."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import state
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.business.social_services import SocialServices
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"


class AtomicMemory(MemoryState):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.fail_commit = False

    def load(self, player_id):
        with self.lock:
            return super().load(player_id)

    def save(self, player, player_id):
        with self.lock:
            super().save(player, player_id)

    @contextmanager
    def transaction(self, ids):
        with self.lock:
            staged = {key: copy.deepcopy(self.rows.get(key, {})) for key in ids}
            yield staged
            if self.fail_commit:
                raise state.StateConflictError("injected commit conflict")
            # One publication after all validation, never two sequential saves.
            self.rows = {**self.rows, **copy.deepcopy(staged)}


class SocialServicesTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = AtomicMemory(), MemorySessions()
        self.now = 1000.0
        self.tables = {n: json.loads((FIXTURES / "social" / (n + ".json")).read_text(encoding="utf-8"))
                       for n in ("defines", "playerLevel")}
        self.reload()
        self.people = []
        for name in ("social-a", "social-b", "social-c"):
            session, _ = self.service._issue_login(name)
            result = self.service.create_player(dict(username=name, countryId="country01",
                navigatorId="navi8000101", colorIndex="color1"), session)
            self.assertTrue(result["succeeded"])
            self.people.append(session)
        self.a, self.b, self.c = self.people

    def reload(self, atomic=True):
        path = FIXTURES / "gameplay" / "tables"
        self.service = GameplayService(catalog=TableCatalog(path, path / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)
        self.social = SocialServices(self.service, atomic_players=self.states.transaction if atomic else None,
                                     clock=lambda: self.now)
        self.social.table = lambda name: self.tables[name]
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.social.register(self.registry)

    def call(self, name, actor=None, target=None, **params):
        if target is not None:
            params["friendPlayerId"] = target["playerId"]
        status, body = self.registry.dispatch("friend/" + name, params, actor)
        self.assertEqual(status, 200, body)
        return body

    def send(self):
        self.assertTrue(self.call("sendFriendOffer", self.a, self.b)["result"])

    def accept(self):
        self.send()
        self.assertTrue(self.call("feedbackFriendOffer", self.b, self.a, reply="ok")["result"])

    def test_lifecycle_lists_counts_profile_reload_and_dissolution(self):
        self.send()
        a_id, b_id = self.a["playerId"], self.b["playerId"]
        self.assertEqual(self.call("getFriends", self.a, option="send")[b_id]["status"], "send")
        self.assertEqual(self.call("getFriends", self.b, option="receive")[a_id]["status"], "receive")
        self.assertEqual(self.call("getFriends", self.a, option="ok"), {})
        self.assertEqual(self.call("updateFriendData", self.b)["count"], {"ok": 0., "send": 0., "receive": 1.})
        self.assertTrue(self.call("feedbackFriendOffer", self.b, self.a, reply="ok")["result"])
        self.reload()
        profile = self.call("getFriendProfile", self.a, self.b, forHTML=False)
        self.assertEqual(profile["status"], "ok")
        self.assertEqual(profile["username"], "social-b")
        self.assertEqual(profile["friendCount"], 1.)
        self.assertNotIn("resources", profile)
        self.assertNotIn("entity", profile)
        self.assertTrue(self.call("dissolutionFriend", self.b, self.a)["result"])
        self.reload()
        self.assertEqual(self.call("getFriends", self.a, option=""), {})
        self.assertEqual(self.call("getFriends", self.b, option=""), {})

    def test_send_accept_cancel_and_dissolve_retries_do_not_duplicate_state(self):
        self.send()
        before = copy.deepcopy(self.states.rows)
        self.now += 1
        self.assertTrue(self.call("sendFriendOffer", self.a, self.b)["result"])
        self.assertEqual(before, self.states.rows)
        self.assertTrue(self.call("cancelFriendOffer", self.a, self.b)["result"])
        self.assertTrue(self.call("cancelFriendOffer", self.a, self.b)["result"])
        self.accept()
        before = copy.deepcopy(self.states.rows)
        self.assertTrue(self.call("feedbackFriendOffer", self.b, self.a, reply="ok")["result"])
        self.assertEqual(before, self.states.rows)
        self.assertTrue(self.call("dissolutionFriend", self.a, self.b)["result"])
        self.assertTrue(self.call("dissolutionFriend", self.a, self.b)["result"])

    def test_reject_retry_is_safe_failure_without_resurrection(self):
        self.send()
        self.assertTrue(self.call("feedbackFriendOffer", self.b, self.a, reply="excuse")["result"])
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.call("feedbackFriendOffer", self.b, self.a, reply="excuse")["result"])
        self.assertEqual(before, self.states.rows)

    def test_authentication_self_unknown_and_wrong_direction_do_not_write(self):
        self.send()
        before = copy.deepcopy(self.states.rows)
        for name, actor, target, params in [
            ("sendFriendOffer", None, self.b, {}), ("sendFriendOffer", self.a, self.a, {}),
            ("sendFriendOffer", self.a, {"playerId": "missing"}, {}),
            ("feedbackFriendOffer", self.a, self.b, {"reply": "ok"}),
            ("feedbackFriendOffer", self.c, self.a, {"reply": "ok"}),
            ("feedbackFriendOffer", self.b, self.a, {"reply": "yes"}),
            ("cancelFriendOffer", self.b, self.a, {}),
            ("dissolutionFriend", self.a, self.b, {}),
            ("sendFriendOffer", self.b, self.a, {})]:
            with self.subTest(name=name, actor=actor):
                result = self.call(name, actor, target, **params)
                self.assertFalse(result["result"])
                self.assertIn("0", result["detail"])
                self.assertEqual(before, self.states.rows)

    def test_offer_and_accepted_caps_on_both_accounts_no_cost(self):
        before_resources = {p: copy.deepcopy(s["resources"]) for p, s in self.states.rows.items()}
        for side in ("send", "receive"):
            self.tables["defines"]["friendoffer_" + side + "_max"]["value"] = 0
            before = copy.deepcopy(self.states.rows)
            result = self.call("sendFriendOffer", self.a, self.b)
            self.assertEqual(result["detail"]["0"], "already reached " + side + " count")
            self.assertEqual(before, self.states.rows)
            self.tables["defines"]["friendoffer_" + side + "_max"]["value"] = 10
        self.send()
        self.tables["playerLevel"]["1"]["friend"] = 0
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.call("feedbackFriendOffer", self.b, self.a, reply="ok")["result"])
        self.assertEqual(before, self.states.rows)
        self.assertEqual(before_resources, {p: s["resources"] for p, s in self.states.rows.items()})

    def test_transaction_commit_failure_rolls_back_both_players_then_retry(self):
        for name in ("sendFriendOffer", "feedbackFriendOffer", "dissolutionFriend"):
            before = copy.deepcopy(self.states.rows)
            self.states.fail_commit = True
            actor, target = (self.b, self.a) if name == "feedbackFriendOffer" else (self.a, self.b)
            self.assertFalse(self.call(name, actor, target, reply="ok")["result"])
            self.assertEqual(before, self.states.rows)
            self.states.fail_commit = False
            self.assertTrue(self.call(name, actor, target, reply="ok")["result"])

    def test_concurrent_duplicate_send_and_accept_and_reverse_requests(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call("sendFriendOffer", self.a, self.b), range(20)))
        self.assertTrue(all(r["result"] for r in results))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call("feedbackFriendOffer", self.b, self.a, reply="ok"), range(20)))
        self.assertTrue(all(r["result"] for r in results))
        self.assertEqual(len(self.states.load(self.a["playerId"])["friends"]), 1)
        self.assertTrue(self.call("dissolutionFriend", self.a, self.b)["result"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self.call, "sendFriendOffer", self.a, self.b)
            two = pool.submit(self.call, "sendFriendOffer", self.b, self.a)
            self.assertEqual(sum(r["result"] for r in (one.result(5), two.result(5))), 1)

    def test_missing_adapter_and_expired_offer_fail_without_saving(self):
        self.reload(atomic=False)
        before = copy.deepcopy(self.states.rows)
        self.assertIn("atomic", self.call("sendFriendOffer", self.a, self.b)["detail"]["0"])
        self.assertEqual(before, self.states.rows)
        self.reload()
        self.send()
        before = copy.deepcopy(self.states.rows)
        self.now += 604800
        self.assertIn("expired", self.call("feedbackFriendOffer", self.b, self.a, reply="ok")["detail"]["0"])
        self.assertIn("errorReason", self.call("getFriends", self.a, option="send"))
        self.assertEqual(before, self.states.rows)

    def test_competing_acceptances_cannot_exceed_capacity(self):
        self.assertTrue(self.call("sendFriendOffer", self.a, self.b)["result"])
        self.assertTrue(self.call("sendFriendOffer", self.c, self.b)["result"])
        self.tables["playerLevel"]["1"]["friend"] = 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda sender: self.call(
                "feedbackFriendOffer", self.b, sender, reply="ok"), (self.a, self.c)))
        self.assertEqual(sum(result["result"] for result in results), 1)
        saved = self.states.load(self.b["playerId"])
        self.assertEqual(len(saved["friends"]), 1)
        self.assertEqual(len(saved["socialOffers"]), 1)

    def test_profile_for_nonfriend_is_read_only_and_rejects_html_and_unknown(self):
        # Normalize existing players first; PlayerServices may persist schema normalization.
        self.call("updateFriendData", self.a)
        before = copy.deepcopy(self.states.rows)
        result = self.call("getFriendProfile", self.a, self.b, forHTML=False)
        self.assertEqual(result["status"], "")
        self.assertEqual(result["selfIntroduction"]["habits"], {"0": "none", "1": "none", "2": "none"})
        for target, html in ((self.b, True), ({"playerId": "missing"}, False)):
            self.assertIn("errorReason", self.call("getFriendProfile", self.a, target, forHTML=html))
        self.assertEqual(before, self.states.rows)

    def test_broken_pair_and_missing_row_vs_missing_table(self):
        self.send()
        self.states.rows[self.b["playerId"]]["socialOffers"] = {}
        before = copy.deepcopy(self.states.rows)
        self.assertFalse(self.call("cancelFriendOffer", self.a, self.b)["result"])
        self.assertEqual(before, self.states.rows)
        self.tables["defines"].pop("friendoffer_expire_time")
        self.assertIn("no stub response", self.call("getFriends", self.a, option="")["errorReason"])
        self.social.table = SocialServices.table.__get__(self.social)
        with patch.object(self.service.catalog, "load", side_effect=MissingTableError("defines")):
            self.assertIn("stub has no assets", self.call("getFriends", self.a, option="")["errorReason"])


if __name__ == "__main__":
    unittest.main()
