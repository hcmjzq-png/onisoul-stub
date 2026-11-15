"""Real original table rows; history is produced through operations, not seeded."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import unittest

from app.business.adventure_events import AdventureEvents, StepIntent
from app.business.adventure_battles import AdventureBattles
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.state import StateConflictError
from app.tables import TableCatalog, MissingTableError
from tools.gameplay_smoke import MemorySessions, MemoryState


FIXTURES = Path(__file__).parent / "fixtures"
ORIGINAL = FIXTURES / "research331/b-adventure"
PARAMS = dict(questType="story", questId=0, chapterId=1, areaId=1, assets="map0")


class StoryPrefixTest(unittest.TestCase):
    def setUp(self):
        self.states, self.sessions = MemoryState(), MemorySessions()
        self.overrides = {}
        self.reload()
        self.session, _ = self.service._issue_login("research331-B")
        self.assertTrue(self.service.create_player(dict(username="story", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), self.session)["succeeded"])

    def reload(self):
        self.service = GameplayService(catalog=TableCatalog(FIXTURES / "gameplay/tables",
            FIXTURES / "gameplay/tables/table_list.tsv"), load_state=self.states.load,
            save_state=self.states.save, session_store=self.sessions)
        self.events = AdventureEvents(self.service)
        self.catalog = TableCatalog(ORIGINAL, ORIGINAL / "table_list.tsv")
        self.events.table = lambda name: copy.deepcopy(self.overrides[name] if name in self.overrides
                                                       else self.catalog.load(name))
        self.registry = self.service.register(Registry()).register_contract_defaults()
        self.events.register(self.registry)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def query(self, name, **params):
        status, body = self.registry.dispatch("quest/" + name, params, self.session)
        self.assertEqual(status, 200)
        return body

    def open(self):
        result = self.query("openQuest", questType="story")
        self.assertTrue(result["succeeded"], result)
        return result

    def step(self, expected, operation=None, params=None):
        intent = StepIntent(self.session["playerId"], operation or f"action-{expected}", expected)
        return self.events.execute_trusted(params or PARAMS, self.session, intent)

    def advance(self, count):
        for expected in range(count):
            result = self.step(expected)
            self.assertTrue(result["succeeded"], result)

    def test_open_step_reward_encounter_and_relogin_use_produced_state(self):
        initial = self.saved()
        self.assertNotIn("adventureV1", initial)
        self.assertTrue(self.open()["addWork"])
        self.advance(5)
        saved = self.saved()
        self.assertEqual(saved["actionPoints"]["missionPoint"]["point"],
                         initial["actionPoints"]["missionPoint"]["point"] - 5)
        self.assertEqual(saved["resources"], initial["resources"])
        self.assertEqual(saved["items"]["item08_0102701"], initial["items"].get("item08_0102701", 0) + 1)
        added = set(saved["characters"]) - set(initial["characters"])
        self.assertEqual(len(added), 1)
        card = saved["characters"][added.pop()]
        self.assertEqual((card["baseId"], card["atk"], card["def"], card["int"]),
                         ("chara1_00324_01", 60, 465, 225))
        self.assertEqual(len(saved["adventureV1"]["storyLifecycle"]["events"]), 5)
        self.reload()
        self.session, _ = self.service._issue_login("research331-B")
        progress = self.query("getQuestProgress")
        self.assertEqual(progress["story"]["current"]["step"], 5)
        chapter = self.query("getChapterData", questType="story", questId=0, chapterId=1)
        self.assertEqual(chapter["area1"]["step"], 5)
        self.assertEqual(chapter["area1"]["item1"]["open"], 1)
        self.assertEqual(chapter["area1"]["item2"]["open"], 1)
        self.assertEqual(chapter["area1"]["item3"]["open"], 0)
        self.assertEqual((chapter["complete"], chapter["clearCount"]), (0, 0))
        self.assertFalse(any(self.query("getQuestCompleteFlags", questType="story")["quest_1_0000"].values()))
        pending = self.query("getQuestEncount")
        self.assertEqual(pending["story"], dict(questId="quest_1_0000", chapter=1, area=1, step=5))
        encounter = saved["adventureV1"]["storyLifecycle"]["events"]["5"]["encounter"]
        self.assertEqual(encounter["monster"]["maxHp"], 1000)
        self.assertNotIn("winner", encounter)
        self.assertFalse(self.open()["addWork"])
        self.assertEqual(self.saved(), saved)

    def test_retries_concurrency_and_stale_distinct_intents_do_not_double_grant(self):
        self.open()
        self.advance(2)
        before = self.saved()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda n: self.step(2, f"parallel-{n}"), range(24)))
        self.assertEqual(sum(result["succeeded"] for result in results), 1)
        saved = self.saved()
        self.assertEqual(len(saved["characters"]), len(before["characters"]) + 1)
        self.assertEqual(saved["actionPoints"]["missionPoint"]["point"],
                         before["actionPoints"]["missionPoint"]["point"] - 1)
        operation = saved["adventureV1"]["storyLifecycle"]["events"]["3"]["operationId"]
        self.reload()
        result = self.step(2, operation)
        self.assertFalse(result["succeeded"])
        self.assertNotIn("rewardInfo", result)
        self.assertEqual(self.saved(), saved)
        # Changing expected step while reusing the old identity is also a retry.
        self.assertFalse(self.step(3, operation)["succeeded"])
        self.assertEqual(self.saved(), saved)

    def test_duplicate_callbacks_never_apply_a_second_character_delta(self):
        self.open()
        self.advance(2)
        displayed = len(self.saved()["characters"])
        for _ in range(2):
            result = self.step(2)
            if result.get("succeeded") and "errorReason" not in result:
                displayed += int(result["rewardInfo"].get("item01_0032401", 0))
        self.assertEqual(displayed, len(self.saved()["characters"]))

    def test_invalid_requests_identity_and_activity_do_not_write(self):
        self.open()
        before = self.saved()
        for change in (dict(questType="event"), dict(questId=1), dict(areaId=2),
                       dict(chapterId=2), dict(assets="map1"), dict(questId=True)):
            self.assertFalse(self.step(0, params={**PARAMS, **change})["succeeded"])
        for intent in (None, StepIntent("other-player", "x", 0),
                       StepIntent(self.session["playerId"], "", 0)):
            self.assertFalse(self.events.execute_trusted(PARAMS, self.session, intent)["succeeded"])
        self.assertFalse(self.query("openQuest", questType="event")["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_raw_http_parameters_cannot_smuggle_a_step_intent(self):
        self.open()
        before = self.saved()
        _, result = self.registry.dispatch("quest/executeQuestEx",
            {**PARAMS, "operationId": "forged", "expectedStep": 0}, self.session)
        # Baseline placeholder replies are NOT semantic success. This producer
        # never registers execute; the integration patch blocks this placeholder.
        self.assertEqual(self.registry._handlers["quest/executeQuestEx"].__module__,
                         "app.business.placeholders")
        self.assertEqual(self.saved(), before)

    def test_insufficient_mp_and_character_capacity_are_atomic(self):
        self.open()
        self.advance(2)
        original = self.saved()
        for restriction in ("mp", "capacity"):
            player = copy.deepcopy(original)
            if restriction == "mp":
                player["actionPoints"]["missionPoint"]["point"] = 0
            else:
                self.service._possession_limits = lambda p: {"character": {"result": len(player["characters"])}}
            self.states.save(player, self.session["playerId"])
            before = self.saved()
            self.assertFalse(self.step(2)["succeeded"])
            self.assertEqual(self.saved(), before)

    def test_bad_reward_and_probabilistic_event_are_atomic(self):
        self.open()
        self.advance(2)
        before = self.saved()
        rewards = self.catalog.load("quest_1_0000_reward")
        self.overrides["quest_1_0000_reward"] = copy.deepcopy(rewards)
        self.overrides["quest_1_0000_reward"]["quest_1_0000_03_002"]["count1max"] = 2
        self.assertFalse(self.step(2)["succeeded"])
        self.assertEqual(self.saved(), before)
        self.overrides.clear()
        rows = self.catalog.load("quest_1_0000")
        self.overrides["quest_1_0000"] = copy.deepcopy(rows)
        self.overrides["quest_1_0000"]["1_1_3"]["event2"] = [1, 1, "x", "none", "none", "none", "none"]
        self.assertFalse(self.step(2)["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_table_asset_failure_vs_bad_reference(self):
        self.open()
        self.advance(4)
        before = self.saved()
        self.overrides["monster_story_1"] = {}
        self.assertIn("no stub response", self.step(4)["errorReason"])
        self.assertEqual(self.saved(), before)
        # Use the real PlayerServices.table exception translation, not the fixture override.
        self.events.table = AdventureEvents.table.__get__(self.events)
        original = self.service.catalog.load
        self.service.catalog.load = lambda name: (_ for _ in ()).throw(MissingTableError("missing"))
        self.assertIn("stub has no assets", self.step(4)["errorReason"])
        self.service.catalog.load = original
        self.assertEqual(self.saved(), before)

    def test_existing_history_is_not_migrated_or_reset(self):
        self.open()
        self.advance(1)
        player = self.saved()
        del player["adventureV1"]["storyLifecycle"]
        self.states.save(player, self.session["playerId"])
        self.assertFalse(self.query("openQuest", questType="story")["succeeded"])
        self.assertFalse(self.step(1)["succeeded"])
        self.assertEqual(self.saved(), player)

    def test_jewel_overflow_does_not_charge_or_advance(self):
        self.open()
        self.advance(3)
        player = self.saved()
        player["items"]["item08_0102701"] = 2147483647
        self.states.save(player, self.session["playerId"])
        self.assertFalse(self.step(3)["succeeded"])
        self.assertEqual(self.saved(), player)

    def test_no_fabricated_victory_completion_or_history_after_encounter(self):
        self.open()
        self.advance(5)
        before = self.saved()
        self.assertFalse(self.step(5)["succeeded"])
        for api in ("battle/executeBattle", "quest/checkCompleteQuestEx", "battle/getVsBattleLogs"):
            self.assertEqual(self.registry._handlers[api].__module__, "app.business.placeholders")
        self.assertEqual(self.saved(), before)

    def test_two_service_instances_compare_and_swap_whole_operation(self):
        self.open()
        self.advance(2)
        first, first_service = self.events, self.service
        self.reload()
        second, second_service = self.events, self.service
        gate, lock = threading.Barrier(2), threading.Lock()
        reads = 0

        def load(pid):
            nonlocal reads
            with lock:
                row = self.states.load(pid)
                reads += 1
                wait = reads <= 2
            if wait:
                gate.wait(timeout=5)
            return row

        def save(player, pid):
            with lock:
                latest = self.states.load(pid)
                if player.get("_revision", 0) != latest.get("_revision", 0):
                    raise StateConflictError("isolated CAS")
                result = copy.deepcopy(player)
                result["_revision"] = latest.get("_revision", 0) + 1
                self.states.save(result, pid)

        for service in (first_service, second_service):
            service.load_state, service.save_state = load, save
        before = self.saved()
        intent = StepIntent(self.session["playerId"], "lost-response-retry", 2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [f.result() for f in [pool.submit(e.execute_trusted, PARAMS, self.session, intent)
                                          for e in (first, second)]]
        self.assertEqual(sum(r["succeeded"] for r in results), 1)
        self.assertEqual(len(self.saved()["characters"]), len(before["characters"]) + 1)
        self.assertFalse(second.execute_trusted(PARAMS, self.session, intent)["succeeded"])

    def test_fixture_integrity_and_no_generated_player_snapshots(self):
        proof = json.loads((ORIGINAL / "source-proof.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(len(t["selected_rows"]) for t in proof["tables"]), 20)
        for table in proof["tables"]:
            self.assertEqual(hashlib.sha256((ORIGINAL / table["file"]).read_bytes()).hexdigest(),
                             table["fixture_sha256"])

    def test_battle_input_requires_real_owned_encounter_and_preserves_formation(self):
        self.open()
        battle = AdventureBattles(self.service)
        battle.table = self.events.table
        params = {"battleInformation": {"battleType": "QUEST_BATTLE", "questType": "story",
                                         "encountId": 5, "deckIndex": {"attacker": 0, "defender": 0}}}
        with self.assertRaisesRegex(ValueError, "owned pending"):
            battle.prepare_quest_battle(self.saved(), params)
        self.advance(5)
        before = self.saved()
        snapshot = battle.prepare_quest_battle(before, params)
        self.assertEqual(snapshot["ownerId"], self.session["playerId"])
        self.assertEqual(snapshot["encounter"]["monsterId"], "q_mons_0000_01")
        positions = [row["position"] for row in snapshot["formation"]]
        self.assertEqual(positions, sorted(positions))
        snapshot["formation"][0]["character"]["atk"] = 999999
        self.assertEqual(self.saved(), before)
        invalid = copy.deepcopy(params)
        invalid["battleInformation"]["encountId"] = 999
        with self.assertRaisesRegex(ValueError, "owned pending"):
            battle.prepare_quest_battle(before, invalid)
        other, _ = self.service._issue_login("research331-B-other")
        self.service.create_player(dict(username="other", countryId="country01",
            navigatorId="navi8000101", colorIndex="color1"), other)
        with self.assertRaises(ValueError):
            battle.prepare_quest_battle(self.states.load(other["playerId"]), params)
        self.assertEqual(self.saved(), before)

    def test_unowned_and_duplicate_battle_cards_are_rejected(self):
        self.open()
        self.advance(5)
        battle = AdventureBattles(self.service)
        battle.table = self.events.table
        params = {"battleInformation": {"battleType": "QUEST_BATTLE", "questType": "story",
                                         "encountId": 5, "deckIndex": {"attacker": 0, "defender": 0}}}
        original = self.saved()
        first = next(iter(original["characters"]))
        for ids in ({"0": 999999}, {"0": int(first), "4": int(first)}):
            bad = copy.deepcopy(original)
            bad["decks"]["quest"]["0"]["ids"] = ids
            with self.assertRaisesRegex(ValueError, "ownership"):
                battle.prepare_quest_battle(bad, params)
        self.assertEqual(self.saved(), original)

    def test_broken_event_receipt_and_false_completion_are_rejected_on_read(self):
        self.open()
        self.advance(3)
        original = self.saved()
        for defect in ("receipt", "completion"):
            bad = copy.deepcopy(original)
            saved = bad["adventureV1"]
            if defect == "receipt":
                saved["storyLifecycle"]["receipts"].clear()
            else:
                saved["quests"]["quest_1_0000"]["completeFlags"]["chapter1"] = 1
                saved["quests"]["quest_1_0000"]["chapters"]["1"]["complete"] = 1
            self.states.save(bad, self.session["playerId"])
            result = self.query("getQuestCompleteFlags", questType="story")
            self.assertIn("no stub response", result["errorReason"])
            self.assertFalse(self.step(3)["succeeded"])
            self.assertEqual(self.saved(), bad)


if __name__ == "__main__":
    unittest.main()
