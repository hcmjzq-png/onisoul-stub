"""End-to-end tests for login, main map, and novice missions 1-4."""
from __future__ import annotations

import copy
import hashlib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
from tools import gameplay_smoke

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gameplay" / "tables"


class MemoryStateStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def load(self, player_id: str) -> dict:
        return copy.deepcopy(self.rows.get(player_id, {}))

    def save(self, player: dict, player_id: str) -> None:
        self.rows[player_id] = copy.deepcopy(player)


class MemorySessions:
    def __init__(self):
        self.tokens: dict[str, dict] = {}
        self.accounts: dict[str, str] = {}
        self.counter = 0

    def issue(self, account_key: str, token: str | None = None) -> dict:
        key = str(account_key or "default")
        if key not in self.accounts:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
            self.accounts[key] = f"p_{digest}"
        self.counter += 1
        token = token or f"token-{self.counter}"
        session = {
            "token": token,
            "accountKey": key,
            "playerId": self.accounts[key],
        }
        self.tokens[token] = session
        return copy.deepcopy(session)

    def resolve(self, token: str | None) -> dict | None:
        return copy.deepcopy(self.tokens.get(str(token or "")))


class GameplayFlowTest(unittest.TestCase):
    def setUp(self):
        self.key_patch = patch.dict("os.environ", {"STUB_DEBUG_LOGIN_KEY": "audit-test"})
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.states = MemoryStateStore()
        self.sessions = MemorySessions()
        self.service = GameplayService(
            catalog=TableCatalog(FIXTURES, FIXTURES / "table_list.tsv"),
            load_state=self.states.load,
            save_state=self.states.save,
            session_store=self.sessions,
        )

    def _login_and_create(self):
        login = self.service.dev_login({"username": "new-player", "key": "audit-test"}, None)
        self.assertFalse(login["succeeded"])
        session = {"playerId": login["playerId"], "token": login["token"]}
        created = self.service.create_player(
            {
                "username": "new-player",
                "countryId": "country01",
                "navigatorId": "navi8000101",
                "colorIndex": "color1",
            },
            session,
        )
        self.assertTrue(created["succeeded"])
        return session

    def _change(self, session, mission_id: str, state: str):
        return self.service.change_mission_state(
            {"missionIds": [mission_id], "states": [state]}, session
        )

    def test_new_player_login_player_params_and_repeat_login(self):
        session = self._login_and_create()
        params = self.service.get_player_params({}, session)
        self.assertTrue(params["succeeded"])
        self.assertEqual(params["entity"]["username"], "new-player")
        self.assertEqual(params["entity"]["country"], "country01")
        self.assertEqual(params["entity"]["cap"], 2)
        self.assertEqual(params["actionPoints"]["politicPoint"]["point"], 25)
        self.assertEqual(params["resources"]["gold"]["amount"], 5000)
        for resource in ("food", "wood", "iron", "credit"):
            self.assertEqual(params["resources"][resource]["amount"], 0)
        self.assertEqual(params["actionPoints"]["missionPoint"]["point"], 25)
        self.assertEqual(params["actionPoints"]["battlePoint"]["point"], 100)
        self.assertEqual(params["characterCount"], 4.0)
        self.assertEqual(params["possessionLimits"]["character"]["result"], 400.0)

        login_again = self.service.dev_login({"username": "new-player", "key": "audit-test"}, None)
        self.assertTrue(login_again["succeeded"])
        self.assertEqual(login_again["playerId"], session["playerId"])
        game_login = self.service.game_login({"token": session["token"]}, session)
        self.assertTrue(game_login["succeeded"])

    def test_starting_gold_is_not_reissued_on_load_login_or_repeated_create(self):
        session = self._login_and_create()
        player = self.states.load(session["playerId"])
        player["resources"]["gold"]["amount"] = 123
        self.states.save(player, session["playerId"])
        self.service.get_player_params({}, session)
        self.service.game_login({"token": session["token"]}, session)
        self.service.create_player({"username": "new-player", "countryId": "country01"}, session)
        self.assertEqual(self.states.load(session["playerId"])["resources"]["gold"]["amount"], 123)

    def test_existing_zero_balance_is_not_retroactively_funded(self):
        session = self._login_and_create()
        player = self.states.load(session["playerId"])
        player["resources"]["gold"]["amount"] = 0
        self.states.save(player, session["playerId"])
        self.assertEqual(self.service.get_player_params({}, session)["resources"]["gold"]["amount"], 0)

    def test_main_map_and_avatar_payload_shapes(self):
        session = self._login_and_create()
        avatars = self.service.get_avatar_characters({}, session)
        self.assertEqual(len(avatars), 1)
        first = next(iter(avatars.values()))
        self.assertIn("baseId", first)
        self.assertIn("grade", first)
        self.assertIn("voice", first)
        self.assertIn("atk", first)
        self.assertIn("skills", first)
        self.assertNotIn("succeeded", avatars)

        map_data = self.service.get_map_data({}, session)
        self.assertEqual(map_data["map"]["size"], {"width": 30.0, "height": 30.0})
        self.assertEqual(map_data["currentMapId"], 0.0)
        self.assertEqual(map_data["buildings"], {})
        self.assertEqual(map_data["tasks"]["buildings"], {})
        self.assertEqual(map_data["buildingCount"], 0.0)

    def test_missions_1_to_4_rewards_buildings_and_persistence(self):
        session = self._login_and_create()
        baseline = self.service.get_mission_states({}, session)
        self.assertEqual(baseline["states"], {"0": "C"})
        self.assertEqual(self.service.get_drafts({}, session)["draft2000002"]["amount"], 1.0)

        for state in ("opened", "accepted", "finished", "closed"):
            result = self._change(session, "po_mission_00001", state)
            self.assertIn("mission", result)
        player = self.states.load(session["playerId"])
        self.assertEqual(player["resources"]["gold"]["amount"], 10000)
        self.assertEqual(player["resources"]["credit"]["amount"], 0)
        self.assertEqual(player["entity"]["exp"], 25)
        self.assertNotIn("item11_0000501", player["items"])
        self.assertEqual(player["missions"]["1"], "C")

        duplicate = self._change(session, "po_mission_00001", "closed")
        self.assertEqual(duplicate["reward"], {})
        player = self.states.load(session["playerId"])
        self.assertEqual(player["resources"]["gold"]["amount"], 10000)

        self.assertEqual(player["entity"]["exp"], 25)
        self.service = GameplayService(
            catalog=TableCatalog(FIXTURES, FIXTURES / "table_list.tsv"),
            load_state=self.states.load, save_state=self.states.save, session_store=self.sessions,
        )
        self.assertEqual(self.service.get_player_params({}, session)["entity"]["exp"], 25)

        self._change(session, "po_mission_00002", "accepted")
        build = self.service.submit_build_task(
            {"draftId": "draft2000002", "originCoord": [25, 25]}, session
        )
        self.assertTrue(build["succeeded"])
        castle_id = build["buildingId"]
        self.assertEqual(build["building"]["status"], "building")
        completed = self.service.complete_tasks({"buildingIds": [castle_id]}, session)
        self.assertEqual(completed["buildings"][castle_id]["status"], "none")
        self.assertEqual(
            self.service.get_build_counts({}, session)["type"],
            {"building200_002_01_01_1_1": 1.0},
        )
        self.assertNotIn("draft2000002", self.service.get_drafts({}, session))
        self._change(session, "po_mission_00002", "closed")

        self._change(session, "po_mission_00003", "accepted")
        self._change(session, "po_mission_00003", "closed")
        self.assertEqual(self.service.get_drafts({}, session)["draft2000041"]["amount"], 1.0)

        self._change(session, "po_mission_00004", "accepted")
        field = self.service.submit_build_and_complete(
            {"draftId": "draft2000041", "originCoord": [27, 27]}, session
        )
        self.assertTrue(field["succeeded"])
        self.assertEqual(field["building"]["status"], "none")
        self.assertEqual(
            self.service.get_build_counts({}, session)["type"],
            {
                "building200_002_01_01_1_1": 1.0,
                "building200_041_01_01_1_1": 1.0,
            },
        )
        self._change(session, "po_mission_00004", "closed")

        player = self.states.load(session["playerId"])
        self.assertEqual(player["missions"]["4"], "C")
        self.assertEqual(player["counters"]["buildingCount"], 2)
        self.assertEqual(player["occupiedGrids"]["25,25"], "1")
        self.assertEqual(player["occupiedGrids"]["27,27"], "2")
        self.assertEqual(player["buildings"]["2"]["buildingTypeId"], "building200_041_01_01_1_1")

        map_data = self.service.get_map_data({}, session)
        self.assertEqual(map_data["occupiedGrids"]["27,27"], "2")
        self.assertEqual(map_data["buildings"]["2"]["status"], "none")

    def test_unearned_client_unlock_bits_are_rejected(self):
        session = self._login_and_create()
        result = self.service.set_working_value(
            {
                "missionId": "po_mission_00000",
                "indexes": [0],
                "values": [0x400],
            },
            session,
        )
        stored = self.states.load(session["playerId"])
        self.assertFalse(result["succeeded"])
        self.assertFalse(int(stored["unlockBits"]) & 0x400)
        missions = self.service.get_missions_in_progress({}, session)["missions"]
        self.assertFalse(int(missions["po_mission_00000"]["work0"]) & 0x400)

    def test_new_player_detection_is_account_specific(self):
        first = self._login_and_create()
        second_login = self.service.dev_login({"username": "second-player", "key": "audit-test"}, None)
        self.assertFalse(second_login["succeeded"])
        self.assertNotEqual(first["playerId"], second_login["playerId"])
        first_login_again = self.service.dev_login({"username": "new-player", "key": "audit-test"}, None)
        self.assertTrue(first_login_again["succeeded"])
        self.assertEqual(first_login_again["playerId"], first["playerId"])

    def test_create_player_validates_country_navigator_and_name(self):
        login = self.service.dev_login({"username": "validation-player", "key": "audit-test"}, None)
        session = {"playerId": login["playerId"], "token": login["token"]}
        base = {
            "username": "validation-player",
            "countryId": "country01",
            "navigatorId": "navi8000101",
            "colorIndex": "color1",
        }
        self.assertFalse(
            self.service.create_player({**base, "username": ""}, session)["succeeded"]
        )
        self.assertFalse(
            self.service.create_player({**base, "countryId": "bad"}, session)["succeeded"]
        )
        self.assertFalse(
            self.service.create_player(
                {**base, "navigatorId": "bad"}, session
            )["succeeded"]
        )
        self.assertFalse(
            self.service.create_player({**base, "colorIndex": "bad"}, session)[
                "succeeded"
            ]
        )

    def test_positive_progress_count_requires_each_click(self):
        session = self._login_and_create()
        self.states.rows[session["playerId"]]["drafts"]["draft2000028"] = 1
        result = self.service.submit_build_task(
            {"draftId": "draft2000028", "originCoord": [1, 1]}, session
        )
        self.assertEqual(result["building"]["status"], "building")
        self.assertEqual(result["building"]["remainedClickCount"], 2)
        early = self.service.complete_tasks({"buildingIds": [result["buildingId"]]}, session)
        self.assertEqual(early["completeCount"], 0)
        self.assertEqual(self.states.load(session["playerId"])["buildings"][result["buildingId"]]["remainedClickCount"], 2)

        first = self.service.progress_build_task(
            {"buildingId": result["buildingId"]}, session
        )
        self.assertEqual(first["remainedClickCount"], 1)
        second = self.service.progress_build_task(
            {"buildingId": result["buildingId"]}, session
        )
        self.assertEqual(second["remainedClickCount"], 0)

        stored = self.states.load(session["playerId"])["buildings"][result["buildingId"]]
        self.assertEqual(stored["status"], "building")
        completed = self.service.complete_tasks(
            {"buildingIds": [result["buildingId"]]}, session
        )
        self.assertEqual(completed["buildings"][result["buildingId"]]["status"], "none")

    def test_registered_handlers_do_not_require_db_for_anonymous_shape_checks(self):
        registry = Registry()
        self.service.register(registry).register_contract_defaults()

        status, login = registry.dispatch("debug/devLogin", {}, None)
        self.assertEqual(status, 200)
        self.assertFalse(login["succeeded"])

        status, drafts = registry.dispatch("politic/building/getDrafts", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(drafts, {"errorReason": "authentication required"})

        status, avatars = registry.dispatch("deck/getAvatarCharacters", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(avatars, {"errorReason": "authentication required"})

    def test_reproducible_gameplay_smoke_tool(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = gameplay_smoke.main(["--table-dir", str(FIXTURES)])
        self.assertEqual(code, 0)
        self.assertIn("missions={'0': 'C', '1': 'C', '2': 'C', '3': 'C', '4': 'C'}", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
