import unittest
from unittest.mock import patch

from app.business.local_quest_menu import LocalQuestMenu
from app.main import build_registry
from tests import test_research331_b_story as story_fixture
from tools.native_story_preview import NativeStoryPreview


class LocalQuestMenuTest(unittest.TestCase):
    def setUp(self):
        self.story = story_fixture.StoryPrefixTest()
        self.story.setUp()
        self.session = self.story.session
        table_patch = patch.object(LocalQuestMenu, "table", side_effect=self.story.events.table)
        table_patch.start()
        self.addCleanup(table_patch.stop)

    def registry(self, menu_type=LocalQuestMenu):
        with patch("app.main.GameplayService", return_value=self.story.service):
            registry = build_registry()
        if menu_type is not None:
            menu_type(self.story.service).register(registry)
        return registry

    def test_closed_activity_checks_do_not_block_menu_or_touch_save(self):
        registry = self.registry()
        before = self.story.saved()
        for kind in ("random", "random2", "event", "event2", "event3"):
            with self.subTest(kind=kind):
                params = {"questType": kind}
                if kind.startswith("event"):
                    status, body = registry.dispatch("quest/openQuest", params, self.session)
                    self.assertEqual(status, 200)
                    self.assertEqual({k: v for k, v in body.items() if k != "now"}, {
                        "succeeded": True, "questType": kind, "questIds": {}, "addWork": False,
                    })
                self.assertEqual(registry.dispatch("quest/getQuestCompleteFlags", params, self.session), (200, {}))
        self.assertEqual(self.story.saved(), before)

    def test_read_then_open_story_with_original_chapter_and_no_grants(self):
        registry = self.registry()
        before = self.story.saved()
        params = {"questType": "story", "questId": 0, "chapterId": 1}

        def query(name, params=params):
            status, body = registry.dispatch("quest/" + name, params, self.session)
            self.assertEqual(status, 200)
            self.assertNotIn("errorReason", body)
            return body

        start = {"quest": 0, "chapter": 1, "area": 1, "step": 0}
        self.assertEqual(query("getQuestProgress", {}), {"story": {"last": start, "current": start}})
        self.assertEqual(query("getQuestCompleteFlags"), {"quest_1_0000": {f"chapter{i}": 0 for i in range(1, 6)}})
        self.assertEqual(self.story.saved(), before)
        self.assertTrue(query("openQuest")["addWork"])
        self.assertEqual(query("getChapterData")["area1"]["maxStep"], 10)
        self.assertIs(query("getQuestRewardOpenFlags")["chapter1"], False)
        self.assertFalse(query("openQuest")["addWork"])
        after = self.story.saved()
        self.assertEqual({k: v for k, v in after.items() if k != "adventureV1"}, before)
        self.assertEqual(after["adventureV1"]["storyLifecycle"]["events"], {})
        _, step = registry.dispatch("quest/executeQuestEx", params, self.session)
        self.assertIn("no stub response", step["errorReason"])
        self.assertEqual(self.story.saved(), after)

    def test_other_types_and_default_registry_keep_failure(self):
        local = self.registry()
        status, body = local.dispatch("quest/openQuest", {"questType": "event"}, None)
        self.assertEqual(status, 200)
        self.assertFalse(body["succeeded"])
        self.assertEqual(body["errorReason"], "authentication required")
        cases = [(local, kind) for kind in ("random", "random2", "event4", [])]
        cases += [(self.registry(None), kind) for kind in ("story", "event")]
        for registry, kind in cases:
            with self.subTest(kind=kind):
                status, body = registry.dispatch("quest/openQuest", {"questType": kind}, self.session)
                self.assertEqual(status, 200)
                self.assertFalse(body["succeeded"])
                self.assertIn("no stub response", body["errorReason"])

    def test_preview_projects_unplayed_areas_and_keeps_saved_tutorial(self):
        self.story.open()
        self.story.advance(5)
        before = self.story.saved()
        index = self.story.catalog.load("quest_1_index")
        self.story.overrides["quest_1_index"] = {
            "0_1": index["0_1"],
            "1_2": {"questNo": 1, "chapterNo": 2, "enable": True, "clientEnable": True,
                    "areaCount": 2, "areaStep1": 15, "areaStep2": 12},
            "2_1": {"questNo": 2, "chapterNo": 1, "enable": True, "clientEnable": False},
        }
        self.story.overrides["quest_1_0001"] = {"2_1_1": {"item1": "item08_0102702"}, "2_2_1": {"item1": "none"}}
        registry = self.registry(NativeStoryPreview)

        def query(name, **params):
            return registry.dispatch("quest/" + name, {"questType": "story", **params}, self.session)[1]

        flags = query("getQuestCompleteFlags")
        self.assertEqual(set(flags), {"quest_1_0000", "quest_1_0001"})
        self.assertFalse(any(flags["quest_1_0001"].values()))
        tutorial = query("getChapterData", questId=0, chapterId=1)["area1"]
        self.assertEqual((tutorial["step"], tutorial["item2"]["open"]), (5, 1))
        preview = query("getChapterData", questId=1, chapterId=2)
        self.assertEqual((preview["area1"]["maxStep"], preview["area2"]["maxStep"]), (15, 12))
        self.assertEqual(preview["area1"]["item1"], {"open": 0})
        self.assertNotIn("item1", preview["area2"])
        self.assertFalse(query("getChapterData", questId=2, chapterId=1)["succeeded"])
        self.assertIn("no stub response", query("executeQuestEx", questId=1, chapterId=2)["errorReason"])
        self.assertEqual(self.story.saved(), before)
