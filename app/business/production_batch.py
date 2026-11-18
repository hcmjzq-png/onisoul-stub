"""Client-defined batch start and harvest for the mounted production engines.

PoliticFSMCollectiveProduce charges one PP per start. PoliticFSMAutoHarvest
charges one PP for a single production, otherwise the original defines value.
Each request commits all supported tasks together; no new wire fields are used.
"""
from __future__ import annotations

import copy

from app.business.city_production_rules import harvest_display_point_cost
from app.business.city_services import CityServices
from app.business.player_services import integer


class ProductionBatch(CityServices):
    def start(self, player: dict, params: dict) -> dict:
        keys = self.ids(params.get("buildingIds"))
        codes = params.get("productIds")
        if not isinstance(codes, list) or len(codes) != len(keys):
            raise ValueError("productIds must match buildingIds")
        candidate = copy.deepcopy(player)
        output, now = {}, None
        for key, code in zip(keys, codes):
            engine = self.service._production_for(candidate, key, code)
            result = engine.start(candidate, {"buildingId": key, "productId": code})
            output[key] = copy.deepcopy(candidate["produce"][key])
            if now is None:
                now = result["now"]
        player.clear()
        player.update(candidate)
        return {"producings": output, "now": now}

    def harvest(self, player: dict, keys: list[str]) -> dict:
        if not keys:
            return {}
        keys = self.ids(keys)
        cost = harvest_display_point_cost(len(keys), self.table("defines"))
        points = player["actionPoints"]["politicPoint"]
        if integer(points.get("point")) < cost:
            raise ValueError("insufficient politic points for harvest")
        candidate = copy.deepcopy(player)
        output = {}
        for key in keys:
            engine = self.service._production_for(candidate, key)
            output.update(engine.harvest(candidate, [key], point_cost=0))
        candidate["actionPoints"]["politicPoint"]["point"] -= cost
        player.clear()
        player.update(candidate)
        return output
