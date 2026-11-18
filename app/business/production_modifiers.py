"""Client skill eligibility/priority and authorized compatible production bonuses.

Exact percentages are read from original skill messages. Local rules define
orthogonal road contact, additive bonuses, intelligence scaling and house links.
Those rules are recorded separately from the original client/table evidence.
"""
from __future__ import annotations

import math
import random
import re

from app.business.city_services import CityServices
from app.business.decks import character_id
from app.business.player_services import integer
from app.business.production_inventory import RESOURCES, PLAYER_EXP, ProductionInventory

HOUSES = {"farmHouse", "technicalHouse", "merchantHouse", "swordHouse", "bowHouse", "horseHouse"}


def validate_formation(player: dict) -> None:
    decks = (player.get("decks") or {}).get("politic", {})
    if not isinstance(decks, dict):
        raise ValueError("no stub response: invalid politic deck")
    for deck in decks.values():
        if not isinstance(deck, dict):
            raise ValueError("no stub response: invalid politic deck")
        for field, inventory in (("ids", "characters"), ("equip", "equips"), ("tactics", "tactics")):
            values = deck.get(field, {})
            if not isinstance(values, dict):
                raise ValueError("no stub response: invalid politic deck slots")
            for slot, value in values.items():
                if slot not in {str(i) for i in range(5)}:
                    raise ValueError("no stub response: invalid politic deck position")
                if value == "empty":
                    continue
                key = character_id(value) if field == "ids" else str(value)
                if key not in player.get(inventory, {}):
                    raise ValueError("no stub response: politic deck references an unowned item")


class ProductionModifiers(CityServices):
    @staticmethod
    def cells(record: dict, row: dict) -> set[tuple[int, int]]:
        size = row.get("size")
        if not isinstance(size, list) or len(size) != 2:
            raise ValueError("stub has no assets: building size missing")
        x, y = integer(record.get("x")), integer(record.get("y"))
        return {(a, b) for a in range(x - integer(size[0], 1) + 1, x + 1)
                for b in range(y - integer(size[1], 1) + 1, y + 1)}

    @staticmethod
    def neighbors(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
        return {(x + dx, y + dy) for x, y in cells for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cells

    def skills(self, player: dict) -> tuple[list[dict], int]:
        validate_formation(player)
        deck = (player.get("decks") or {}).get("politic", {}).get("0", {})
        active, intelligence = [], 0
        for position, value in sorted(deck.get("ids", {}).items()):
            if value == "empty":
                continue
            card = player["characters"][character_id(value)]
            intelligence += integer(card.get("int", 0)) + integer(card.get("intAdd", 0))
            skills = card.get("skills") or {}
            if not isinstance(skills, dict):
                raise ValueError("no stub response: invalid saved character skills")
            for skill in skills.values():
                if not isinstance(skill, dict) or skill.get("id") in (None, "", "empty"):
                    continue
                if integer(skill.get("learning", 1), 0) > integer(card.get("grade"), 1):
                    continue
                row = self.table("skill").get(skill["id"])
                if not isinstance(row, dict):
                    raise ValueError("stub has no assets: assigned skill definition missing")
                post = ("1st", "2nd", "3rd", "4th", "5th")[int(position)]
                if row.get("type") != "politic" or post not in str(row.get("condition2B", "")).split(","):
                    continue
                if not row.get("multiple"):
                    if any(v["id"] == row["id"] or v.get("group") == row.get("group")
                           and v.get("priorityInGroup", 0) > row.get("priorityInGroup", 0) for v in active):
                        continue
                    active = [v for v in active if v.get("group") != row.get("group")]
                active.append(row)
        for value in deck.get("equip", {}).values():
            if value != "empty":
                equip = player["equips"][str(value)]
                intelligence += integer(equip.get("int", 0)) + integer(equip.get("intAdd", 0))
        return active, intelligence

    def plan(self, player: dict, key: str, reward: dict, *, seed: str) -> tuple[dict, dict]:
        key, record, row = self.owned(player, key)
        footprint = self.cells(record, row)
        border, roads, houses = self.neighbors(footprint), set(), {}
        buildings = self.table("building")
        for other_key, other in player["buildings"].items():
            if other_key == key or other.get("deployedMapKey") != record["deployedMapKey"] or other.get("status") in ("building", "dead"):
                continue
            kind = buildings.get(other.get("buildingTypeId"), {})
            if kind.get("category") == "road":
                roads.update(self.cells(other, kind))
            elif kind.get("category") in HOUSES:
                houses[other_key] = (other, kind)
        active, intelligence = self.skills(player)
        boosts = {v: 0.0 for v in RESOURCES.values()}
        road_increase, book_chances, book_range = 0.0, [], []
        if active:
            messages = self.table("skillMessage.json")
            for skill in active:
                text = (messages.get(skill.get("desc")) or {}).get("tw", "")
                for label, percent in re.findall(r"「(金钱|粮食|食粮|木材|铁矿)」的生产量上升([0-9.]+)%", text):
                    boosts[{"金钱": "gold", "粮食": "food", "食粮": "food", "木材": "wood", "铁矿": "iron"}[label]] += float(percent)
                for percent in re.findall(r"「道路」的影响上升([0-9.]+)%", text):
                    road_increase += float(percent)
                for match in re.finditer(r"(?:追加生产([0-9]+)本兵法书之机率上升|兵法书追加生产([0-9]+)册的机率上升)([0-9.]+)%", text):
                    book_chances.append((int(match.group(1) or match.group(2)), float(match.group(3))))
                match = re.search(r"城以外的建筑物生产之兵法书追加生产([0-9]+)～([0-9]+)册", text)
                if match and row.get("category") != "castle":
                    book_range.append((int(match.group(1)), int(match.group(2))))
        road_bonus = 20 * (1 + road_increase / 100) if border & roads else 0.0
        collaborator, house_bonus = {}, 0.0
        if row.get("category") == "castle":
            touched = set(border & roads)
            while True:
                expanded = touched | (self.neighbors(touched) & roads)
                if expanded == touched:
                    break
                touched = expanded
            for other_key, (other, kind) in houses.items():
                cells = self.cells(other, kind)
                if cells & border or self.neighbors(cells) & touched:
                    house_bonus += integer(other.get("level"), 1)  # Compatible 1% per linked house level.
                    collaborator[other_key] = {"exp": integer(integer(other.get("exp")) +
                        integer(self.table("product")[player["produce"][key]["productId"]].get("buildingExp")))}
        output, rng = {}, random.Random(seed + ":modifiers")
        inventory = ProductionInventory(self.service)
        for code, amount in reward.items():
            kind, target = inventory.route(code)
            if kind == "resource":
                percent = road_bonus + boosts[target] + intelligence / 1000 + house_bonus
                amount = integer(math.floor(amount * (1 + percent / 100)))
            elif code == PLAYER_EXP:
                amount = integer(math.floor(amount * (1 + road_bonus / 100)))
            elif kind == "tactics":
                amount = integer(math.floor(amount * (1 + (road_bonus + house_bonus) / 100)))
                amount += sum(n for n, chance in book_chances if rng.random() * 100 < min(100, chance))
                amount += sum(rng.randint(lo, hi) for lo, hi in book_range)
                amount = integer(amount)
            output[code] = amount
        return output, collaborator
