"""Free automatic timers, harvest renewal and finite-building exhaustion.

Auto buildings have one original recipe, no start costs and no start PP. Rewards
are resolved only at harvest using the task's saved generation and the explicit
selection policy. Offline time produces one harvestable batch.
"""
from __future__ import annotations

import copy
from typing import Any

from app.business.city_production_rules import durability_kind
from app.business.fixed_resource_production import FixedResourceProduction
from app.business.player_services import integer


class AutomaticProduction(FixedResourceProduction):
    PLAN_KEY = "automaticResourceProductionV1"  # Internal, never wire data.

    def validate_recipe(self, record: dict, row: dict, code: Any, defines: dict) -> None:
        if (row.get("produceType") not in ("auto", "friend") or row.get("map0") is not True
                or durability_kind(record.get("durability"), defines) == "dead"
                or not isinstance(row.get("products"), list) or len(row["products"]) != 1
                or not isinstance(code, str) or code != row["products"][0]):
            raise ValueError("no stub response: invalid automatic production recipe")

    def start(self, player: dict, params: dict) -> dict:
        raise ValueError("automatic production starts on construction completion or deployment")

    def activate(self, player: dict, key: str) -> dict:
        key, record, row = self.owned(player, key)
        if row.get("produceType") not in ("auto", "friend"):
            return {}
        self.idle(player, key, record)
        if key in self.plans(player):
            raise ValueError("no stub response: automatic production ledger already exists")
        products = row.get("products")
        code = products[0] if isinstance(products, list) and len(products) == 1 else None
        self.validate_recipe(record, row, code, self.table("defines"))
        product = self.table("product").get(code)
        if not isinstance(product, dict):
            raise ValueError("stub has no assets: automatic product row missing")
        # Original auto rows have no cost types but retain a dummy [0] amount.
        if product.get("costTypes") != [] or product.get("costAmounts") not in ([], [0]):
            raise ValueError("no stub response: automatic recipe has unexpected start costs")
        now = self.now()
        due = integer(now + integer(product.get("dueInterval"), 1), 0, 9007199254740991)
        task = {"productId": code, "createdTime": float(now), "dueTime": float(due)}
        self.store_plan(player, key, record, row, task,
                        {"reward": None, "buildingExp": integer(product.get("buildingExp"))})
        player["produce"][key] = task
        record["status"] = "producing"
        return {key: copy.deepcopy(task)}

    def restore(self, player: dict) -> bool:
        if player["entity"].get("currentMapKey") != "map001":
            return False
        changed = False
        for key, record in player["buildings"].items():
            row = self.table("building").get(record.get("buildingTypeId"), {})
            if (row.get("produceType") in ("auto", "friend") and record.get("deployedMapKey") == "map001"
                    and record.get("status") in ("none", "waiting") and key not in player["produce"]
                    and durability_kind(record.get("durability"), self.table("defines")) != "dead"):
                self.activate(player, key)
                changed = True
        return changed

    def refresh_level(self, player: dict, key: str) -> None:
        plan = self.plans(player)[key]
        plan.update(buildingLevel=player["buildings"][key]["level"], reward=None)

    def discard(self, player: dict, key: str) -> None:
        self.active(player, key)
        del player["produce"][key]
        del self.plans(player)[key]
        player["buildings"][key]["status"] = "waiting"

    def harvest(self, player: dict, keys: list[str], *, point_cost: int = 1) -> dict:
        if len(keys) != 1:
            raise ValueError("automatic settlement requires one building at a time")
        key = self.ids(keys)[0]
        candidate = copy.deepcopy(player)
        record, row, plan, task = self.active(candidate, key)
        if plan.get("reward") is None:
            plan.update(self.reward_plan(record, row, task["productId"], seed=plan["generation"]))
        output = super().harvest(candidate, [key], point_cost=point_cost)
        if key in candidate["buildings"]:
            self.activate(candidate, key)
            output[key]["building"] = copy.deepcopy(candidate["buildings"][key])
        player.clear()
        player.update(candidate)
        return output
