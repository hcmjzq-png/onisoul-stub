"""Manual/single production using original quantities and compatible settlement.

Original tables determine recipe membership, costs, time and experience.
Quantities use the PC interpolation; reward selection and modifiers follow
local policies. Finite durability decreases on successful harvest. The automatic
subclass renews timers, and all item categories used by city recipes are routed
through the original inventory mappings.
"""
from __future__ import annotations

import copy
import math
import secrets
from typing import Any

from app.business.city_production_rules import durability_kind
from app.business.city_production_services import ManualProductionServices
from app.business.player_services import integer
from app.business.production_inventory import ProductionInventory
from app.business.production_rewards import resolve_rewards
from app.business.production_modifiers import ProductionModifiers

RESOURCE_ITEMS = {
    "item11_0000101": "gold", "item11_0000201": "wood",
    "item11_0000301": "food", "item11_0000401": "iron",
}
PLAYER_EXP = "item11_0000501"
ALLOWED_ITEMS = frozenset({*RESOURCE_ITEMS, PLAYER_EXP})


class FixedResourceProduction(ManualProductionServices):
    APPLY_LESSON_POLICY = True
    PLAN_KEY = "fixedResourceProductionV1"  # Internal persistence, never wire data.
    POLICY = "base-preview-v1"

    def validate_recipe(self, record: dict, row: dict, code: Any, defines: dict) -> None:
        if (row.get("produceType") not in ("manual", "single") or row.get("map0") is not True
                or durability_kind(record.get("durability"), defines) == "dead"):
            raise ValueError("no stub response: living manual/single resource building required")
        if (not isinstance(row.get("products"), list) or not isinstance(code, str)
                or code not in row["products"]):
            raise ValueError("no stub response: recipe does not belong to this building")

    def reward_plan(self, record: dict, row: dict, code: str, *, seed: str = "catalog") -> dict:
        self.validate_recipe(record, row, code, self.table("defines"))
        product = self.table("product").get(code)
        if not isinstance(product, dict):
            raise ValueError("no stub response: referenced product row missing")
        return resolve_rewards(self.service, record, row, product, seed=seed)

    def plans(self, player: dict) -> dict:
        plans = player.get(self.PLAN_KEY, {})
        if not isinstance(plans, dict):
            raise ValueError("no stub response: invalid resource production ledger")
        return plans

    def submit(self, player: dict, params: dict, *, bulk: bool = False) -> dict:
        if bulk:
            raise ValueError("no stub response: bulk production start is not enabled")
        return self.start(player, params)

    def start(self, player: dict, params: dict) -> dict:
        self.no_modifiers(player)
        key, record, row = self.owned(player, params.get("buildingId"))
        if key in self.plans(player):
            raise ValueError("no stub response: production ledger already exists; reload the map")
        code = params.get("productId")
        plan = self.reward_plan(record, row, code, seed=secrets.token_hex(16))
        result = super().submit(player, params)
        task = copy.deepcopy(player["produce"][key])
        record = player["buildings"][key]
        self.store_plan(player, key, record, row, task, plan)
        return {**result, **task, "remainedClickCount": 0, "producings": {key: task}}

    def store_plan(self, player: dict, key: str, record: dict, row: dict, task: dict, plan: dict) -> None:
        player.setdefault(self.PLAN_KEY, {})[key] = {
            **plan, **task, "policy": self.POLICY, "generation": secrets.token_hex(16),
            "buildingTypeId": record["buildingTypeId"], "buildingGrade": row["grade"],
            "buildingLevel": record["level"], "buildingDurability": record["durability"],
        }

    def active(self, player: dict, key: str) -> tuple[dict, dict, dict, dict]:
        key, record, row = self.owned(player, key)
        plans = self.plans(player)
        plan, task = plans.get(key), player["produce"].get(key)
        if not isinstance(plan, dict) or not isinstance(task, dict):
            raise ValueError("no stub response: production settlement plan missing")
        self.validate_recipe(record, row, task.get("productId"), self.table("defines"))
        if (record.get("status") != "producing" or plan.get("policy") != self.POLICY
                or not isinstance(plan.get("generation"), str) or not plan["generation"]
                or any(plan.get(field) != task.get(field) for field in ("productId", "createdTime", "dueTime"))
                or plan.get("buildingTypeId") != record.get("buildingTypeId")
                or plan.get("buildingLevel") != record.get("level")
                or plan.get("buildingGrade") != row.get("grade")
                or plan.get("buildingDurability", self.table("defines")["infinite_building_durability"]["value"])
                    != record.get("durability")):
            raise ValueError("no stub response: production settlement state mismatch")
        return record, row, plan, task

    def now(self) -> int:
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("no stub response: invalid production clock")
        return integer(int(value), 0, 9007199254740991)

    def harvest(self, player: dict, keys: list[str], *, point_cost: int = 1) -> dict:
        if len(keys) != 1:
            raise ValueError("no stub response: settlement engine requires one building at a time")
        self.no_modifiers(player)
        key = self.ids(keys)[0]
        record, row, plan, task = self.active(player, key)
        now = self.now()
        if now < integer(task.get("dueTime"), 0, 9007199254740991):
            raise ValueError("production is not ready for harvest")
        reward = plan.get("reward")
        if not isinstance(reward, dict) or not reward and plan.get("emptyAllowed") is not True:
            raise ValueError("no stub response: invalid resource production reward")
        reward = {code: integer(amount) for code, amount in reward.items()}
        reward, collaborator = ProductionModifiers(self.service).plan(player, key, reward, seed=plan["generation"])
        building_exp = integer(integer(record.get("exp")) + integer(plan.get("buildingExp")))
        points = player["actionPoints"]["politicPoint"]
        point_cost = integer(point_cost)
        if integer(points.get("point")) < point_cost:
            raise ValueError("insufficient politic points for harvest")
        ProductionInventory(self.service).grant(player, reward)
        for other_key, updated in collaborator.items():
            player["buildings"][other_key]["exp"] = updated["exp"]
        points["point"] -= point_cost
        if durability_kind(record["durability"], self.table("defines")) == "finite":
            record["durability"] -= 1
        record.update(status="dead" if record["durability"] <= 0 else "none", exp=building_exp)
        del player["produce"][key]
        del self.plans(player)[key]
        if record["durability"] <= 0:
            del player["buildings"][key]
            player["occupiedGrids"] = {coord: value for coord, value in player["occupiedGrids"].items()
                                       if str(value) != key}
            player["counters"]["buildingCount"] = len(player["buildings"])
        return {key: {"reward": {code: float(amount) for code, amount in reward.items()},
                      "building": copy.deepcopy(record), "collaborator": collaborator}}
