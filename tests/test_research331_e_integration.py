"""Execute the exact shared-file patch in isolated modules, without editing it in."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from app import state
from app.business import periodic
from app.business.social_inbox_services import SocialInboxServices
from tests import test_social_services as social_tests

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/analysis/research-331/results/e-social"


def patched_sources():
    spec = importlib.util.spec_from_file_location("e_patch_builder", RESULT / "build_integration_patch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


class Research331EIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.h = social_tests.SocialServicesTest()
        self.h.setUp()
        texts, exact = patched_sources()
        self.assertEqual((RESULT / "integration.patch").read_text(encoding="utf-8"), exact)
        period = types.ModuleType("app.business.periodic")
        exec(compile(texts["app/business/periodic.py"], "<patched-periodic>", "exec"), period.__dict__)
        main = types.ModuleType("e_patched_main")
        with patch.dict(sys.modules, {"app.business.periodic": period}):
            exec(compile(texts["app/main.py"], "<patched-main>", "exec"), main.__dict__)
        self.period = period
        # Exercise main's actual constructor wiring; no real DB in this test.
        original = main.SocialServices

        def social(service, *, atomic_players):
            self.assertIs(service, self.h.service)
            self.assertEqual(atomic_players, self.h.states.transaction)
            created = original(service, atomic_players=atomic_players, clock=lambda: self.h.now)
            created.table = lambda name: self.h.tables[name]
            return created

        with patch.object(state, "atomic_players", self.h.states.transaction, create=True), \
                patch.object(main, "GameplayService", return_value=self.h.service), \
                patch.object(main, "SocialServices", side_effect=social):
            self.registry = main.build_registry()

    def test_periodic_retains_baseline_fields_and_reconciles_authoritative_badges(self):
        h = self.h
        self.registry.dispatch("friend/sendFriendOffer", {"friendPlayerId": h.b["playerId"]}, h.a)
        status, body = self.registry.dispatch("common/periodicInquiry", {}, h.b)
        self.assertEqual(status, 200)
        self.assertEqual(body["friendOffer"], 1.)
        self.assertEqual(body["inboxParcel"], 0.)
        self.assertEqual(body["gmMessage"], "")
        self.assertIsInstance(body["show_off"], dict)
        self.assertNotIn("unreadMail", body)
        h.now += 604800
        body = self.registry.dispatch("common/periodicInquiry", {}, h.b)[1]
        self.assertEqual(body["friendOffer"], 0.)
        self.assertEqual(h.states.load(h.a["playerId"])["socialOffers"], {})

    def test_bad_social_state_does_not_fabricate_zero_counts(self):
        self.h.states.rows[self.h.a["playerId"]]["socialOffers"] = []
        body = self.registry.dispatch("common/periodicInquiry", {}, self.h.a)[1]
        self.assertFalse(body["succeeded"])
        self.assertIn("errorReason", body)
        self.assertNotIn("friendOffer", body)
        self.assertIn("gmMessage", body)
        self.assertIn("show_off", body)

    def test_unauthed_poll_and_query_do_not_access_player_database(self):
        before = self.h.states.rows.copy()
        body = self.registry.dispatch("common/periodicInquiry", {}, None)[1]
        self.assertNotIn("friendOffer", body)
        self.assertEqual(self.registry.dispatch("friend/getFriends", {"option": ""}, None)[1],
                         {"errorReason": "authentication required"})
        self.assertEqual(self.h.states.rows, before)

    def test_authenticated_new_player_poll_does_not_interrupt_creation(self):
        session, _ = self.h.service._issue_login("not-created-yet")
        self.h.states.save({"entity": {"playerId": session["playerId"], "created": False}},
                           session["playerId"])
        before = self.h.states.load(session["playerId"])
        self.assertIs(before["entity"]["created"], False)
        status, body = self.registry.dispatch("common/periodicInquiry", {}, session)
        self.assertEqual(status, 200)
        self.assertNotIn("errorReason", body)
        self.assertNotIn("friendOffer", body)
        self.assertEqual(body["gmMessage"], "")
        self.assertEqual(self.h.states.load(session["playerId"]), before)

    def test_registry_parcel_issuance_claim_and_notification(self):
        h = self.h
        inbox = SocialInboxServices(h.service)
        with h.states.transaction((h.a["playerId"],)) as rows:
            parcel = inbox.stage_parcel(rows[h.a["playerId"]], issuance_id="integration-event",
                source={"kind": "administrator", "authority": "test", "reference": "integration"},
                rewards={"item11_0000101": 7}, created_time=h.now)
        self.assertEqual(self.registry.dispatch("common/periodicInquiry", {}, h.a)[1]["inboxParcel"], 1.)
        self.assertEqual(self.registry.dispatch("inbox/getParcels", {"start": 0, "end": 499}, h.a)
                         [1]["parcels"][parcel]["rewards"], {"item11_0000101": 7.})
        self.registry.dispatch("inbox/resolveParcels", {"responses": {parcel: "accept"}}, h.a)
        self.assertEqual(self.registry.dispatch("common/periodicInquiry", {}, h.a)[1]["inboxParcel"], 0.)
