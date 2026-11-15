"""Regression for original resetList -> restoreMissions -> wakeupMission consumers."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.mission_chain import DEFAULT_BUTTON_BITS, SYSTEM_MISSION
from app.tables import TableCatalog
from tests.test_gameplay import FIXTURES, MemorySessions, MemoryStateStore
from tools.repair_initial_mission import apply_plan, digest, repaired


class NewPlayerTutorialTest(unittest.TestCase):
    def setUp(self):
        self.store, self.sessions = MemoryStateStore(), MemorySessions()
        self.service = self.restart()
        self.session, _ = self.service._issue_login("tutorial-test")
        self.service.create_player(dict(username="tutorial-test", countryId="country01",
                                        navigatorId="navi8000101", colorIndex="color1"), self.session)

    def restart(self):
        self.service = GameplayService(catalog=TableCatalog(FIXTURES, FIXTURES / "table_list.tsv"),
            load_state=self.store.load, save_state=self.store.save, session_store=self.sessions)
        return self.service

    def saved(self):
        return self.store.load(self.session["playerId"])

    def change(self, code, target):
        result = self.service.change_mission_state({"missionIds": [code], "states": [target]}, self.session)
        self.assertNotIn("errorReason", result)
        return result

    def unlock(self, bits):
        return self.service.set_working_value(dict(missionId=SYSTEM_MISSION, indexes=[0], values=[bits]), self.session)

    def test_fresh_and_relogin_wake_first_mission_without_claiming_completion(self):
        for _ in range(2):
            self.restart()
            summary = self.service.get_mission_states({}, self.session)["states"]
            details = self.service.get_missions_in_progress({}, self.session)["missions"]
            # Original IsLockedMission(1181): absence or L; wakeupMission(907)
            # uses that plus bootCheckFunc=none, then setup(null) latches AutoStart.
            self.assertIn(summary.get("1", "L"), ("L",))
            self.assertNotIn("po_mission_00001", details)
            self.assertEqual(self.saved()["missionRewards"], {})
            self.assertEqual(self.saved()["resources"]["gold"]["amount"], 5000)
            self.assertNotIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS))

    def test_every_active_state_has_restorable_detail_after_restart(self):
        for target, letter in (("opened", "O"), ("accepted", "A"), ("finished", "F")):
            self.change("po_mission_00001", target)
            self.restart()
            summary = self.service.get_mission_states({}, self.session)["states"]
            details = self.service.get_missions_in_progress({}, self.session)["missions"]
            self.assertEqual(summary["1"], letter)
            self.assertEqual(details["po_mission_00001"]["state"], target)
        self.change("po_mission_00001", "closed")
        before = self.saved()
        self.assertEqual(self.change("po_mission_00001", "closed")["reward"], {})
        self.assertEqual(self.saved()["resources"], before["resources"])
        self.restart()
        self.assertNotIn("po_mission_00001", self.service.get_missions_in_progress({}, self.session)["missions"])

    def test_unlock_accept_message_precedes_state_and_clear_requires_completion(self):
        self.assertIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS | 2))
        self.change("po_mission_00001", "accepted")
        self.change("po_mission_00001", "closed")
        self.change("po_mission_00002", "opened")
        self.assertNotIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS | 2))
        self.assertFalse(self.saved()["unlockBits"] & 2)
        self.assertEqual(self.saved()["missions"]["2"], "O")
        self.change("po_mission_00002", "accepted")
        self.restart()
        self.assertTrue(self.service.get_missions_in_progress({}, self.session)["missions"][SYSTEM_MISSION]["work0"] & 2)
        self.assertIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS | 2 | 16))
        self.assertNotIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS | 2))

    def test_rejected_batch_does_not_commit_experience_or_reward_receipt(self):
        self.change("po_mission_00001", "accepted")
        before = self.saved()
        result = self.service.change_mission_state(
            {"missionIds": ["po_mission_00001", "unknown"], "states": ["closed", "closed"]}, self.session,
        )
        self.assertIn("errorReason", result)
        self.assertEqual(self.saved(), before)

    def test_invalid_or_unearned_bits_never_change_saved_state(self):
        for value in (0xfffffff, -1, True, 1.5, "2", 0x8000, 0x20000000, 0x2000000):
            before = self.saved()
            self.assertIn("errorReason", self.unlock(value))
            self.assertEqual(self.saved(), before)
        for indexes, values in (([], []), ([0, 0], [0, 0]), ([1], [0]), ([False], [0])):
            result = self.service.set_working_value(dict(missionId=SYSTEM_MISSION, indexes=indexes, values=values), self.session)
            self.assertIn("errorReason", result)

    def test_reported_cache_cannot_grant_permissions_and_level_ten_screenshot_is_valid(self):
        p = self.saved(); p["unlockBits"] = 0xfffffff
        self.store.save(p, self.session["playerId"])
        result = self.service.get_missions_in_progress({}, self.session)
        self.assertEqual(result["missions"][SYSTEM_MISSION]["work0"], DEFAULT_BUTTON_BITS | 0x10000)
        p["entity"]["level"] = 10
        self.store.save(p, self.session["playerId"])
        self.assertNotIn("errorReason", self.unlock(DEFAULT_BUTTON_BITS | 0x2000000))
        self.assertFalse(self.saved()["unlockBits"] & 0x8000)

    def test_inconsistent_saved_states_fail_explicitly_without_guessing_or_writing(self):
        for letter in ("O", "A", "F"):
            p = self.saved(); p["missions"]["1"] = letter
            self.store.save(p, self.session["playerId"])
            for get in (self.service.get_mission_states, self.service.get_missions_in_progress):
                self.assertIn("summary/progress mismatch", get({}, self.session)["errorReason"])
            self.assertEqual(self.saved(), p)

    def test_repair_only_removes_known_orphan_marker_and_preserves_everything_else(self):
        p = self.saved(); p["missions"]["1"] = "O"
        rows = self.service.missions.rows()
        fixed = repaired(p, rows)
        expected = copy.deepcopy(p); del expected["missions"]["1"]
        self.assertEqual(fixed, expected)
        self.assertIsNone(repaired(fixed, rows))
        for key, value in (("missionProgress", {"po_mission_00001": {"state": "opened"}}),
                           ("missionRewards", {"po_mission_00001": {}}),
                           ("missionChecks", {"po_mission_00001": [1]}),
                           ("missions", {"0": "C", "1": "O", "2": "C"})):
            changed = copy.deepcopy(p); changed[key] = value
            self.assertIsNone(repaired(changed, rows))

    def test_repair_stale_preview_refuses_before_backup_or_any_write(self):
        from contextlib import contextmanager
        from app.state import StateConflictError
        p = self.saved(); p["missions"]["1"] = "O"
        after = repaired(p, self.service.missions.rows())
        plan = {"version": 1, "players": [{"player_id": "test", "before_sha256": digest(p), "after_sha256": digest(after)}]}
        live = copy.deepcopy(p); live["resources"]["gold"]["amount"] += 1
        @contextmanager
        def atomic(_ids):
            yield {"test": live}
        with tempfile.TemporaryDirectory() as folder, patch("tools.repair_initial_mission.state.atomic_players", atomic):
            backup = Path(folder) / "before.json"
            with self.assertRaises(StateConflictError):
                apply_plan(plan, self.service.missions.rows(), backup)
            self.assertFalse(backup.exists())
            self.assertEqual(live["missions"]["1"], "O")


if __name__ == "__main__":
    unittest.main()
