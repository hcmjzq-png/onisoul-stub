"""Verified main-map placement and building-level transactions.

Production yields/road bonuses, automatic production and kokudaka aggregation
remain outside this scope; see docs/analysis/city-contract-20261115/README.md.
"""
from __future__ import annotations

import copy
from functools import partial
import math
import re
import struct
from typing import Any

from app.business.player_services import PlayerServices, integer
from app.business.production_availability import recipe_available


def building_id(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        value = int(value)
    return str(integer(value, 1))


def coordinates(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("coordinate must contain two integers")
    return integer(value[0]), integer(value[1])


def level_cost(amount: Any, ratio: Any) -> int:
    """PoliticBuilding.getLevelUpCosts: float32 ratio rounded to thousandths."""
    amount = integer(amount)
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio <= 2147483:
        raise ValueError("stub has no assets: invalid building level cost ratio")
    f32 = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
    scaled = int(round(f32(f32(ratio) * 1000)))
    return integer(amount * scaled // 1000)


class CityServices(PlayerServices):
    def register(self, registry: Any) -> None:
        actions = {
            "politic/building/getProductsByBuilding": self.products,
            "politic/map/relocateEnded": self.relocate,
            "politic/building/putInBuildings": self.store_buildings,
            "politic/building/deployBuilding": self.deploy,
            "politic/building/levelUpBuilding": partial(self.upgrade, mode="single"),
            "politic/building/levelUpBuildings": partial(self.upgrade, mode="batch"),
            "politic/building/levelUpBuildingCollectively": partial(self.upgrade, mode="collective"),
            "politic/task/submitBulkBuildAndComplete": partial(self.build_roads, serial=False),
            "politic/task/submitSerialBuildAndComplete": partial(self.build_roads, serial=True),
        }
        for api, action in actions.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def products(self, player: dict, params: dict) -> dict:
        """Return the recipes currently available to start."""
        _, _, building = self.owned(player, params.get("buildingId"))
        codes = building.get("products")
        if not isinstance(codes, list):
            raise ValueError("stub has no assets: building products list missing")
        catalogue = self.table("product")
        missions = self.service.missions.rows()
        products = {}
        for code in codes:
            if code == "none":
                continue
            if not isinstance(code, str) or not isinstance(catalogue.get(code), dict):
                raise ValueError("stub has no assets: referenced product row missing")
            row = catalogue[code]
            if recipe_available(player, building, code, row, missions):
                products[code] = {}
        return {"products": products}

    @staticmethod
    def current_map(player: dict) -> str:
        if not player["entity"].get("created") or player["entity"].get("currentMapKey") != "map001":
            raise ValueError("only an existing player's main map is supported")
        return "map001"

    def owned(self, player: dict, value: Any, *, stored: bool = False) -> tuple[str, dict, dict]:
        current = self.current_map(player)
        key = building_id(value)
        record = player["buildings"].get(key)
        if not isinstance(record, dict) or record.get("deployedMapKey") != ("none" if stored else current):
            raise ValueError("building not owned or not in the required map/storage")
        row = self.table("building").get(record.get("buildingTypeId"))
        if not isinstance(row, dict):
            raise ValueError("no stub response: referenced building row missing")
        return key, record, row

    def ids(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("buildingIds must be a nonempty array")
        keys = [building_id(item) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate buildingIds")
        return keys

    def validate_layout(self, player: dict) -> None:
        current = self.current_map(player)
        width, height = self.service._map_size(player)
        cells: set[tuple[int, int]] = set()
        occupied = {}
        for key, record in player["buildings"].items():
            if record.get("deployedMapKey") != current:
                continue
            _, _, row = self.owned(player, key)
            size = row.get("size")
            if not isinstance(size, list) or len(size) != 2:
                raise ValueError("stub has no assets: building footprint missing")
            sx, sy = integer(size[0], 1), integer(size[1], 1)
            x, y = integer(record.get("x")), integer(record.get("y"))
            if x - sx + 1 < 0 or y - sy + 1 < 0 or x >= width or y >= height:
                raise ValueError("building footprint outside map")
            footprint = {(a, b) for a in range(x - sx + 1, x + 1) for b in range(y - sy + 1, y + 1)}
            if footprint & cells:
                raise ValueError("building footprints overlap")
            cells.update(footprint)
            # Existing save format; PoliticMap parses the two digit groups.
            occupied[f"{x},{y}"] = key
        player["occupiedGrids"] = occupied

    @staticmethod
    def idle(player: dict, key: str, record: dict) -> None:
        if record.get("status") not in ("none", "waiting") or key in player["produce"]:
            raise ValueError("active construction/production/event/trade is not supported here")

    def relocate(self, player: dict, params: dict) -> dict:
        current = self.current_map(player)
        value = params.get("relocatedGrids")
        if not isinstance(value, dict):
            raise ValueError("relocatedGrids must be a map")
        positions = {}
        for coord, value_id in value.items():
            match = re.fullmatch(r"x(0|[1-9][0-9]*)y(0|[1-9][0-9]*)", coord) if isinstance(coord, str) else None
            if match is None:
                raise ValueError("relocatedGrids key must be x<number>y<number>")
            key, record, _ = self.owned(player, value_id)
            if key in positions:
                raise ValueError("duplicate building in relocatedGrids")
            position = tuple(map(int, match.groups()))
            if position != (record.get("x"), record.get("y")):
                row = self.table("building")[record["buildingTypeId"]]
                if row.get("produceType") in ("auto", "friend") and key in player["produce"]:
                    self.service.automatic_production.active(player, key)
                else:
                    self.idle(player, key, record)
            positions[key] = position
        expected = {key for key, row in player["buildings"].items() if row.get("deployedMapKey") == current}
        if set(positions) != expected:
            raise ValueError("relocation must include every placed building exactly once")
        for key, (x, y) in positions.items():
            player["buildings"][key].update(x=x, y=y)
        self.validate_layout(player)
        return {}

    def storage_supported(self, row: dict) -> None:
        if row.get("connectChipType") != "none" or row.get("produceType") not in ("none", "manual", "single", "auto", "friend"):
            raise ValueError("connected decorations/special production storage is not implemented")

    def store_buildings(self, player: dict, params: dict) -> dict:
        for key in self.ids(params.get("buildingIds")):
            record = player["buildings"].get(key)
            stored = isinstance(record, dict) and record.get("deployedMapKey") == "none"
            key, record, row = self.owned(player, key, stored=stored)
            self.storage_supported(row)
            if row.get("produceType") in ("auto", "friend") and key in player["produce"]:
                self.service.automatic_production.discard(player, key)
            self.idle(player, key, record)
            record.update(deployedMapKey="none", status="waiting")
        self.validate_layout(player)
        return {}

    def deploy(self, player: dict, params: dict) -> dict:
        key = building_id(params.get("buildingId"))
        position = coordinates(params.get("originCoord"))
        record = player["buildings"].get(key)
        stored = isinstance(record, dict) and record.get("deployedMapKey") == "none"
        key, record, row = self.owned(player, key, stored=stored)
        self.storage_supported(row)
        if (not stored and row.get("produceType") in ("auto", "friend") and key in player["produce"]
                and position == (record.get("x"), record.get("y"))):
            self.service.automatic_production.active(player, key)
            return {"buildingId": float(key), "building": record,
                    "autoProducings": {key: copy.deepcopy(player["produce"][key])}}
        self.idle(player, key, record)
        if not stored and position != (record.get("x"), record.get("y")):
            raise ValueError("placed building must be moved using relocateEnded")
        if row.get("map0") is not True:
            raise ValueError("building not permitted on main map")
        record.update(deployedMapKey=self.current_map(player), x=position[0], y=position[1], status="waiting")
        self.validate_layout(player)
        tasks = self.service.automatic_production.activate(player, key)
        return {"buildingId": float(key), "building": record, "autoProducings": tasks}

    def upgrade(self, player: dict, params: dict, *, mode: str) -> dict:
        keys = [building_id(params.get("buildingId"))] if mode == "single" else self.ids(params.get("buildingIds"))
        times = params.get("levelUpTimes") if mode == "collective" else [1] * len(keys)
        if not isinstance(times, list) or len(times) != len(keys):
            raise ValueError("levelUpTimes must match buildingIds")
        rule = self.table("defines").get("politic_expend_point")
        if not isinstance(rule, dict):
            raise ValueError("stub has no assets: politic_expend_point missing")
        point_cost = integer(rule.get("value"), 1)
        # Single/batch client paths explicitly subtract one point; refuse a table
        # version that disagrees rather than silently applying different costs.
        if point_cost != 1:
            raise ValueError("unsupported politic_expend_point version")
        levels = self.table("building_level")
        output, costs, total_points, active_auto = {}, {}, 0, []
        for key, count in zip(keys, times):
            key, record, row = self.owned(player, key)
            if row.get("produceType") in ("auto", "friend") and key in player["produce"]:
                self.service.automatic_production.active(player, key)
                active_auto.append(key)
            else:
                self.idle(player, key, record)
            count = integer(count, 1, len(levels))
            level, exp = integer(record.get("level"), 1), integer(record.get("exp"))
            grade = integer(row.get("grade"), 1)
            prefix = row.get("levelUpTypeId")
            if not isinstance(prefix, str):
                raise ValueError("stub has no assets: building level type missing")
            types, amounts = row.get("costTypes"), row.get("costAmounts")
            if not isinstance(types, list) or not isinstance(amounts, list) or len(types) != len(amounts) or len(types) != len(set(types)):
                raise ValueError("stub has no assets: inconsistent building costs")
            for _ in range(count):
                step = levels.get(f"{prefix}{grade * 1000 + level}")
                if not isinstance(step, dict):
                    raise ValueError("stub has no assets: building level row missing")
                needed = integer(step.get("needExp"))
                if needed == 0 or exp < needed:
                    raise ValueError("building experience insufficient or maximum level reached")
                if f"{prefix}{grade * 1000 + level + 1}" not in levels:
                    raise ValueError("stub has no assets: next building level missing")
                for resource, amount in zip(types, amounts):
                    if resource not in player["resources"]:
                        raise ValueError("unsupported building cost resource")
                    costs[resource] = costs.get(resource, 0) + level_cost(amount, step.get("needCostRatio"))
                exp -= needed
                level += 1
                total_points += point_cost
            record.update(level=level, exp=exp)
            output[key] = record
        point = player["actionPoints"]["politicPoint"]
        if integer(point["point"]) < total_points or any(integer(player["resources"][k]["amount"]) < v for k, v in costs.items()):
            raise ValueError("insufficient resources or politic points")
        point["point"] -= total_points
        for resource, amount in costs.items():
            player["resources"][resource]["amount"] -= amount
        for key in active_auto:
            self.service.automatic_production.refresh_level(player, key)
        if mode == "single":
            return {"building": output[keys[0]]}
        if mode == "batch":
            return {"output_buildings": output}
        return {"resultBuildings": output, "totalUsedPoint": float(total_points), "restResources": player["resources"]}

    def build_roads(self, player: dict, params: dict, *, serial: bool) -> dict:
        self.current_map(player)
        code = params.get("draftId")
        draft = self.table("draft").get(code) if isinstance(code, str) else None
        row = self.table("building").get(draft.get("buildType")) if isinstance(draft, dict) else None
        if not isinstance(row, dict):
            raise ValueError("unknown road draft")
        if (row.get("connectChipType") != "road" or row.get("size") != [1, 1]
                or row.get("costTypes") != [] or row.get("costAmounts") != []
                or row.get("produceType") != "none" or draft.get("immediateBuild") is not True
                or draft.get("isConsume") is not False or draft.get("progressCount") != 0):
            raise ValueError("only verified free immediate road rows are supported by bulk construction")
        positions = params.get("originCoords")
        width, height = self.service._map_size(player)
        if not isinstance(positions, list) or not 1 <= len(positions) <= width * height:
            raise ValueError("originCoords must be a nonempty coordinate array within map capacity")
        positions = [coordinates(value) for value in positions]
        if len(positions) != len(set(positions)):
            raise ValueError("duplicate coordinates")
        output, origins = {}, {}
        existing = {(r.get("x"), r.get("y")): r for r in player["buildings"].values()
                    if r.get("deployedMapKey") == self.current_map(player)}
        for position in positions:
            record = existing.get(position)
            if record is not None and record.get("buildingTypeId") == draft["buildType"] and record.get("status") in ("none", "waiting"):
                record = copy.deepcopy(record)  # retry at an existing identical road
            else:
                record = self.service._build_from_draft(player, code, position, completed=True)
            if record is None:
                raise ValueError("road location blocked or outside map")
            key = str(record["instanceId"])
            output[key] = record
            origins[key] = {"0": float(position[0]), "1": float(position[1])}
        self.validate_layout(player)
        if serial:
            body = {str(i): {"buildingId": float(key), "building": row, "x": origins[key]["0"], "y": origins[key]["1"],
                             "buildingCount": float(len(player["buildings"]))} for i, (key, row) in enumerate(output.items())}
            return {**body, "autoProducings": {}}
        return {"buildings": output, "originCoords": origins, "autoProducings": {}}
