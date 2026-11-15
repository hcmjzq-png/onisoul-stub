"""Verify integrated quest failure gates through normal registration."""
import unittest

from app.business.adventure_events import AdventureEvents
from app.business.registry import Registry
from app.business.placeholders import BLOCKED_WRITES
from app.main import build_registry
from tests import test_research331_b_story as story_tests


class IntegrationPatchTest(unittest.TestCase):
    def test_unsafe_placeholder_writes_are_blocked_without_counting_as_handlers(self):
        registry = build_registry()
        writes = [api for api in BLOCKED_WRITES if api.startswith(("quest/", "battle/", "giganticRaidBoss/"))]
        self.assertEqual(len(writes), 13)
        for api in writes:
            status, body = registry.dispatch(api, {}, {"playerId": "unavailable"})
            self.assertEqual(status, 200)
            self.assertFalse(body["succeeded"])
            self.assertIn("no stub response", body["errorReason"])
            self.assertEqual(registry._handlers[api].__module__, "app.business.placeholders")

    def test_registration_whitelist_does_not_open_execution_or_other_groups(self):
        # Reuse setup, not synthetic adventure snapshots; nothing is pre-opened.
        scenario = story_tests.StoryPrefixTest()
        scenario.setUp()
        registry = Registry()
        AdventureEvents(scenario.service).register(registry, apis=frozenset({"quest/openQuest"}))
        self.assertEqual(registry.known(), {"quest/openQuest"})


if __name__ == "__main__":
    unittest.main()
