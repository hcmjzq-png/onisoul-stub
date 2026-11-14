"""G-only snapshot tests; fixture scores are synthetic, never original evidence."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
from threading import Event, Lock
import unittest

from app.business.gameplay import GameplayService
from app.business.rankings_services import RankingsServices, ScoreRecord, Snapshot, SnapshotPair
from app.business.registry import Registry
from app.tables import TableCatalog
from tools.gameplay_smoke import MemoryState, MemorySessions

TABLES = Path(__file__).parent / "fixtures/gameplay/tables"
LIST = "ranking/getRankersInKokudaka"
BRIEF = "ranking/getBriefOfKokudaka"


class RankingsTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.service = self.new_service()
        self.session, _ = self.service._issue_login("rankings-isolated")
        self.service.create_player(dict(username="G", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), self.session)
        self.pid = str(self.session["playerId"])
        self.pair = SnapshotPair(Snapshot("country01", (
            ScoreRecord("other", "Other", "country01", 250),
            ScoreRecord(self.pid, "G", "country01", 100),
            ScoreRecord("third", "Third", "country01", 50))),
            Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 30),)))
        self.mount()

    def new_service(self):
        return GameplayService(catalog=TableCatalog(TABLES, TABLES / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions)

    def mount(self, provider=True):
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.rankings = RankingsServices(self.service, (lambda country: self.pair) if provider else None)
        self.rankings.register(self.registry)

    def call(self, api=LIST, **params):
        if api == LIST:
            params = {"term": "current", "startIndex": 0, "endIndex": 99, **params}
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def test_actual_scores_pagination_and_personal_rank_outside_page(self):
        result = self.call(startIndex=2, endIndex=2, playerId="other", country="country02")
        self.assertEqual(result["entries"], 3)
        self.assertEqual(result["rankers"]["0"]["playerId"], "third")
        self.assertEqual(result["myRecord"], {"rank": 2., "score": 100.})
        self.assertEqual(self.call(startIndex=10, endIndex=11)["rankers"], {})

    def test_current_last_and_brief_are_distinct(self):
        self.assertEqual(self.call(term="last")["myRecord"], {"rank": 1., "score": 30.})
        self.assertEqual(self.call(BRIEF)["brief"], {"rank": 2., "score": 100., "lastRank": 1.})

    def test_empty_is_not_missing(self):
        self.pair = SnapshotPair(Snapshot("country01", ()), Snapshot("country01", ()))
        self.assertEqual(self.call()["myRecord"], {"rank": -1.})
        self.assertEqual(self.call()["entries"], 0.)
        self.assertEqual(self.call(BRIEF)["brief"], {"rank": -1., "lastRank": -1.})
        self.pair = SnapshotPair(self.pair.current, None)
        self.assertIn("no stub response", self.call(term="last")["errorReason"])
        self.assertIn("errorReason", self.call(BRIEF))
        self.assertTrue(self.call()["succeeded"])

    def test_no_provider_fails_without_synthetic_ranking(self):
        self.mount(provider=False)
        for api in (LIST, BRIEF):
            self.assertIn("no stub response", self.call(api)["errorReason"])

    def test_authentication_and_country_scope(self):
        self.assertIn("errorReason", self.registry.dispatch(LIST, {}, None)[1])
        self.pair = SnapshotPair(Snapshot("country02", ()), None)
        self.assertIn("scope", self.call()["errorReason"])

    def test_invalid_pagination_and_period(self):
        for change in ({"term": "weekly"}, {"startIndex": -1}, {"endIndex": True},
                       {"startIndex": 2, "endIndex": 1}, {"endIndex": 100},
                       {"endIndex": float("nan")}, {"startIndex": "0"}):
            self.assertIn("errorReason", self.call(**change))

    def test_snapshot_validation_and_tie_policy(self):
        records = (ScoreRecord("b", "B", "country01", 5),
                   ScoreRecord("a", "A", "country01", 5),
                   ScoreRecord("c", "C", "country01", 1))
        rows = Snapshot("country01", records).ranked()
        self.assertEqual([r["rank"] for r in rows], [1., 1., 3.])
        self.assertEqual([r["playerId"] for r in rows], ["a", "b", "c"])
        for records2 in (records + (records[0],), list(records)):
            with self.assertRaises(ValueError):
                Snapshot("country01", records2)
        with self.assertRaises(ValueError):
            Snapshot("country02", records)
        for score in (True, -1, float("inf"), 0.5, 2**53):
            with self.assertRaises(ValueError):
                ScoreRecord("a", "A", "country01", score)

    def test_queries_retries_concurrency_and_reload_preserve_player_state(self):
        before = copy.deepcopy(self.states.load(self.pid))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call(), range(20)))
        self.assertTrue(all(r["myRecord"] == {"rank": 2., "score": 100.} for r in results))
        results[0]["rankers"]["0"]["score"] = -999
        self.assertEqual(self.call()["rankers"]["0"]["score"], 250.)
        self.service = self.new_service()
        self.mount()
        self.assertEqual(self.call(BRIEF)["brief"]["lastRank"], 1.)
        self.assertEqual(self.states.load(self.pid), before)

    def test_provider_read_once_per_query(self):
        calls = []
        self.rankings.snapshots = lambda country: calls.append(country) or self.pair
        self.call(BRIEF)
        self.assertEqual(calls, ["country01"])

    def test_response_hierarchy_survives_json_transport(self):
        # MiniJSON represents JSON numbers as doubles. These paths are consumed
        # by HTMLRankingMediator.send/createMyRankHash and makeBriefInfo.
        def wire(api, **params):
            return json.loads(json.dumps(self.call(api, **params), allow_nan=False),
                              parse_int=float, parse_float=float)

        for term, rank, score in (("current", 2., 100.), ("last", 1., 30.)):
            body = wire(LIST, term=term, startIndex=0, endIndex=0)
            self.assertEqual(set(body), {"succeeded", "now", "entries", "myRecord", "rankers"})
            self.assertIs(body["succeeded"], True)
            self.assertIsInstance(body["now"], float)
            self.assertEqual(body["myRecord"], {"rank": rank, "score": score})
            self.assertEqual(set(body["rankers"]), {"0"})
            row = body["rankers"]["0"]
            self.assertEqual(set(row), {"playerId", "username", "country", "score", "rank"})
            for key in ("rank", "score"):
                self.assertIsInstance(row[key], float)
            for key in ("playerId", "username", "country"):
                self.assertIsInstance(row[key], str)
        body = wire(BRIEF)
        self.assertEqual(set(body), {"succeeded", "now", "brief"})
        self.assertEqual(body["brief"], {"rank": 2., "score": 100., "lastRank": 1.})

    def test_scores_must_survive_client_brief_float32_to_int(self):
        # HashAccessFuncs.getInt parses to float32 before casting to Int32;
        # list scores instead use getDouble. Do not send disagreeing values.
        for score in (2**24 + 1, 2**31 - 1, 2**31, 2**53 - 1):
            with self.subTest(score=score), self.assertRaises(ValueError):
                ScoreRecord(self.pid, "G", "country01", score)
        for score in (0, 2**24, 2**24 + 2, 2**31 - 128):
            with self.subTest(score=score):
                current = Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", score),))
                self.pair = SnapshotPair(current, self.pair.last)
                listed = self.call()["myRecord"]["score"]
                brief = self.call(BRIEF)["brief"]["score"]
                client_brief = int(struct.unpack("!f", struct.pack("!f", brief))[0])
                self.assertEqual(client_brief, int(listed))
                self.assertEqual(client_brief, score)

    def test_unranked_player_is_not_ranked_zero_score(self):
        empty = Snapshot("country01", ())
        zero = Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 0),))
        self.pair = SnapshotPair(empty, zero)
        self.assertEqual(self.call(BRIEF)["brief"], {"rank": -1., "lastRank": 1.})
        self.assertEqual(self.call()["myRecord"], {"rank": -1.})
        self.assertEqual(self.call(term="last")["myRecord"], {"rank": 1., "score": 0.})
        self.pair = SnapshotPair(zero, empty)
        self.assertEqual(self.call(BRIEF)["brief"], {"rank": 1., "score": 0., "lastRank": -1.})

    def test_full_page_and_following_page_use_page_local_keys(self):
        records = tuple(ScoreRecord(f"other-{i}", f"P{i}", "country01", 100 - i)
                        for i in range(100))
        self.pair = SnapshotPair(Snapshot("country01", records + (
            ScoreRecord(self.pid, "G", "country01", 0),)), self.pair.last)
        page = self.call()
        self.assertEqual(set(page["rankers"]), {str(i) for i in range(100)})
        self.assertEqual(page["entries"], 101.)
        self.assertEqual(page["myRecord"], {"rank": 101., "score": 0.})
        next_page = self.call(startIndex=100, endIndex=100)
        self.assertEqual(set(next_page["rankers"]), {"0"})
        self.assertEqual(next_page["rankers"]["0"]["playerId"], self.pid)
        self.assertEqual(next_page["myRecord"], page["myRecord"])

    def test_inflight_queries_keep_one_pair_during_publication(self):
        other_session, _ = self.service._issue_login("rankings-second-reader")
        self.service.create_player(dict(username="Second", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), other_session)
        second = str(other_session["playerId"])
        old = SnapshotPair(
            Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 100),
                                   ScoreRecord(second, "Second", "country01", 200))),
            Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 300),
                                   ScoreRecord(second, "Second", "country01", 100))))
        new = SnapshotPair(
            Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 500),
                                   ScoreRecord(second, "Second", "country01", 100),
                                   ScoreRecord("third", "Third", "country01", 900))),
            Snapshot("country01", (ScoreRecord(self.pid, "G", "country01", 30),
                                   ScoreRecord(second, "Second", "country01", 80))))
        before = {pid: self.states.load(pid) for pid in (self.pid, second)}
        for api, params in ((BRIEF, {}), (LIST, dict(term="current", startIndex=0, endIndex=99)),
                            (LIST, dict(term="last", startIndex=0, endIndex=99))):
            with self.subTest(api=api, params=params):
                captured, release, lock = Event(), Event(), Lock()
                published = old
                calls = []

                def provider(country):
                    with lock:
                        pair = published
                        calls.append(country)
                        first = len(calls) == 1
                    if first:
                        captured.set()
                        if not release.wait(5):
                            raise AssertionError("test reader was not released")
                    return pair

                self.rankings.snapshots = provider
                with ThreadPoolExecutor(max_workers=2) as pool:
                    waiting = pool.submit(self.registry.dispatch, api, params, self.session)
                    try:
                        self.assertTrue(captured.wait(5))
                        with lock:
                            published = new
                        status_new, body_new = pool.submit(
                            self.registry.dispatch, api, params, other_session).result(timeout=5)
                    finally:
                        release.set()
                    status_old, body_old = waiting.result(timeout=5)
                self.assertEqual((status_old, status_new), (200, 200))
                self.assertEqual(calls, ["country01", "country01"])
                if api == BRIEF:
                    self.assertEqual(body_old["brief"], {"rank": 2., "score": 100., "lastRank": 1.})
                    self.assertEqual(body_new["brief"], {"rank": 3., "score": 100., "lastRank": 1.})
                else:
                    current = params["term"] == "current"
                    self.assertEqual(body_old["entries"], 2.)
                    self.assertEqual(body_new["entries"], 3. if current else 2.)
                    self.assertEqual(body_old["myRecord"], {"rank": 2. if current else 1.,
                                                           "score": 100. if current else 300.})
                    self.assertEqual(body_new["myRecord"], {"rank": 3. if current else 1.,
                                                           "score": 100. if current else 80.})
                    self.assertEqual([r["score"] for r in body_old["rankers"].values()],
                                     [200., 100.] if current else [300., 100.])
                    self.assertEqual([r["score"] for r in body_new["rankers"].values()],
                                     [900., 500., 100.] if current else [80., 30.])
        self.assertEqual({pid: self.states.load(pid) for pid in before}, before)

    def test_invalid_source_fails_both_queries_without_player_writes(self):
        before = self.states.load(self.pid)
        for invalid in (None, {}, SnapshotPair(self.pair.current, []),
                        SnapshotPair(self.pair.current, Snapshot("country02", ()))):
            self.rankings.snapshots = lambda country: invalid
            for api in (LIST, BRIEF):
                with self.subTest(source=invalid, api=api):
                    body = self.call(api)
                    self.assertIs(body["succeeded"], False)
                    self.assertIn("no stub response", body["errorReason"])

        def invalid_score_source(country):
            # Constructing from an authoritative source can fail inside the
            # request too. It must reach the client's errorReason filter.
            return SnapshotPair(Snapshot(country, (
                ScoreRecord(self.pid, "G", country, 2**24 + 1),)), self.pair.last)

        self.rankings.snapshots = invalid_score_source
        for api in (LIST, BRIEF):
            body = self.call(api)
            self.assertIs(body["succeeded"], False)
            self.assertIn("no stub response", body["errorReason"])
        self.assertEqual(self.states.load(self.pid), before)


if __name__ == "__main__":
    unittest.main()
