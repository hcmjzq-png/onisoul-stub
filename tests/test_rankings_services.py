"""G-only snapshot tests; fixture scores are synthetic, never original evidence."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
