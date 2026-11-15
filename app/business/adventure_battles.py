"""Prepare owned quest encounters for a future authoritative battle resolver.

This is a read-only INTERNAL input snapshot. It is not a battle response, replay,
victory, kill event, or damage formula. No battle/* route is registered here.
"""
from __future__ import annotations

import copy

from app.business.adventure_events import AdventureEvents
from app.business.adventure_services import mapping
from app.business.decks import character_id
from app.business.player_services import integer


class AdventureBattles(AdventureEvents):
    def prepare_quest_battle(self, player: dict, params: dict) -> dict:
        """Call under the same player transaction as the eventual resolver/save."""
        information = mapping(params.get("battleInformation"))
        if information.get("battleType") != "QUEST_BATTLE" or information.get("questType") != "story":
            raise ValueError("no stub response: unsupported battle type")
        encount_id = integer(information.get("encountId"), 1)
        index = mapping(information.get("deckIndex"))
        if (set(index) != {"attacker", "defender"}
                or any(integer(index[key]) != 0 for key in index)):
            raise ValueError("no stub response: only quest deck zero is supported")
        life = self.lifecycle(player)
        matches = [event for event in life["events"].values()
                   if isinstance(event.get("encounter"), dict)
                   and event["encounter"].get("encountId") == encount_id]
        if len(matches) != 1 or matches[0]["status"] != "pending":
            raise ValueError("no stub response: no owned pending quest encounter")
        event = matches[0]
        self.encounters(player, {})  # validate the saved position against this encounter
        deck = mapping(mapping(mapping(player.get("decks")).get("quest")).get("0"))
        ids = mapping(deck.get("ids"))
        if any(key not in {str(i) for i in range(5)} for key in ids):
            raise ValueError("no stub response: invalid quest formation position")
        ordered, used = [], set()
        owned = mapping(player.get("characters"))
        for position in range(5):
            value = ids.get(str(position), "empty")
            if value == "empty":
                continue
            instance = character_id(value)
            if instance in used or instance not in owned:
                raise ValueError("no stub response: invalid quest character ownership")
            used.add(instance)
            character = mapping(owned[instance])
            for stat in ("atk", "def", "int"):
                integer(character.get(stat))
            mapping(character.get("skills"))
            ordered.append({"position": position, "characterId": instance,
                            "character": copy.deepcopy(character)})
        if not ordered:
            raise ValueError("no stub response: empty quest formation")
        if any(value != "empty" for field in ("tactics", "equip")
               for value in mapping(deck.get(field)).values()):
            raise ValueError("no stub response: tactic/equipment battle modifiers unresolved")
        # Formation order is not a claim about initiative or skill timing. Never
        # use the preview sum or recommended preAtk/preDef/preInt as damage.
        return {"ownerId": mapping(player.get("entity"))["playerId"],
                "originOperationId": event["operationId"],
                "encounter": copy.deepcopy(event["encounter"]),
                "formation": ordered, "sourceRevision": player.get("_revision")}
