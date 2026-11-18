"""Deliver production items through original item category/parameter mappings."""
from __future__ import annotations

from app.business.city_services import CityServices
from app.business.player_services import integer

RESOURCES = {"item11_0000101": "gold", "item11_0000201": "wood",
             "item11_0000301": "food", "item11_0000401": "iron"}
PLAYER_EXP = "item11_0000501"
SOULS = {"item11_0001101": "purple", "item11_0001201": "red", "item11_0001301": "blue",
         "item11_0001401": "yellow", "item11_0001501": "green", "item11_0001601": "black",
         "item11_0001701": "white"}


class ProductionInventory(CityServices):
    def route(self, code: str) -> tuple[str, str]:
        if code in RESOURCES:
            return "resource", RESOURCES[code]
        if code == PLAYER_EXP:
            return "experience", "exp"
        if code in SOULS:
            return "souls", SOULS[code]
        if not isinstance(code, str) or len(code) < 7 or not code.startswith("item"):
            raise ValueError("no stub response: invalid production item id")
        row = self.table(code[:6]).get(code)
        if not isinstance(row, dict):
            raise ValueError("stub has no assets: production item definition missing")
        category, parameter = row.get("category"), row.get("parameterId")
        if category == "tactics":
            if parameter not in self.table("tactics"):
                raise ValueError("stub has no assets: production tactic definition missing")
            return "tactics", parameter
        if category == "consumable":
            potion = self.table("potion").get(parameter)
            if not isinstance(potion, dict) or potion.get("itemID") != code:
                raise ValueError("stub has no assets: production consumable definition mismatch")
            return "items", code
        if category == "cannonShot":
            if parameter not in self.table("cannon_shot"):
                raise ValueError("stub has no assets: production cannon shot definition missing")
            return "items", code
        raise ValueError("no stub response: production item delivery category is not enabled")

    def grant(self, player: dict, rewards: dict) -> None:
        updates = {}
        for code, value in rewards.items():
            amount = integer(value)
            kind, key = self.route(code)
            if kind == "resource":
                box = player["resources"][key]
                total = integer(integer(box.get("amount")) + amount)
                if amount and total > integer(box.get("maxAmount")):
                    raise ValueError(f"{key} capacity is insufficient for harvest")
            elif kind == "experience":
                total = integer(integer(player["entity"].get("exp")) + amount)
            elif kind == "tactics":
                total = integer(integer(player.get("tactics", {}).get(key, {}).get("amount", 0)) + amount)
            elif kind == "souls":
                total = integer(integer(player.get("souls", {}).get(key, 0)) + amount)
            else:
                total = integer(integer(player.get("items", {}).get(key, 0)) + amount)
            # Aggregate aliased item IDs before mutation, rather than losing a
            # second reward that resolves to the same original inventory key.
            if (kind, key) in updates:
                total = integer(updates[(kind, key)] + amount)
                if kind == "resource" and amount and total > integer(player["resources"][key]["maxAmount"]):
                    raise ValueError(f"{key} capacity is insufficient for harvest")
            updates[(kind, key)] = total
        for (kind, key), total in updates.items():
            if kind == "resource":
                player["resources"][key]["amount"] = total
            elif kind == "experience":
                player["entity"]["exp"] = total
            elif kind == "tactics":
                player.setdefault("tactics", {}).setdefault(key, {})["amount"] = total
            elif kind == "souls":
                player.setdefault("souls", {})[key] = total
            else:
                player.setdefault("items", {})[key] = total
