"""Stored-building evolution using original families and material tables."""
from __future__ import annotations

import copy

from app.business.city_services import CityServices
from app.business.player_services import integer
from app.business.shop_availability import remember_shop_unlocks


class BuildingEvolution(CityServices):
    def maximum(self, row: dict, record: dict, *, wildcard: bool = False) -> bool:
        grade, level = integer(row.get("grade"), 1), integer(record.get("level"), 1)
        step = self.table("building_level").get(f"{row.get('levelUpTypeId')}{grade * 1000 + level}")
        # Original getNeedExp returns zero for missing rows. Only fabric items
        # may use that rule; a normal building needs its actual maximum row.
        return (wildcard and row.get("category") == "fabric" and step is None
                or isinstance(step, dict) and integer(step.get("needExp")) == 0)

    def evolve(self, player: dict, params: dict) -> dict:
        first, left, source = self.owned(player, params.get("first"), stored=True)
        second, right, material = self.owned(player, params.get("second"), stored=True)
        if first == second:
            raise ValueError("building evolution requires two distinct instances")
        self.idle(player, first, left)
        self.idle(player, second, right)
        if source.get("category") == "fabric" or not self.maximum(source, left):
            raise ValueError("source building must be at its maximum level")
        grade = integer(source.get("grade"), 1)
        if (material.get("grade") != grade
                or material.get("id") != source.get("id") and material.get("category") != "fabric"
                or not self.maximum(material, right, wildcard=True)):
            raise ValueError("evolution needs a maximum-level identical building or same-grade fabric")
        choices = [(key, row) for key, row in self.table("building").items()
                   if row.get("itemId") == source.get("itemId") and row.get("grade") == grade + 1]
        if len(choices) != 1:
            raise ValueError("no stub response: unique next building grade is unavailable")
        target_id, target = choices[0]
        extra = self.table("building_evolutions").get(left["buildingTypeId"])
        charges, potion_items = {}, {}
        if extra is not None:
            kinds, amounts = extra.get("fabrics"), extra.get("amount")
            if (not isinstance(kinds, list) or not isinstance(amounts, list) or len(kinds) != len(amounts)
                    or len(set(kinds)) != len(kinds)):
                raise ValueError("stub has no assets: inconsistent building evolution materials")
            for code, amount in zip(kinds, amounts):
                potion = self.table("potion").get(code)
                if not isinstance(potion, dict) or not isinstance(potion.get("itemID"), str):
                    raise ValueError("stub has no assets: building evolution potion missing")
                item, amount = potion["itemID"], integer(amount, 1)
                balance = integer(player["items"].get(item, 0)) - amount
                if balance < 0:
                    raise ValueError("insufficient building evolution materials")
                charges[item] = charges.get(item, 0) + amount
                potion_items[code] = item
        for item, amount in charges.items():
            if integer(player["items"].get(item, 0)) < amount:
                raise ValueError("insufficient building evolution materials")
        number = integer(player["counters"].get("nextBuildingId"), 1)
        if str(number) in player["buildings"]:
            raise ValueError("no stub response: building instance counter requires repair")
        result = {**left, "instanceId": number, "buildingTypeId": target_id, "level": 1, "exp": 0,
                  "status": "waiting", "durability": integer(target.get("durability"), 1),
                  "deployedMapKey": "none", "remainedClickCount": 0}
        for item, amount in charges.items():
            player["items"][item] -= amount
        del player["buildings"][first]
        del player["buildings"][second]
        player["buildings"][str(number)] = result
        player["counters"].update(nextBuildingId=number + 1, buildingCount=len(player["buildings"]))
        remember_shop_unlocks(player, {target_id: target}, [result])
        return {"buildingId": float(number), "building": copy.deepcopy(result),
                "buildingCount": float(len(player["buildings"])),
                "potions": {code: {"amount": float(player["items"][item])} for code, item in potion_items.items()}}
