"""G integration tests: real city commands, real original table subset, no scores.

DurableTestStore is an isolated JSON transaction oracle, NOT a production DB.
All game scores come from building mutations or charged gold commands.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
import unittest

from app.business.city_services import CityServices
from app.business.gameplay import GameplayService
from app.business.rankings_aggregation import (
    RankingTransactions, building_kokudaka, city_source, client_integer,
    donate_gold, national_context_data, new_ledger, project_pair, record_city,
    seal_through,
)
from app.business.rankings_periods import METRICS, period_pair, validate_periods
from app.business.rankings_services import LedgerRankingsServices
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemorySessions, MemoryState


FIXTURES = Path(__file__).parent / "fixtures"
FIELD = "building200_041_01_01_1_1"


def plans():
    # Deliberately synthetic explicit timestamps; NOT original server calendars.
    result = {name: [{"key": f"{name}:{i}", "start": i * 100, "end": (i + 1) * 100}
                     for i in range(3)] for name in METRICS}
    result["dedication_monthly"] = [{"key": "monthly:0", "start": 0, "end": 200},
                                      {"key": "monthly:1", "start": 200, "end": 300}]
    return result


class DurableTestStore:
    def __init__(self, path, initial=None):
        self.path, self.lock, self.fail_commit = path, RLock(), False
        if initial is not None:
            path.write_text(json.dumps(initial, sort_keys=True), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def commit(self, state):
        if self.fail_commit:
            raise RuntimeError("injected durable commit failure")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def transact(self, player_id, transition):
        with self.lock:
            state = self.read()
            player, ledger, payload = transition(state["players"][player_id], state["ledger"])
            state["players"][player_id], state["ledger"] = player, ledger
            self.commit(state)
            return copy.deepcopy(payload)

    def view(self, now):
        with self.lock:
            state = self.read()
            state["ledger"] = seal_through(state["ledger"], now)
            self.commit(state)
            return state["ledger"], now


class Research331GTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.states, self.sessions = MemoryState(), MemorySessions()
        base = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        city = TableCatalog(FIXTURES / "city", FIXTURES / "city/table_list.tsv")
        raw = {name: json.loads((FIXTURES / "research331/g-rankings" / (name + ".json")).read_text(encoding="utf-8"))[name]
               for name in ("building", "defines")}
        self.catalog = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        self.catalog.load = lambda name: ({**city.load(name), **raw[name]} if name in raw else
                                          city.load(name) if name in ("draft", "building_level") else base.load(name))
        self.service = GameplayService(catalog=self.catalog, load_state=self.states.load,
                                       save_state=self.states.save, session_store=self.sessions)
        self.city = CityServices(self.service)
        self.session, _ = self.service._issue_login("g-real-events")
        self.service.create_player(dict(username="G", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), self.session)
        self.pid = str(self.session["playerId"])
        player = self.states.load(self.pid)
        player["drafts"]["draft2000041"] = 3
        player["actionPoints"]["politicPoint"]["point"] = 50
        other = copy.deepcopy(player)
        other["entity"].update(playerId="other", username="Other", country="country02")
        ledger = new_ledger(plans(), coverage_start=0, realm="isolated-test", gold_only_no_war=True)
        self.store = DurableTestStore(Path(self.tmp.name) / "state.json",
                                      {"players": {self.pid: player, "other": other}, "ledger": ledger})
        self.now = 10
        self.tx = RankingTransactions(self.store, self.catalog, lambda: self.now)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.read_calls = 0
        def read_view():
            self.read_calls += 1
            return self.store.view(self.now)
        LedgerRankingsServices(self.service, read_view).register(self.registry)

    def build(self, pid=None, op="build-1"):
        def action(player):
            building = self.service._build_from_draft(player, "draft2000041", (10, 10), completed=True)
            return {"building": building}
        return self.tx.city(pid or self.pid, action, operation_id=op)

    def donate(self, amount=1000, op="gold-1", pid=None):
        return self.tx.gold(pid or self.pid, {"category": "gold", "article": {"item11_0000101": amount}}, operation_id=op)

    def query(self, api="ranking/getRankersInKokudaka", **params):
        if "Brief" not in api:
            params = {"term": "current", "startIndex": 0, "endIndex": 99, **params}
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def test_real_build_charge_rank_upgrade_store_redeploy_and_reload(self):
        before = self.store.read()["players"][self.pid]
        built = self.build()
        self.assertEqual(built["kokudaka"], 10)
        after = self.store.read()["players"][self.pid]
        self.assertLess(after["resources"]["gold"]["amount"], before["resources"]["gold"]["amount"])
        self.assertEqual(self.query()["myRecord"], {"rank": 1., "score": 10.})
        # Use the existing city command with its actual costs, exp and level checks.
        def upgrade(player):
            player["buildings"]["1"]["exp"] = 10000  # isolated earned-exp prerequisite
            return self.city.upgrade(player, {"buildingId": 1}, mode="single")
        self.now = 20
        self.tx.city(self.pid, upgrade, operation_id="aaa-upgrade")
        self.assertEqual(self.query()["myRecord"]["score"], 13.)
        self.now = 30
        self.tx.city(self.pid, lambda p: self.city.store_buildings(p, {"buildingIds": [1]}), operation_id="store")
        self.assertEqual(self.query()["myRecord"]["score"], 0.)
        self.assertEqual(self.store.read()["players"][self.pid]["rankingDedicationLimit"], 130)
        self.now = 40
        self.tx.city(self.pid, lambda p: self.city.deploy(p, {"buildingId": 1, "originCoord": [10, 10]}), operation_id="deploy")
        reloaded = DurableTestStore(self.store.path).read()
        self.assertEqual(project_pair(reloaded["ledger"], "kokudaka", "country01", 40)[0][0]["score"], 13.)
        source = list(reloaded["ledger"]["events"].values())
        self.assertTrue(all("tableSha256" in e["source"]["buildings"]["1"] for e in source if e["source"]["buildings"]))

    def test_gold_actual_deduction_drives_three_projections_and_country_shop(self):
        self.build()
        before = self.store.read()["players"][self.pid]["resources"]["gold"]["amount"]
        body = self.donate(2000)
        self.assertEqual(body["gainPoint"], 2.)
        self.assertEqual(body["dedication"], {"point": 2., "limit": 100., "rank": 1.})
        self.assertEqual(body["myRank"], {"rank": 1., "countryRank": 1.})
        state = self.store.read()
        self.assertEqual(state["players"][self.pid]["resources"]["gold"]["amount"], before - 2000)
        for api in ("ranking/getRankersInDedication", "ranking/getMonthlyRankersInDedication"):
            self.assertEqual(self.query(api)["myRecord"]["score"], 2.)
        country = self.query("ranking/getRankersInNationalPower")
        self.assertEqual(country["rankers"], {"0": {"countryId": "country01", "score": 2., "rank": 1.}})
        self.assertEqual(national_context_data(state["ledger"], "country01", self.now), ("isolated-test:national_power:0", 2))

    def test_exact_boundary_previous_and_monthly_are_independent(self):
        self.build()
        self.donate()
        self.now = 99
        self.assertEqual(self.query("ranking/getRankersInDedication")["myRecord"]["score"], 1.)
        self.now = 100
        self.assertEqual(self.query("ranking/getRankersInDedication")["myRecord"], {"rank": -1.})
        self.donate(op="gold-next-period")
        for term in ("current", "last"):
            self.assertEqual(self.query("ranking/getRankersInDedication", term=term)["myRecord"]["score"], 1.)
        self.assertEqual(self.query("ranking/getMonthlyRankersInDedication")["myRecord"]["score"], 2.)
        for metric in ("Kokudaka", "Dedication", "NationalPower"):
            self.assertEqual(self.query("ranking/getBriefOf" + metric)["brief"]["lastRank"], 1.)
        self.now = 200
        self.assertEqual(self.query("ranking/getBriefOfDedicationMonthly")["brief"], {"rank": -1., "lastRank": 1.})
        self.assertEqual(self.query()["myRecord"]["score"], 10.)  # city value carries forward

    def test_missing_history_is_not_empty_and_no_historical_inventory_backfill(self):
        self.assertIn("no stub response", self.query("ranking/getBriefOfKokudaka")["errorReason"])
        self.assertEqual(self.query()["entries"], 0.)
        self.now = 110
        self.build()
        self.assertEqual(self.query(term="last")["entries"], 0.)
        self.assertEqual(self.query()["myRecord"]["score"], 10.)
        state = self.store.read()
        state["ledger"]["coverageStart"] = 50
        self.store.commit(state)
        self.assertIn("no stub response", self.query(term="last")["errorReason"])
        self.assertEqual(self.query()["myRecord"]["score"], 10.)

    def test_retry_and_commit_failure_never_half_write_or_replay_client_increment(self):
        self.build()
        self.donate()
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.donate()
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.donate(op="commit-failure")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.fail_commit = False
        self.assertEqual(self.donate(op="commit-failure")["gainPoint"], 1.)

    def test_concurrent_duplicate_gold_only_charges_once(self):
        self.build()
        before = self.store.read()["players"][self.pid]["resources"]["gold"]["amount"]
        def attempt(_):
            try:
                return self.donate()
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.store.read()["players"][self.pid]["resources"]["gold"]["amount"], before - 1000)

    def test_country_isolation_tie_order_and_page_local_keys(self):
        self.build()
        self.build("other", "build-other")
        self.donate()
        self.donate(pid="other", op="gold-other")
        national = self.query("ranking/getRankersInNationalPower", startIndex=1, endIndex=1)
        self.assertEqual(national["entries"], 2)
        self.assertEqual(national["rankers"]["0"]["countryId"], "country02")
        self.assertEqual(national["myRecord"], {"rank": 1., "score": 1.})
        self.assertEqual(self.query(playerId="other", country="country02")["entries"], 1)

    def test_unsupported_invalid_and_stale_city_do_not_charge(self):
        self.build()
        bad = [{"category": "character", "article": [1]}]
        bad += [{"category": "gold", "article": {"item11_0000101": n}}
                for n in (0, True, 1001, "1000", float("nan"), 1000000)]
        for params in bad:
            before = self.store.path.read_bytes()
            with self.assertRaises(ValueError):
                self.tx.gold(self.pid, params, operation_id="invalid")
            self.assertEqual(self.store.path.read_bytes(), before)
        state = self.store.read()
        state["players"][self.pid]["buildings"]["1"]["level"] = 2
        self.store.commit(state)
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "current authoritative city"):
            self.donate()
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_cap_uses_event_history_and_never_legacy_artificial_values(self):
        state = self.store.read()
        state["players"][self.pid]["kokudaka"] = 999999
        state["players"][self.pid]["rankingDedicationLimit"] = 9999999
        self.store.commit(state)
        self.build()
        self.assertEqual(self.store.read()["players"][self.pid]["rankingDedicationLimit"], 100)
        state = self.store.read()
        state["players"][self.pid]["resources"]["gold"]["amount"] = 200000
        self.store.commit(state)
        self.assertEqual(self.donate(100000)["dedication"]["point"], 100.)
        with self.assertRaisesRegex(ValueError, "limit exceeded"):
            self.donate(op="over-limit")

    def test_skill_subcity_and_missing_table_fail_closed(self):
        self.build()
        player = self.store.read()["players"][self.pid]
        player["decks"]["politic"] = {"0": {"ids": {"0": 123}}}
        with self.assertRaisesRegex(ValueError, "skill"):
            city_source(player, self.catalog)
        player["decks"]["politic"] = {}
        player["buildings"]["1"]["deployedMapKey"] = "map002"
        with self.assertRaisesRegex(ValueError, "subcity"):
            city_source(player, self.catalog)
        player["buildings"]["1"]["deployedMapKey"] = "map001"
        player["buildings"]["1"]["buildingTypeId"] = "missing"
        with self.assertRaisesRegex(ValueError, "no stub response"):
            city_source(player, self.catalog)
        class Missing:
            def load(self, name):
                raise MissingTableError(name)
        with self.assertRaisesRegex(ValueError, "stub has no assets"):
            city_source(player, Missing())

    def test_client_precision_original_formula_and_policy_disabled(self):
        row = self.catalog.load("building")[FIELD]
        self.assertEqual([building_kokudaka(row, n) for n in range(1, 11)], [10, 13, 16, 20, 23, 26, 30, 33, 36, 40])
        for number in (2**24 + 1, 2**31 - 1, 2**31, True):
            with self.assertRaises(ValueError):
                client_integer(number)
        self.assertEqual(client_integer(2**24 + 2), 2**24 + 2)
        state = self.store.read()
        state["ledger"]["goldOnlyNoWar"] = False
        self.store.commit(state)
        self.build()
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.donate()
        self.assertIn("no stub response", self.query("ranking/getRankersInNationalPower")["errorReason"])

    def test_watermark_rejects_late_events_and_one_read_per_query(self):
        self.build()
        self.now = 100
        before = self.store.read()["players"]
        self.query("ranking/getBriefOfKokudaka")
        self.assertEqual(self.read_calls, 1)
        self.assertEqual(self.store.read()["players"], before)
        self.now = 99
        with self.assertRaises(ValueError):
            self.donate()
        self.now = 100
        self.assertEqual(self.query(term="last")["myRecord"]["score"], 10.)

    def test_period_validation_and_expiration_do_not_guess_maintenance(self):
        self.assertEqual(period_pair(plans(), "kokudaka", 100)[0].key, "kokudaka:1")
        for now in (-1, 300, True):
            with self.assertRaises(ValueError):
                period_pair(plans(), "kokudaka", now)
        for field, value in (("start", 101), ("key", "kokudaka:0")):
            changed = plans()
            changed["kokudaka"][1][field] = value
            with self.assertRaises(ValueError):
                validate_periods(changed)

    def test_city_failure_and_duplicate_never_apply_a_partial_command(self):
        self.build()
        before = self.store.path.read_bytes()
        def broken(player):
            player["resources"]["gold"]["amount"] = 0
            raise ValueError("A command rejected")
        with self.assertRaisesRegex(ValueError, "A command rejected"):
            self.tx.city(self.pid, broken, operation_id="bad-city")
        self.assertEqual(self.store.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.tx.city(self.pid, broken, operation_id="build-1")
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_country_total_from_two_players_and_same_amount_new_identity(self):
        state = self.store.read()
        state["players"]["other"]["entity"]["country"] = "country01"
        self.store.commit(state)
        self.build()
        self.build("other", "build-other")
        self.donate()
        self.donate(op="second-legitimate-donation")
        self.donate(pid="other", op="other-donation")
        self.assertEqual(self.query("ranking/getRankersInNationalPower")["myRecord"]["score"], 3.)
        self.assertEqual(self.query("ranking/getRankersInDedication")["entries"], 2.)

    def test_all_eight_routes_auth_wire_types_and_bad_page_rejection(self):
        self.build()
        self.donate()
        self.now = 210
        self.donate(op="next-month")
        for api in LedgerRankingsServices.APIS:
            body = json.loads(json.dumps(self.query(api), allow_nan=False), parse_int=float)
            self.assertIs(body["succeeded"], True, body)
            self.assertEqual(set(body) - {"succeeded", "now"}, {"brief"} if "Brief" in api else {"entries", "myRecord", "rankers"})
            self.assertFalse(self.registry.dispatch(api, {}, None)[1]["succeeded"])
        for params in ({"term": "weekly"}, {"startIndex": True}, {"endIndex": 100},
                       {"startIndex": 5, "endIndex": 4}, {"startIndex": "0"}):
            self.assertFalse(self.query(**params)["succeeded"])

    def test_published_view_does_not_change_when_another_request_crosses_period(self):
        self.build()
        self.donate()
        captured, now = self.store.view(99)
        self.now = 100
        self.store.view(100)
        self.donate(op="new-period")
        old = project_pair(captured, "dedication", "country01", now)
        new = project_pair(self.store.read()["ledger"], "dedication", "country01", 100)
        self.assertIsNone(old[1])
        self.assertEqual(old[0][0]["score"], 1.)
        self.assertEqual(new[0][0]["score"], 1.)
        self.assertEqual(new[1][0]["score"], 1.)

    def test_bad_ledger_and_precision_failure_leave_real_state_unchanged(self):
        self.build()
        state = self.store.read()
        for ledger in (None, {}, {**state["ledger"], "events": []},
                       {**state["ledger"], "schema": True}):
            with self.assertRaises(ValueError):
                project_pair(ledger, "kokudaka", "country01", 10)
        # Synthetic extreme row is a failure probe, not original table evidence.
        original_load = self.catalog.load
        rows = copy.deepcopy(original_load("building"))
        rows[FIELD].update(kokudakaMin=2**24, kokudakaMax=2**24)
        rows["building200_051_01_01_1_1"].update(kokudakaMin=1, kokudakaMax=1)
        self.catalog.load = lambda name: rows if name == "building" else original_load(name)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.tx.city(self.pid, lambda p: self.service._build_from_draft(
                p, "draft2000051", (20, 20), completed=True), operation_id="overflow")
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
