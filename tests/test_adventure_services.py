"""Isolated saved-state projections; fixture progress is synthetic, not a starter grant."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from app.business.adventure_services import AdventureServices
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemorySessions, MemoryState

FIXTURES = Path(__file__).parent / "fixtures"


def snapshot():
    location = {"quest": 0, "chapter": 1, "area": 1, "step": 4}
    return {"version": 1, "progress": {"story": {"last": dict(location), "current": dict(location)}},
            "quests": {"quest_1_0000": {
                "completeFlags": {f"chapter{i}": 0 for i in range(1, 6)},
                "rewardOpenFlags": {f"chapter{i}": False for i in range(1, 6)},
                "chapters": {"1": {"complete": 0, "clearCount": 2, "areas": {
                    "1": {"complete": 0, "step": 4, "items": {"1": 1, "2": 0}}}}}}}}


class AdventureServicesTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.reload()
        self.session, _ = self.service._issue_login("adventure-isolated")
        result = self.service.create_player({"username": "adventure", "countryId": "country01",
            "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        self.assertTrue(result["succeeded"])
        player = self.saved()
        player["adventureV1"] = snapshot()
        self.save(player)

    def reload(self):
        self.service = GameplayService(catalog=TableCatalog(FIXTURES / "gameplay/tables",
            FIXTURES / "gameplay/tables/table_list.tsv"), load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.adventure = AdventureServices(self.service)
        self.catalog = TableCatalog(FIXTURES / "adventure", FIXTURES / "adventure/table_list.tsv")
        self.adventure.table = self.load_table
        self.adventure.register(self.registry)

    def load_table(self, name):
        try:
            return self.catalog.load(name)
        except MissingTableError as exc:
            raise ValueError(f"stub has no assets: required table {name}") from exc

    def saved(self):
        return self.states.load(self.session["playerId"])

    def save(self, player):
        self.states.save(player, self.session["playerId"])

    def call(self, name, **params):
        status, body = self.registry.dispatch("quest/" + name, params, self.session)
        self.assertEqual(status, 200, body)
        return body

    def test_progress_is_bare_and_relogin_does_not_reset_saved_position(self):
        before = self.saved()
        expected = before["adventureV1"]["progress"]
        self.assertEqual(self.call("getQuestProgress"), expected)
        self.reload()
        self.session, _ = self.service._issue_login("adventure-isolated")
        self.assertEqual(self.call("getQuestProgress"), expected)
        self.assertEqual(self.saved(), before)

    def test_chapter_combines_original_step_limit_and_saved_state(self):
        result = self.call("getChapterData", questType="story", questId=0, chapterId=1)
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["clearCount"], 2)
        self.assertEqual(result["area1"], {"complete": 0.0, "step": 4.0, "maxStep": 10.0,
            "item1": {"open": 1.0}, "item2": {"open": 0.0}})
        self.assertNotIn("area2", result)
        self.assertNotIn("reward", result)

    def test_flag_types_hierarchy_and_explicit_five_slots(self):
        result = self.call("getQuestCompleteFlags", questType="story")
        self.assertEqual(set(result), {"quest_1_0000"})
        self.assertEqual(len(result["quest_1_0000"]), 5)
        self.assertTrue(all(type(x) is float for x in result["quest_1_0000"].values()))
        reward = self.call("getQuestRewardOpenFlags", questType="story", questId=0)
        self.assertTrue(all(type(reward[f"chapter{i}"]) is bool for i in range(1, 6)))

    def test_missing_snapshot_never_initializes_or_grants(self):
        player = self.saved()
        del player["adventureV1"]
        self.save(player)
        for name in ("getQuestProgress", "getChapterData", "getQuestCompleteFlags", "getQuestRewardOpenFlags"):
            result = self.call(name, questType="story", questId=0, chapterId=1)
            self.assertIn("no stub response", result["errorReason"])
            self.assertEqual(self.saved(), player)

    def test_authentication_and_account_isolation(self):
        status, body = self.registry.dispatch("quest/getQuestProgress", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("authentication", body["errorReason"])
        other, _ = self.service._issue_login("adventure-other")
        status, body = self.registry.dispatch("quest/getQuestProgress", {"playerId": self.session["playerId"]}, other)
        self.assertEqual(status, 200)
        self.assertIn("errorReason", body)
        self.assertEqual(self.call("getQuestProgress", playerId=other["playerId"]), snapshot()["progress"])

    def test_invalid_ids_and_disabled_rows_have_no_side_effects(self):
        before = self.saved()
        for changes in ({"questId": True}, {"questId": 0.5}, {"questId": "0"}, {"questId": -1},
                        {"questId": 999}, {"chapterId": 2}, {"chapterId": 0},
                        {"questType": "../story"}, {"questType": []}):
            params = dict(questType="story", questId=0, chapterId=1)
            params.update(changes)
            result = self.call("getChapterData", **params)
            self.assertIn("errorReason", result)
            self.assertNotIn("stub has no assets", result["errorReason"])
            self.assertEqual(self.saved(), before)

    def test_missing_table_is_distinct_from_missing_row(self):
        with patch.object(self.service.catalog, "load", side_effect=MissingTableError("missing")):
            # Exercise the actual inherited loader, not the fixture adapter.
            self.adventure.table = super(AdventureServices, self.adventure).table
            body = self.call("getChapterData", questType="story", questId=0, chapterId=1)
        self.assertIn("stub has no assets", body["errorReason"])

    def test_corrupt_state_is_not_repaired_into_success(self):
        original = self.saved()
        for field, value in (("step", 11), ("step", float("nan")), ("complete", True), ("items", {"5": 1})):
            player = copy.deepcopy(original)
            player["adventureV1"]["quests"]["quest_1_0000"]["chapters"]["1"]["areas"]["1"][field] = value
            self.save(player)
            self.assertIn("errorReason", self.call("getChapterData", questType="story", questId=0, chapterId=1))
        player = copy.deepcopy(original)
        player["adventureV1"]["quests"]["quest_1_0000"]["rewardOpenFlags"]["chapter1"] = 1
        self.save(player)
        self.assertIn("errorReason", self.call("getQuestRewardOpenFlags", questType="story", questId=0))

    def test_parallel_retries_are_read_only_and_detached(self):
        before = self.saved()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.call("getQuestProgress"), range(32)))
        for result in results:
            self.assertEqual(result, snapshot()["progress"])
        results[0]["story"]["last"]["step"] = 999
        self.assertEqual(self.saved(), before)
        self.assertEqual(results[1]["story"]["last"]["step"], 4)

    def test_no_unspecified_handlers_registered(self):
        registry = Registry()
        self.adventure.register(registry)
        self.assertEqual(registry.known(), {"quest/" + name for name in (
            "getQuestProgress", "getChapterData", "getQuestCompleteFlags", "getQuestRewardOpenFlags")})

    def test_missing_flags_and_unknown_versions_fail_without_save(self):
        for mode in ("flag", "version", "current", "area"):
            player = self.saved()
            player["adventureV1"] = snapshot()
            saved = player["adventureV1"]
            if mode == "flag":
                del saved["quests"]["quest_1_0000"]["completeFlags"]["chapter5"]
                name, params = "getQuestCompleteFlags", {"questType": "story"}
            elif mode == "area":
                saved["quests"]["quest_1_0000"]["chapters"]["1"]["areas"] = {}
                name, params = "getChapterData", dict(questType="story", questId=0, chapterId=1)
            else:
                if mode == "version":
                    saved["version"] = 2
                else:
                    del saved["progress"]["story"]["current"]
                name, params = "getQuestProgress", {}
            self.save(player)
            self.assertIn("errorReason", self.call(name, **params))
            self.assertEqual(self.saved(), player)

    def test_baseline_normalization_conflict_uses_existing_guard(self):
        from app.state import StateConflictError
        player = self.saved()
        del player["unlockBits"]
        self.save(player)
        with patch.object(self.service, "save_state", side_effect=StateConflictError("test")):
            result = self.call("getQuestProgress")
        self.assertIn("retry", result["errorReason"])
        self.assertEqual(self.saved(), player)


if __name__ == "__main__":
    unittest.main()
