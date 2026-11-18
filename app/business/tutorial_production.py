"""Settlement of the field lesson and existing fixed-recipe saves."""
from __future__ import annotations

import copy
import math
import secrets
from functools import partial

from app.business.city_production_rules import durability_kind, preview_amount, reward_slot
from app.business.city_production_services import ManualProductionServices
from app.business.player_services import integer
from app.business.production_availability import FIELD_LESSON_HARVESTED, FIELD_LESSON_RECIPE
from app.business.production_modifiers import ProductionModifiers
from app.business.production_inventory import ProductionInventory


class TutorialFieldProduction(ManualProductionServices):
    APPLY_LESSON_POLICY = True
    PRODUCT = FIELD_LESSON_RECIPE
    PRODUCTS = frozenset({PRODUCT})
    PLAN_KEY = "tutorialFieldProductionV1"  # Internal, never projected on the wire.
    RESOURCE_ITEM = "item11_0000301"
    RESOURCE = "food"
    RECIPE_ERROR = "no stub response: only the task 5 ten-second field recipe is enabled"

    def register(self, registry, *, apis=None) -> None:
        api = "politic/task/submitProduceTask"
        registry.register(api, self.service._guard(api, partial(self.call, api, self.start)))

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
                    or slot.item_id not in {self.RESOURCE_ITEM, "item11_0000501"}):
                raise ValueError("no stub response: unsupported tutorial reward slot")
            groups.add(slot.group)
            amounts[slot.item_id] = preview_amount(1, integer(record.get("level"), 1, 10),
                                                  slot.count_min, slot.count_max)
        if set(amounts) != {self.RESOURCE_ITEM, "item11_0000501"}:
            raise ValueError("no stub response: supported resource/experience reward missing")
        return {"reward": amounts, "buildingExp": integer(product.get("buildingExp"))}

    def plans(self, player: dict) -> dict:
        plans = player.get(self.PLAN_KEY, {})
        if not isinstance(plans, dict):
            raise ValueError("no stub response: invalid tutorial production ledger")
        return plans

    def start(self, player: dict, params: dict) -> dict:
        key, record, _ = self.owned(player, params.get("buildingId"))
        if params.get("productId") != self.PRODUCT:
            raise ValueError(self.RECIPE_ERROR)
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

    def active(self, player: dict, key: str) -> tuple[dict, dict, dict, dict]:
        key, record, row = self.owned(player, key)
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
        return record, row, plan, task

    def now(self) -> int:
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("no stub response: invalid production clock")
        return integer(int(value), 0, 9007199254740991)

    def harvest(self, player: dict, keys: list[str], *, point_cost: int = 1) -> dict:
        """All validations precede mutation; caller commits once with construction."""
        if not keys:
            return {}
        if len(keys) != 1:
            raise ValueError("settlement engine requires one building at a time")
        key = self.ids(keys)[0]
        record, _, plan, task = self.active(player, key)
        now = self.now()
        due = integer(task.get("dueTime"), 0, 9007199254740991)
        if now < due:
            raise ValueError("production is not ready for harvest")
        reward = plan.get("reward")
        if not isinstance(reward, dict) or set(reward) != {self.RESOURCE_ITEM, "item11_0000501"}:
            raise ValueError("no stub response: invalid tutorial production reward")
        amount, exp = integer(reward[self.RESOURCE_ITEM], 1), integer(reward["item11_0000501"])
        box = player["resources"][self.RESOURCE]
        if integer(box.get("amount")) + amount > integer(box.get("maxAmount")):
            raise ValueError(f"{self.RESOURCE} capacity is insufficient for harvest")
        integer(integer(player["entity"].get("exp")) + exp)
        building_exp = integer(integer(record.get("exp")) + integer(plan.get("buildingExp")))
        points = player["actionPoints"]["politicPoint"]
        point_cost = integer(point_cost)
        if integer(points.get("point")) < point_cost:
            raise ValueError("insufficient politic points for harvest")
        reward, collaborator = ProductionModifiers(self.service).plan(player, key, reward, seed=plan["generation"])
        ProductionInventory(self.service).grant(player, reward)
        points["point"] -= point_cost
        record.update(status="none", exp=building_exp)
        del player["produce"][key]
        del self.plans(player)[key]
        if self.PRODUCT == FIELD_LESSON_RECIPE:
            player[FIELD_LESSON_HARVESTED] = True
        # No automatic renewal: manual fields return to the recipe selector.
        return {key: {"reward": {k: float(v) for k, v in reward.items()},
                      "building": copy.deepcopy(record), "collaborator": collaborator}}
