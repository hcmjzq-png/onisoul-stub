"""E's component acceptance: original consumers, transactional scopes and issuance.

Memory tests here are NOT evidence of database durability. The separate adapter
suite runs I's implementation, including an optional isolated MySQL exercise.
"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor

from app.business.social_inbox_services import SocialInboxServices
from tests import test_social_services as _social_tests


class Research331ELifecycleTest(unittest.TestCase):
    def setUp(self):
        self.h = _social_tests.SocialServicesTest()
        self.h.setUp()
        self.inbox = SocialInboxServices(self.h.service)
        self.inbox.register(self.h.registry)

    def issue(self, key="event-001", actor=None, **changes):
        actor = actor or self.h.a
        args = dict(issuance_id=key, source={"kind": "administrator", "authority": "test-operator",
                    "reference": "isolated acceptance"}, rewards={"item11_0000101": 7},
                    created_time=self.h.now)
        args.update(changes)
        with self.h.states.transaction((actor["playerId"],)) as rows:
            return self.inbox.stage_parcel(rows[actor["playerId"]], **args)

    def resolve(self, parcel, actor=None):
        return self.h.registry.dispatch("inbox/resolveParcels",
            {"responses": {parcel: "accept"}}, actor or self.h.a)[1]

    def test_expiry_third_party_and_new_offer_commit_together(self):
        h = self.h
        h.send()
        h.now += 604800
        self.assertTrue(h.call("sendFriendOffer", h.c, h.b)["result"])
        self.assertEqual(h.call("updateFriendData", h.a)["remove"], {h.b["playerId"]: "expired"})
        self.assertEqual(h.call("getFriends", h.b, option="receive").keys(), {h.c["playerId"]})
        self.assertEqual(h.social.notifications(h.b), {"friendOffer": 1., "inboxParcel": 0.})

    def test_expiry_commit_failure_preserves_all_rows_and_notices(self):
        h = self.h
        h.send()
        h.now += 604800
        before = copy.deepcopy(h.states.rows)
        h.states.fail_commit = True
        self.assertIn("errorReason", h.call("updateFriendData", h.b))
        self.assertEqual(h.states.rows, before)
        h.states.fail_commit = False
        self.assertEqual(h.call("updateFriendData", h.b)["count"]["receive"], 0.)
        self.assertEqual(h.states.load(h.a["playerId"])["socialOffers"], {})

    def test_repeated_and_relogged_notifications_are_absolute(self):
        h = self.h
        parcel = self.issue()
        h.send()
        self.assertEqual(h.social.notifications(h.b)["friendOffer"], 1.)
        self.assertEqual(h.social.notifications(h.a)["inboxParcel"], 1.)
        h.call("feedbackFriendOffer", h.b, h.a, reply="excuse")
        first = h.call("updateFriendData", h.a)
        h.reload()
        self.assertEqual(h.call("updateFriendData", h.a)["remove"], first["remove"])
        self.assertEqual(h.social.notifications(h.b)["friendOffer"], 0.)
        self.inbox.register(h.registry)
        self.resolve(parcel)
        self.assertEqual(h.social.notifications(h.a)["inboxParcel"], 0.)
        h.reload()
        self.assertEqual(h.social.notifications(h.a)["inboxParcel"], 0.)
        self.assertEqual(h.social.notifications(None), {})

    def test_fresh_profile_allows_new_request_after_removal(self):
        h = self.h
        h.send()
        h.call("cancelFriendOffer", h.a, h.b)
        self.assertIn(h.b["playerId"], h.call("updateFriendData", h.a)["remove"])
        self.assertEqual(h.call("getFriendProfile", h.a, h.b, forHTML=False)["status"], "")
        self.assertNotIn(h.b["playerId"], h.call("updateFriendData", h.a)["remove"])
        h.send()
        self.assertEqual(h.call("updateFriendData", h.b)["remove"], {})

    def test_expiry_and_accept_race_never_make_one_sided_friends(self):
        h = self.h
        h.send()
        h.now += 604800
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(h.call, "updateFriendData", h.a),
                       pool.submit(h.call, "feedbackFriendOffer", h.b, h.a, reply="ok")]
            [f.result(5) for f in futures]
        for person in (h.a, h.b):
            row = h.states.load(person["playerId"])
            self.assertFalse(row.get("friends"))
            self.assertFalse(row.get("socialOffers"))

    def test_pair_evidence_is_not_a_blanket_visit_permission(self):
        h = self.h
        a, b = h.a["playerId"], h.b["playerId"]
        self.assertEqual(h.social.pair_status(a, b, h.states.load(a), h.states.load(b)), "")
        h.send()
        self.assertEqual(h.social.pair_status(a, b, h.states.load(a), h.states.load(b)), "send")
        h.call("feedbackFriendOffer", h.b, h.a, reply="ok")
        self.assertEqual(h.social.pair_status(a, b, h.states.load(a), h.states.load(b)), "ok")
        h.states.rows[b]["friends"] = {}
        with self.assertRaises(ValueError):
            h.social.pair_status(a, b, h.states.load(a), h.states.load(b))

    def test_issuance_retry_after_claim_never_recreates_or_replays_rewards(self):
        parcel = self.issue()
        before = copy.deepcopy(self.h.states.rows)
        self.h.now += 1
        self.assertEqual(self.issue(), parcel)
        self.assertEqual(self.h.states.rows, before)
        self.assertEqual(self.resolve(parcel)["successful"][parcel]["rewards"], {"item11_0000101": 7.})
        self.assertEqual(self.issue(), parcel)
        self.assertEqual(self.resolve(parcel)["successful"][parcel]["rewards"], {})
        listing = self.h.registry.dispatch("inbox/getParcels", {"start": 0, "end": 499}, self.h.a)[1]
        self.assertEqual(listing["totalCount"], 0.)

    def test_issuer_id_content_binding_and_failed_commit(self):
        parcel = self.issue()
        before = copy.deepcopy(self.h.states.rows)
        for changes in ({"rewards": {"item11_0000101": 8}},
                        {"source": {"kind": "administrator", "authority": "other", "reference": "change"}},
                        {"rewards": {"item11_0000801": 7}}):
            with self.assertRaises(ValueError):
                self.issue(**changes)
            self.assertEqual(self.h.states.rows, before)
        self.h.states.fail_commit = True
        with self.assertRaises(Exception):
            self.issue("event-002")
        self.assertEqual(self.h.states.rows, before)
        self.h.states.fail_commit = False
        other = self.issue(actor=self.h.b)
        self.assertNotEqual(parcel, other)
        self.assertIn(parcel, self.resolve(parcel, self.h.b)["failed"])

    def test_issuer_provenance_is_private_and_rpc_cannot_issue(self):
        parcel = self.issue()
        listing = self.h.registry.dispatch("inbox/getParcels", {"start": 0, "end": 0,
            "issuance_id": "evil", "rewards": {"item11_0000101": 999}}, self.h.a)[1]
        self.assertEqual(set(listing["parcels"][parcel]), {"createdTime", "rewards"})
        self.assertEqual(listing["totalCount"], 1.)
        self.assertIn("event-001", self.h.states.load(self.h.a["playerId"])["socialInboxIssuances"]["grants"])

    def test_missing_parcel_receipt_is_corruption_not_reissuance(self):
        parcel = self.issue()
        self.h.states.rows[self.h.a["playerId"]]["socialInbox"]["pending"].pop(parcel)
        before = copy.deepcopy(self.h.states.rows)
        with self.assertRaisesRegex(ValueError, "no parcel"):
            self.issue()
        self.assertEqual(self.h.states.rows, before)
