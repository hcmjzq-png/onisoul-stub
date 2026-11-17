"""Task 5's G1 field loop; table-driven, explicitly bounded compatibility policy.

Wire shapes come from the original manual-production callbacks. Settlement uses
the original menu quantity interpolation and product.buildingExp, as a local
compatibility policy, not a recovered original-server formula. Road/skill
modifiers, other recipes, automatic renewal and finite durability stay closed.
"""
from __future__ import annotations

import copy
import math
import secrets
from functools import partial

from app.business.city_production_rules import durability_kind, preview_amount, reward_slot
from app.business.city_production_services import ManualProductionServices
from app.business.player_services import integer
from app.business.mission_validation import state_of


class TutorialFieldProduction(ManualProductionServices):
    PRODUCT = "product060_023_01_01_1_1"
    PRODUCTS = frozenset({PRODUCT})
    PLAN_KEY = "tutorialFieldProductionV1"  # Internal, never projected on the wire.

    def register(self, registry, *, apis=None) -> None:
        api = "politic/task/submitProduceTask"
        registry.register(api, self.service._guard(api, partial(self.call, api, self.start)))

    def eligible(self, player: dict) -> None:
        rows = self.service.missions.rows()
        if (state_of(player, rows, "po_mission_00004") != "closed"
                or state_of(player, rows, "po_mission_00005") not in ("accepted", "finished", "closed")):
            raise ValueError("task 5 must be accepted before tutorial production")
        self.no_modifiers(player)
        # Road adjacency/stacking are not established. Refuse this bounded mode
        # if a placed road exists, rather than silently omit an unknown bonus.
        buildings = self.table("building")
        for record in player["buildings"].values():
            if record.get("deployedMapKey") != "map001":
                continue
            row = buildings.get(record.get("buildingTypeId"))
            if not isinstance(row, dict):
                raise ValueError("no stub response: referenced building row missing")
            if row.get("connectChipType") == "road" or row.get("category") == "road":
                raise ValueError("no stub response: tutorial production with road bonuses is unsupported")

    def reward_plan(self, record: dict) -> dict:
        product = self.table("product").get(self.PRODUCT)
        if not isinstance(product, dict):
            raise ValueError("no stub response: tutorial product row missing")
        reward = self.table("reward01_politic").get(product.get("rewardId"))
        if not isinstance(reward, dict):
            raise ValueError("no stub response: tutorial reward row missing")
        amounts, groups = {}, set()
        for index in range(1, 11):
            slot = reward_slot(reward, index)
            if slot is None:
                continue
            if (slot.ratio_min != 1 or slot.ratio_max != 1 or slot.group in groups
                    or slot.item_id not in {"item11_0000301", "item11_0000501"}):
                raise ValueError("no stub response: unsupported tutorial reward slot")
            groups.add(slot.group)
            amounts[slot.item_id] = preview_amount(1, integer(record.get("level"), 1, 10),
                                                  slot.count_min, slot.count_max)
        if set(amounts) != {"item11_0000301", "item11_0000501"}:
            raise ValueError("no stub response: tutorial food/experience reward missing")
        return {"reward": amounts, "buildingExp": integer(product.get("buildingExp"))}

    def plans(self, player: dict) -> dict:
        plans = player.get(self.PLAN_KEY, {})
        if not isinstance(plans, dict):
            raise ValueError("no stub response: invalid tutorial production ledger")
        return plans

    def start(self, player: dict, params: dict) -> dict:
        self.eligible(player)
        key, record, _ = self.owned(player, params.get("buildingId"))
        if params.get("productId") != self.PRODUCT:
            raise ValueError("no stub response: only the task 5 ten-second field recipe is enabled")
        plans = self.plans(player)
        if key in plans:
            raise ValueError("no stub response: production already exists; reload the map")
        plan = self.reward_plan(record)
        result = super().submit(player, params)
        task = copy.deepcopy(player["produce"][key])
        player.setdefault(self.PLAN_KEY, {})[key] = {
            **plan, **task, "generation": secrets.token_hex(16),
            "buildingLevel": record["level"],
        }
        # Legacy recovery supplied these root fields as well as the task map;
        # updateTask consumes dueTime/now, and map reload consumes producings.
        return {**result, **task, "remainedClickCount": 0, "producings": {key: task}}

    def harvest(self, player: dict, keys: list[str]) -> dict:
        """All validations precede mutation; caller commits once with construction."""
        if not keys:
            return {}
        if len(keys) != 1:
            raise ValueError("no stub response: bulk production harvest is not enabled")
        self.eligible(player)
        key, record, _ = self.owned(player, keys[0])
        plans = self.plans(player)
        plan, task = plans.get(key), player["produce"].get(key)
        if not isinstance(plan, dict) or not isinstance(task, dict):
            raise ValueError("no stub response: production settlement plan missing")
        if (record.get("buildingTypeId") != self.FIELD or record.get("status") != "producing"
                or task.get("productId") != self.PRODUCT
                or not isinstance(plan.get("generation"), str) or not plan["generation"]
                or any(plan.get(field) != task.get(field) for field in ("productId", "createdTime", "dueTime"))
                or record.get("level") != plan.get("buildingLevel")):
            raise ValueError("no stub response: production settlement state mismatch")
        if durability_kind(record.get("durability"), self.table("defines")) != "infinite":
            raise ValueError("no stub response: finite durability harvest is unsupported")
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("no stub response: invalid production clock")
        now = integer(int(value), 0, 9007199254740991)
        due = integer(task.get("dueTime"), 0, 9007199254740991)
        if now < due:
            raise ValueError("production is not ready for harvest")
        reward = plan.get("reward")
        if not isinstance(reward, dict) or set(reward) != {"item11_0000301", "item11_0000501"}:
            raise ValueError("no stub response: invalid tutorial production reward")
        food, exp = integer(reward["item11_0000301"], 1), integer(reward["item11_0000501"])
        food_box = player["resources"]["food"]
        if integer(food_box.get("amount")) + food > integer(food_box.get("maxAmount")):
            raise ValueError("food capacity is insufficient for harvest")
        integer(integer(player["entity"].get("exp")) + exp)
        building_exp = integer(integer(record.get("exp")) + integer(plan.get("buildingExp")))
        points = player["actionPoints"]["politicPoint"]
        if integer(points.get("point")) < 1:
            raise ValueError("insufficient politic points for harvest")
        self.service._grant_items(player, reward)
        points["point"] -= 1
        record.update(status="none", exp=building_exp)
        del player["produce"][key]
        del plans[key]
        # No automatic renewal: manual fields return to the recipe selector.
        return {key: {"reward": {k: float(v) for k, v in reward.items()},
                      "building": copy.deepcopy(record), "collaborator": {}}}
