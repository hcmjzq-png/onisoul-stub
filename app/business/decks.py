"""Persisted deck wire format; evidence and bootstrap policy: docs/api_schema.md."""
from __future__ import annotations

import copy
import math
from typing import Any

KINDS = ("attack", "defense", "politic", "quest", "strategy", "siege")


def character_id(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("invalid character id")
    if isinstance(value, str) and value.isascii() and value.isdigit():
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and math.isfinite(value) and int(value) == value:
        number = int(value)
    else:
        raise ValueError("invalid character id")
    if not 0 < number <= 2147483647:
        raise ValueError("invalid character id")
    return str(number)


def empty_deck() -> dict[str, dict]:
    return {"ids": {}, "tactics": {}, "equip": {}}


def counts(player: dict, level: dict) -> dict[str, int]:
    bits = int(player.get("unlockBits") or 0)
    return {"attack": max(1, int(level.get("attackDeckCount") or 1)), "defense": 1,
            "politic": 3 if bits & 0x04000000 else 2 if bits & 0x01000000 else 1,
            "quest": 1, "strategy": 2, "siege": 2}


def initialize(player: dict, level: dict, equipment: dict, items: dict) -> dict:
    """Fill absent structures only; never replace a player's saved formation."""
    stored = copy.deepcopy(player.get("decks") or {})
    characters = player.get("characters") or {}
    # Do not persist an empty bootstrap before createPlayer installs its characters.
    if not characters:
        return stored
    by_base = {row["baseId"]: key for key, row in characters.items() if "baseId" in row}
    for kind, count in counts(player, level).items():
        group = stored.setdefault(kind, {})
        for index in range(count):
            if str(index) in group:
                continue
            deck = empty_deck()
            if index == 0 and kind in ("attack", "defense", "quest"):
                for item in equipment.get(kind + "Characters") or []:
                    key = by_base.get((items.get(item) or {}).get("parameterId"))
                    if key and len(deck["ids"]) < 5:
                        # Attack/defense/quest mark their last character post as leader.
                        position = (4, 0, 1, 2, 3)[len(deck["ids"])]
                        deck["ids"][str(position)] = float(key)
            group[str(index)] = deck
    if "avatar" not in stored:
        quest = stored["quest"]["0"]["ids"]
        first = next((v for v in quest.values() if v != "empty"), next(iter(characters)))
        stored["avatar"] = {"id": float(character_id(first)), "grade": 1.0}
    return stored


def validate(value: Any, player: dict, level: dict) -> dict:
    if not isinstance(value, dict) or set(value) != set(KINDS) | {"avatar"}:
        raise ValueError("decks must contain avatar and all six deck groups")
    avatar = value["avatar"]
    if not isinstance(avatar, dict) or set(avatar) != {"id", "grade"}:
        raise ValueError("invalid avatar")
    avatar_id = character_id(avatar["id"])
    if avatar_id not in player["characters"] or type(avatar["grade"]) not in (int, float) or avatar["grade"] != 1:
        raise ValueError("avatar must be an owned character with display grade 1")
    result = {"avatar": {"id": float(avatar_id), "grade": 1.0}}
    for kind, count in counts(player, level).items():
        group = value[kind]
        if not isinstance(group, dict) or set(group) != {str(i) for i in range(count)}:
            raise ValueError(f"invalid {kind} deck indexes")
        result[kind] = {}
        for index, deck in group.items():
            if not isinstance(deck, dict) or set(deck) != {"ids", "equip", "tactics"}:
                raise ValueError(f"invalid {kind} deck")
            clean = empty_deck()
            for field, inventory in (("ids", "characters"), ("equip", "equips"), ("tactics", "tactics")):
                slots = deck[field]
                if not isinstance(slots, dict) or any(k not in {str(i) for i in range(5)} for k in slots):
                    raise ValueError(f"invalid {field} slots")
                seen = set()
                for slot, raw in slots.items():
                    if raw == "empty":
                        clean[field][slot] = "empty"
                        continue
                    key = character_id(raw) if field == "ids" else str(raw)
                    if key not in (player.get(inventory) or {}):
                        raise ValueError(f"{field} contains an unowned card")
                    if field == "ids" and key in seen:
                        raise ValueError("duplicate character within a deck")
                    seen.add(key)
                    clean[field][slot] = float(key) if field == "ids" else key
            result[kind][index] = clean
    return result
