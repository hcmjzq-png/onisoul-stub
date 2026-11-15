"""Exercise the supplied integration patch in memory; public files stay intact."""
from pathlib import Path
import re
import unittest

from app.business.adventure_events import AdventureEvents
from app.business.registry import Registry
from tests import test_research331_b_story as story_tests


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "docs/analysis/research-331/results/b-adventure/integration.patch"


def patched_sources():
    lines = PATCH.read_text(encoding="utf-8").splitlines(True)
    result, index = {}, 0
    while index < len(lines):
        if not lines[index].startswith("--- a/"):
            raise AssertionError("unexpected integration patch format")
        path = lines[index][6:].strip()
        original = (ROOT / path).read_text(encoding="utf-8").splitlines(True)
        index += 2
        cursor, output = 0, []
        while index < len(lines) and not lines[index].startswith("--- a/"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[index])
            if not match:
                raise AssertionError("missing patch hunk")
            start = int(match[1]) - 1
            output.extend(original[cursor:start])
            cursor = start
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@", "--- a/")):
                line = lines[index]
                if line[0] in " -":
                    if original[cursor] != line[1:]:
                        raise AssertionError(f"patch context drift: {path}:{cursor + 1}")
                    cursor += 1
                if line[0] in " +":
                    output.append(line[1:])
                index += 1
        output.extend(original[cursor:])
        result[path] = "".join(output)
    return result


class IntegrationPatchTest(unittest.TestCase):
    def test_unsafe_placeholder_writes_are_blocked_without_counting_as_handlers(self):
        sources = patched_sources()
        namespace = {"__name__": "app.business.placeholders", "__package__": "app.business"}
        exec(compile(sources["app/business/placeholders.py"], "B-integration-patch", "exec"), namespace)
        writes = [api for api in namespace["BLOCKED_WRITES"] if api.startswith(("quest/", "battle/", "giganticRaidBoss/"))]
        self.assertEqual(len(writes), 13)
        for api in writes:
            handler = namespace["make_handler"](api)
            body = handler({}, None)
            self.assertFalse(body["succeeded"])
            self.assertIn("no stub response", body["errorReason"])
            self.assertTrue(handler.__name__.startswith("placeholder_"))
        self.assertIn("monster_story_1.json\tmonster_story_1\tMonsterTableAccessor",
                      sources["docs/analysis/server_tables.tsv"])

    def test_registration_whitelist_does_not_open_execution_or_other_groups(self):
        # Reuse setup, not synthetic adventure snapshots; nothing is pre-opened.
        scenario = story_tests.StoryPrefixTest()
        scenario.setUp()
        registry = Registry()
        AdventureEvents(scenario.service).register(registry, apis=frozenset({"quest/openQuest"}))
        self.assertEqual(registry.known(), {"quest/openQuest"})


if __name__ == "__main__":
    unittest.main()
