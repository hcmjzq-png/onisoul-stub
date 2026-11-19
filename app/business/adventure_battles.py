"""Prepare owned quest encounters and settle the isolated tutorial calculation.

The first-turn QA policy comes from the supplied offline calculation. It is
not a recovered original server rule or a client battle feed. No battle/*
route is registered here.
"""
from __future__ import annotations

import copy
from collections import defaultdict
import hashlib
import secrets

from app.business.adventure_events import AdventureEvents, TUTORIAL_BATTLE_POLICY
from app.business.adventure_services import mapping
from app.business.decks import character_id
from app.business.player_services import integer
from app.business.production_inventory import ProductionInventory


FACTION_BONUS = "effect_00001_01"
SKILL_EXP = "item11_0000601"


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

    def settle_tutorial_win(self, player: dict, params: dict) -> dict:
        """Commit through AdventureEvents.call only in an isolated server fixture."""
        information = mapping(params.get("battleInformation"))
        deck = mapping(information.get("deckIndex"))
        if (information.get("battleType") != "QUEST_BATTLE" or information.get("questType") != "story"
                or integer(information.get("encountId"), 1) != 5
                or set(deck) != {"attacker", "defender"}
                or any(integer(value) != 0 for value in deck.values())):
            raise ValueError("no stub response: request is outside the tutorial settlement")
        life = self.lifecycle(player)
        event = life["events"].get("5")
        if event and event.get("status") == "resolved":
            return copy.deepcopy(event["battle"])

        inputs = self.prepare_quest_battle(player, params)
        encounter = inputs["encounter"]
        if (encounter.get("monsterId") != "q_mons_0000_01" or encounter["monster"]["maxHp"] != 1000
                or encounter.get("lossRewardId") != "none" or encounter.get("overKillRewardId") != "none"):
            raise ValueError("no stub response: unsupported tutorial opponent")
        if encounter["winRewardId"] != "quest_1_0000_06_0001":
            raise ValueError("no stub response: unexpected tutorial reward table")

        country = mapping(self.table("country_setting").get(player["entity"]["country"]))
        faction = country["attribute"]
        bonus = mapping(self.table("commonEffect").get(FACTION_BONUS))
        required = {
            "activateRatio": 100, "timing": "battle", "condition1A": "self",
            "condition1B": "playerAttribute", "condition2A": "self", "condition2B": "characterAttribute",
            "sign": "equal", "effect1Target": "self", "effect1Action": "paramUpRatio",
            "effect1ValueA": "attack", "effect1ValueB": 25,
        }
        if any(bonus.get(field) != value for field, value in required.items()):
            raise ValueError("no stub response: tutorial faction bonus does not match the supplied calculation")
        damage, hp = [], encounter["monster"]["maxHp"]
        definitions = self.table("character")
        for row in inputs["formation"]:
            fighter = row["character"]
            definition = mapping(definitions.get(fighter["baseId"]))
            if (fighter.get("skills") or fighter.get("grade") != 1 or fighter.get("level") != 1
                    or any(fighter[stat] != definition.get(stat) or fighter.get(stat + "Add") != 0
                           for stat in ("atk", "def", "int"))):
                raise ValueError("no stub response: only unmodified grade-one fighters are supported")
            attack = integer(fighter["atk"])
            amount = attack * 125 // 100 if definition["attribute"] == faction else attack
            hp -= amount
            damage.append({"position": row["position"], "characterId": row["characterId"],
                           "attack": attack, "damage": amount, "remainingHp": hp})
            if hp <= -encounter["monster"]["maxHp"]:
                break
        if hp > 0:
            raise ValueError("no stub response: counterattacks and later turns are unavailable in the QA policy")

        seed = secrets.token_hex(16)
        reward = self.tutorial_battle_reward(encounter["winRewardId"], seed)
        staged = copy.deepcopy(player)
        # In this bounded case no fighter has skills eligible for the skill EXP
        # entry. Keep it in the receipt and do not store it as an inventory item.
        ProductionInventory(self.service).grant(staged, {item: count for item, count in reward.items()
                                                        if item != SKILL_EXP})
        receipt = {"policy": TUTORIAL_BATTLE_POLICY, "encountId": 5, "originOperationId": event["operationId"],
                   "winner": "attacker", "seed": seed, "damage": damage, "reward": reward,
                   "skillExperienceApplied": 0}
        target = staged["adventureV1"]["storyLifecycle"]["events"]["5"]
        target.update(status="resolved", battle=receipt)
        player.clear()
        player.update(staged)
        return copy.deepcopy(receipt)

    def tutorial_battle_reward(self, reward_id: str, seed: str) -> dict[str, int]:
        row = mapping(self.table("quest_1_0000_reward").get(reward_id))
        groups = defaultdict(list)
        for index in range(1, 11):
            item, group = row[f"itemId{index}"], row[f"group{index}"]
            if not item:
                if group:
                    raise ValueError("no stub response: empty tutorial reward slot has a group")
                continue
            weight, count = integer(row[f"ratio{index}min"], 1), integer(row[f"count{index}min"], 1)
            if (not group or item not in {"item11_0000501", SKILL_EXP, "item11_0001101"}
                    or weight != row[f"ratio{index}max"] or count != row[f"count{index}max"]):
                raise ValueError("no stub response: unverified tutorial reward row")
            groups[group].append((item, weight, count))
        if set(groups) != {"A", "B", "C"}:
            raise ValueError("no stub response: incomplete tutorial reward groups")
        reward = {}
        for group, entries in sorted(groups.items()):
            key = f"{TUTORIAL_BATTLE_POLICY}\0{seed}\0{reward_id}\0{group}".encode()
            ticket = int.from_bytes(hashlib.sha256(key).digest(), "big")
            ticket %= sum(weight for _, weight, _ in entries)
            for item, weight, count in entries:
                if ticket < weight:
                    reward[item] = reward.get(item, 0) + count
                    break
                ticket -= weight
        return reward
