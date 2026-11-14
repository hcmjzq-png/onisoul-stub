"""Progression invariants against small subsets of the original installer tables."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemoryState, MemorySessions

FIXTURES = Path(__file__).parent / "fixtures"


class ProgressionTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.base = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        self.original = TableCatalog(FIXTURES / "progression", FIXTURES / "progression/table_list.tsv")
        self.reload()
        self.session, _ = self.service._issue_login("progression")
        self.service.create_player({"username": "progression", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)

    def load_table(self, name):
        if name in {"lesson", "reward14_lesson", "playerLevel", "politicMission", "defines"}:
            return self.original.load(name)
        return self.base.load(name)

    def reload(self):
        catalog = TableCatalog(FIXTURES / "gameplay/tables", FIXTURES / "gameplay/tables/table_list.tsv")
        catalog.load = self.load_table
        self.service = GameplayService(catalog=catalog, load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, api, **params):
        status, body = self.registry.dispatch(api, params, self.session)
        self.assertEqual(status, 200)
        return body

    def close(self, code, letter="C"):
        player = self.saved()
        index = self.original.load("politicMission")[code]["index"]
        player["missions"][str(index)] = letter
        self.save(player)

    def test_lesson_grants_original_reward_once_and_survives_reload(self):
        result = self.call("politic/mypage/takeLesson", lessonId="lesson_00001")
        self.assertEqual(result["reward"], {"item11_0000101": 5000.0})
        self.assertEqual(result["toInbox"], {})
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 10000)
        self.reload()
        self.assertEqual(self.call("politic/mypage/getLessonStates")["states"]["1"], "C")
        before = self.saved()
        self.assertEqual(self.call("politic/mypage/takeLesson", lessonId="lesson_00001")["reward"], {})
        self.assertEqual(self.saved(), before)

    def test_lesson_requires_closed_not_just_finished_prerequisite(self):
        for letter in ("L", "O", "A", "F"):
            self.close("po_mission_00012", letter)
            before = self.saved()
            self.assertFalse(self.call("politic/mypage/takeLesson", lessonId="lesson_00002")["succeeded"])
            self.assertEqual(self.saved(), before)
        self.close("po_mission_00012")
        self.assertEqual(self.call("politic/mypage/takeLesson", lessonId="lesson_00002")["reward"], {"item11_0000101": 1000.0})

    def test_lesson_experience_updates_entity_not_an_unusable_inventory_item(self):
        self.close("po_mission_00013")
        result = self.call("politic/mypage/takeLesson", lessonId="lesson_00023")
        self.assertEqual(result["reward"], {"item11_0000101": 1000.0, "item11_0000501": 50.0})
        self.assertEqual(self.saved()["entity"]["exp"], 50)
        self.assertNotIn("item11_0000501", self.saved()["items"])

    def test_lesson_rejects_bad_ranges_unsupported_delivery_and_overflow_atomically(self):
        self.close("po_mission_00013")
        before = self.saved()
        for code in ("missing", [], "lesson_00008", "lesson_00022"):
            self.assertFalse(self.call("politic/mypage/takeLesson", lessonId=code)["succeeded"])
            self.assertEqual(self.saved(), before)
        player = self.saved(); player["resources"]["gold"]["amount"] = 99999; self.save(player)
        before = self.saved()
        self.assertFalse(self.call("politic/mypage/takeLesson", lessonId="lesson_00001")["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_missing_lesson_reward_is_an_asset_failure_without_completion(self):
        original = self.service.catalog.load
        def load(name):
            if name == "reward14_lesson":
                raise MissingTableError("reward14_lesson")
            return original(name)
        before = self.saved()
        with patch.object(self.service.catalog, "load", side_effect=load):
            result = self.call("politic/mypage/takeLesson", lessonId="lesson_00001")
        self.assertIn("stub has no assets", result["errorReason"])
        self.assertEqual(self.saved(), before)

    def test_concurrent_claims_grant_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("politic/mypage/takeLesson", lessonId="lesson_00001"), range(2)))
        self.assertEqual(sum(r["reward"].get("item11_0000101", 0) for r in results), 5000)
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 10000)

    def test_original_initial_level_cap_is_five_and_gate_needs_closed_mission(self):
        self.assertEqual(self.saved()["entity"]["cap"], 5)
        for letter in ("L", "A", "F"):
            self.close("po_mission_07000", letter)
            self.assertEqual(self.call("common/solvePlayerLevelCap", cap=100)["cap"], 5)
        self.close("po_mission_07000")
        self.assertEqual(self.call("common/solvePlayerLevelCap")["cap"], 10)
        self.close("po_mission_07001"); self.close("po_mission_07002")
        self.assertEqual(self.call("common/solvePlayerLevelCap")["cap"], 15)  # defines.level_limit

    def test_level_uses_cumulative_exp_and_retries_cannot_grant_levels_or_points(self):
        self.call("common/increasePlayerLevel", exp=999999, level=100)
        self.assertEqual(self.saved()["entity"]["level"], 1)
        for exp, expected in ((199, 1), (200, 2), (499, 2), (500, 3)):
            player = self.saved(); player["entity"]["exp"] = exp
            player["actionPoints"]["missionPoint"]["point"] = 7; self.save(player)
            result = self.call("common/increasePlayerLevel")
            self.assertTrue(result["succeeded"])
            self.assertEqual(self.saved()["entity"]["level"], expected)
            self.assertEqual(self.saved()["entity"]["exp"], exp)
            self.assertEqual(self.saved()["actionPoints"]["missionPoint"]["point"], 7)
            self.assertEqual(self.saved()["actionPoints"]["missionPoint"]["maxPoint"], {1: 25, 2: 30, 3: 35}[expected])
            before = self.saved(); self.call("common/increasePlayerLevel"); self.assertEqual(self.saved(), before)

    def test_high_experience_stops_at_gate_and_never_downgrades_existing_level(self):
        player = self.saved(); player["entity"]["exp"] = 1000000; self.save(player)
        self.call("common/increasePlayerLevel")
        self.assertEqual(self.saved()["entity"]["level"], 5)
        self.close("po_mission_07000"); self.call("common/increasePlayerLevel")
        self.assertEqual(self.saved()["entity"]["level"], 10)
        self.close("po_mission_07000", "L"); self.call("common/increasePlayerLevel")
        self.assertEqual(self.saved()["entity"]["level"], 10)

    def test_loading_does_not_destroy_points_above_current_maximum(self):
        player = self.saved(); player["actionPoints"]["missionPoint"]["point"] = 40; self.save(player)
        result = self.call("common/getPlayerParams")
        self.assertEqual(result["actionPoints"]["missionPoint"]["point"], 40)
        self.assertEqual(result["actionPoints"]["missionPoint"]["maxPoint"], 25)

    def test_clock_heartbeat_and_entity_only_return_authenticated_account_data(self):
        with patch("time.time", return_value=1234567890):
            for api in ("common/getServerTime", "auth/keepAliveContainer"):
                result = self.call(api)
                self.assertEqual(result, {"succeeded": True, "now": 1234567890.0})
        self.assertEqual(self.call("common/getPlayerEntity", playerId="another")["playerId"], self.session["playerId"])
        for api in ("common/getServerTime", "auth/keepAliveContainer", "common/getPlayerEntity", "politic/mypage/takeLesson"):
            self.assertFalse(self.registry.dispatch(api, {}, None)[1]["succeeded"])

    def test_uncreated_player_cannot_claim_lesson(self):
        session, _ = self.service._issue_login("uncreated")
        result = self.registry.dispatch("politic/mypage/takeLesson", {"lessonId": "lesson_00001"}, session)[1]
        self.assertFalse(result["succeeded"])
