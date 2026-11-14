"""Behavior regressions backed by original client callbacks and tutorial table rows."""
import copy
import unittest
from unittest.mock import patch

from app.business import decks, mission_validation
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
from tools.gameplay_smoke import MemoryState, MemorySessions
from tools.repair_starter_rosters import candidate, repaired

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "gameplay" / "tables"


class CoreGameplayTest(unittest.TestCase):
    def setUp(self):
        self.states = MemoryState()
        self.sessions = MemorySessions()
        self.service = self.new_service()
        self.session, _ = self.service._issue_login("core-gameplay")
        created = self.service.create_player({"username": "core-gameplay", "countryId": "country01",
                                              "navigatorId": "navi8000101", "colorIndex": "color1"}, self.session)
        self.assertTrue(created["succeeded"])

    def new_service(self):
        return GameplayService(catalog=TableCatalog(FIXTURES, FIXTURES / "table_list.tsv"),
                               load_state=self.states.load, save_state=self.states.save,
                               session_store=self.sessions)

    def saved(self):
        return self.states.load(self.session["playerId"])

    def change(self, number, target):
        return self.service.change_mission_state({"missionIds": [f"po_mission_{number:05d}"],
                                                  "states": [target]}, self.session)

    def deck_value(self):
        result = self.service.get_decks({}, self.session)
        return {key: result[key] for key in (*decks.KINDS, "avatar")}

    def test_inactive_events_and_normal_shop_do_not_fabricate_presence_keys(self):
        registry = self.service.register(Registry()).register_contract_defaults()
        for api in ("common/getEventStatuses", "common/getShopsale"):
            status, body = registry.dispatch(api, {}, self.session)
            self.assertEqual(status, 200)
            self.assertEqual(set(body), {"succeeded", "now"})
            self.assertTrue(body["succeeded"])

    def test_initial_decks_resolve_to_owned_characters_and_original_table(self):
        value = self.deck_value()
        chars = self.service.get_characters({}, self.session)
        self.assertEqual(len(chars), 4)
        for kind in decks.KINDS:
            self.assertIsInstance(value[kind]["0"]["ids"], dict)
            for row in value[kind].values():
                for key in row["ids"].values():
                    self.assertIn(str(int(key)), chars)
        self.assertEqual(set(value["strategy"]), {"0", "1"})
        self.assertEqual(set(value["siege"]), {"0", "1"})
        self.assertEqual(len(value["attack"]["0"]["ids"]), 1)
        self.assertIn("4", value["attack"]["0"]["ids"])
        self.assertEqual(len(value["defense"]["0"]["ids"]), 2)
        self.assertTrue(value["quest"]["0"]["ids"])

    def test_deck_save_survives_service_reload_and_updates_avatar(self):
        value = self.deck_value()
        value["avatar"]["id"] = 2
        value["attack"]["0"]["ids"] = {"0": 1, "4": 2, "2": "empty"}
        self.assertEqual(self.service.set_decks({"decks": value}, self.session), {})
        self.service = self.new_service()
        self.assertEqual(self.deck_value(), value)
        self.assertEqual(set(self.service.get_avatar_characters({}, self.session)), {"2"})
        self.assertEqual(set(self.service.get_select_characters({"ids": [1, 2.0, "2"]}, self.session)), {"1", "2"})

    def test_deck_mutations_validate_atomically(self):
        original = self.deck_value()
        bad_values = []
        for slots in ({"0": 9999}, {"0": 1, "1": 1}, {"-1": 1}, {"5": 1},
                      {"0": True}, {"0": 1.5}, {"0": float("nan")}, {"0": 10 ** 400}, {"0": []}):
            bad = copy.deepcopy(original)
            bad["attack"]["0"]["ids"] = slots
            bad_values.append(bad)
        bad = copy.deepcopy(original)
        bad["quest"]["0"]["equip"] = {"0": "fake-weapon"}
        bad_values.extend([bad, {}, None])
        before = self.saved()
        for value in bad_values:
            with self.subTest(value=value):
                self.assertIn("errorReason", self.service.set_decks({"decks": value}, self.session))
                self.assertEqual(self.saved(), before)

    def test_new_handlers_require_session_and_selected_characters_do_not_leak(self):
        for handler in (self.service.get_characters, self.service.get_select_characters,
                        self.service.get_decks, self.service.set_decks):
            self.assertIn("errorReason", handler({}, None))
        for ids in ([999], [True], [1.5], "1", [None]):
            self.assertIn("errorReason", self.service.get_select_characters({"ids": ids}, self.session))
        self.assertEqual(self.service.get_select_characters({"ids": []}, self.session), {})

    def test_legacy_empty_decks_migrate_once_without_resetting_inventory(self):
        player = self.saved()
        player["decks"] = {}
        player["resources"]["gold"]["amount"] = 123
        self.states.save(player, self.session["playerId"])
        first = self.deck_value()
        self.assertEqual(first, self.deck_value())
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 123)
        self.assertEqual(self.saved()["characters"], player["characters"])

    def test_premature_mission_close_and_prerequisite_bypass_are_rejected(self):
        before = self.saved()
        self.assertFalse(self.change(1, "closed")["succeeded"])
        self.assertFalse(self.change(2, "accepted")["succeeded"])
        self.assertEqual(self.saved(), before)
        self.assertTrue(self.change(1, "accepted")["succeeded"])
        self.assertTrue(self.change(1, "closed")["succeeded"])
        self.assertTrue(self.change(2, "accepted")["succeeded"])
        before = self.saved()
        self.assertFalse(self.change(2, "closed")["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_mission_batches_rollback_and_reject_ambiguous_input(self):
        self.assertTrue(self.change(1, "accepted")["succeeded"])
        before = self.saved()
        for params in (
            {"missionIds": ["po_mission_00001", "missing"], "states": ["closed", "accepted"]},
            {"missionIds": ["po_mission_00001"], "states": []},
            {"missionIds": ["po_mission_00001"] * 2, "states": ["closed"] * 2},
            {"missionIds": ["po_mission_00000"], "states": ["accepted"]},
        ):
            self.assertFalse(self.service.change_mission_state(params, self.session)["succeeded"])
            self.assertEqual(self.saved(), before)

    def test_mission_reward_is_once_only_and_closed_cannot_be_reopened(self):
        self.change(1, "accepted")
        self.change(1, "finished")
        self.service = self.new_service()
        self.assertTrue(self.change(1, "closed")["succeeded"])
        before = self.saved()["resources"]
        self.assertEqual(self.change(1, "closed")["reward"], {})
        self.assertFalse(self.change(1, "accepted")["succeeded"])
        self.assertEqual(self.saved()["resources"], before)

    def test_unknown_completion_predicate_never_grants_reward(self):
        rows = copy.deepcopy(self.service.missions.rows())
        rows["po_mission_00001"]["conditionTypes1"] = ["unverified"]
        with patch.object(self.service.missions, "rows", return_value=rows):
            self.assertTrue(self.change(1, "accepted")["succeeded"])
            result = self.change(1, "closed")
        self.assertFalse(result["succeeded"])
        self.assertIn("unsupported", result["errorReason"])
        self.assertEqual(self.saved()["resources"]["gold"]["amount"], 0)

    def test_castle_condition_ignores_unfinished_and_other_map_buildings(self):
        player = self.saved()
        player["buildings"]["1"] = {"buildingTypeId": "building200_002_01_01_1_1",
                                      "status": "building", "deployedMapKey": "map001"}
        rows = self.service.missions.rows()
        table = self.service._table("building")
        self.assertFalse(mission_validation.completed(player, rows, table, "po_mission_00002"))
        player["buildings"]["1"].update(status="none", deployedMapKey="map002")
        self.assertFalse(mission_validation.completed(player, rows, table, "po_mission_00002"))
        player["buildings"]["1"]["deployedMapKey"] = "map001"
        self.assertTrue(mission_validation.completed(player, rows, table, "po_mission_00002"))

    def test_mission_four_accepts_each_country_variant(self):
        rows = self.service.missions.rows()
        for target in rows["po_mission_00004"]["conditionTargets1"]:
            player = self.saved()
            player["buildings"]["1"] = {"buildingTypeId": target, "status": "none"}
            self.assertTrue(mission_validation.completed(player, rows, self.service._table("building"), "po_mission_00004"))

    def test_legacy_finished_self_acceptance_can_close_but_build_check_is_not_bypassed(self):
        player = self.saved()
        player["missions"].update({"1": "F"})
        self.states.save(player, self.session["playerId"])
        self.assertTrue(self.change(1, "closed")["succeeded"])
        player = self.saved()
        player["missions"]["2"] = "F"
        self.states.save(player, self.session["playerId"])
        self.assertFalse(self.change(2, "closed")["succeeded"])

    def test_missing_reward_table_does_not_close_mission_or_consume_receipt(self):
        self.change(1, "accepted")
        before = self.saved()
        original = self.service._table
        with patch.object(self.service, "_table", side_effect=lambda name: {} if name == "reward01_politic" else original(name)):
            self.assertFalse(self.change(1, "closed")["succeeded"])
        self.assertEqual(self.saved(), before)

    def test_starter_roster_repair_is_narrow_and_idempotent(self):
        player = self.saved()
        player.update(characters={}, decks={})
        player["counters"]["characterCount"] = 0
        player["resources"]["gold"]["amount"] = 123
        original = copy.deepcopy(player)
        result = repaired(self.service, player, self.session["playerId"])
        self.assertEqual(len(result["characters"]), 4)
        self.assertTrue(result["decks"]["attack"]["0"]["ids"])
        for key in original.keys() - {"characters", "decks", "counters"}:
            self.assertEqual(result[key], original[key])
        self.assertEqual(player, original)
        self.assertIsNone(repaired(self.service, result, self.session["playerId"]))
        for field, value in (("missionRewards", {"x": {}}), ("missions", {"0": "C", "1": "C"}),
                             ("buildings", {"1": {}}), ("characters", {"1": {}})):
            changed = copy.deepcopy(original)
            changed[field] = value
            self.assertFalse(candidate(changed))


if __name__ == "__main__":
    unittest.main()
