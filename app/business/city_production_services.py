"""Group A: verified inventory sales and explicitly owned background selection.

GameplayService mounts inventory sales only from CityProductionServices.
ManualProductionServices is a start/timer base used by the mounted production
engines; this module does not register a settlement engine on its own.
items/mapBackgrounds are SERVER-INTERNAL save fields, not original wire fields.
The original background UI is subcity-only (mapId=1). It needs a verified
subcity provider before mounting; no ownership or city unlock is granted here.
"""
from __future__ import annotations

import copy
from functools import partial
import math
import time
from typing import Any, Callable

from app.business.city_services import CityServices
from app.business.city_production_rules import durability_kind, production_costs
from app.business.player_services import integer
from app.business.production_availability import FIELD_LESSON_RECIPE, recipe_available
from app.business.production_modifiers import validate_formation


class CityProductionServices(CityServices):
    def __init__(self, service: Any, *, subcity_enabled: Callable[[dict], bool] | None = None) -> None:
        super().__init__(service)
        # Provider reads authoritative player state under the shared player lock.
        # No production provider exists yet; callers cannot supply this via params.
        self.subcity_enabled = subcity_enabled

    def require_subcity(self, player: dict) -> None:
        if self.subcity_enabled is None or self.subcity_enabled(player) is not True:
            raise ValueError("no stub response: verified subcity state is not integrated or locked")

    def register(self, registry: Any, *, apis: frozenset[str] | None = None) -> None:
        for api, action in {
            "politic/shop/sellBuildings": self.sell_buildings,
            "politic/map/getBackgrounds": self.backgrounds,
            "politic/map/setBackground": self.set_background,
        }.items():
            if apis is None or api in apis:
                registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def sell_buildings(self, player: dict, params: dict) -> dict:
        self.current_map(player)
        keys = self.ids(params.get("buildingIds"))
        prices = self.table("itemIdToShopId")
        buildings = self.table("building")
        sold, gain = {}, 0
        for key in keys:
            # InventoryUpdateSaleBuild enumerates inventory only. Placed and
            # active buildings cannot be sold through this supported path.
            record = player["buildings"].get(key)
            if not isinstance(record, dict) or record.get("deployedMapKey") != "none":
                raise ValueError("building not owned or not in storage")
            row = buildings.get(record.get("buildingTypeId"))
            if not isinstance(row, dict):
                raise ValueError("no stub response: referenced building row missing")
            self.idle(player, key, record)
            if key in {str(value) for value in player["occupiedGrids"].values()}:
                raise ValueError("stored building still has a map reference")
            price = prices.get(row.get("itemId"))
            if not isinstance(price, dict):
                raise ValueError("no stub response: referenced sale price row missing")
            amount = price.get("price")
            if amount == -1:
                raise ValueError("building cannot be sold")
            gain += integer(amount)
            sold[key] = record
        gold = player["resources"]["gold"]
        balance = integer(gold.get("amount"))
        if balance + gain > integer(gold.get("maxAmount")):
            # Overflow disposition is unknown. Reject the entire transaction.
            raise ValueError("no stub response: sale gold overflow is unsupported")
        for key in keys:
            del player["buildings"][key]
        gold["amount"] = balance + gain
        player["counters"]["buildingCount"] = len(player["buildings"])
        # Consumer only reads buildings.Keys; values retain the sold records
        # as an explicit compatibility choice, not a captured server response.
        return {"buildings": sold, "gainGold": float(gain),
                "buildingCount": float(len(player["buildings"]))}

    def backgrounds(self, player: dict, params: dict) -> dict:
        self.require_subcity(player)
        catalogue = self.table("shop_item_bg")
        known = {"nearGround": set(), "farGround": set()}
        for row in catalogue.values():
            # Disabled original rows include inconsistent cross-category item
            # references. Only the verified enabled catalogue subset is supported.
            if row.get("isEnable") is not True:
                continue
            category = {"near": "nearGround", "far": "farGround"}.get(row.get("category"))
            if category and isinstance(row.get("itemIds"), list):
                known[category].update(code for code in row["itemIds"] if isinstance(code, str))
        result = {}
        for category in known:
            codes = sorted(code for code in known[category] if integer(player["items"].get(code, 0)) > 0)
            # Empty lists crash mypageBgItemSelect.SelectItemCode; do not
            # invent a default background to make the selector appear usable.
            if not codes:
                raise ValueError("no stub response: both background categories need verified ownership")
            result[category] = {code: {} for code in codes}
        return result

    def set_background(self, player: dict, params: dict) -> dict:
        if integer(params.get("mapId")) != 1:
            raise ValueError("no stub response: original background selection requires subcity mapId=1")
        owned = self.backgrounds(player, {})
        chosen = {}
        for category in ("nearGround", "farGround"):
            code = params.get(category)
            if not isinstance(code, str) or code not in owned[category]:
                raise ValueError("background not owned in the requested category")
            chosen[category] = code
        player.setdefault("mapBackgrounds", {})["1"] = chosen
        return {}

    def selected_background(self, player: dict, map_id: int) -> dict:
        """Subcity-only projection; never copies map 1 backgrounds into main map 0."""
        if map_id != 1:
            return {}
        owned = self.backgrounds(player, {})
        selected = (player.get("mapBackgrounds") or {}).get("1", {})
        return {category: code for category, code in selected.items()
                if category in ("nearGround", "farGround")
                and isinstance(code, str) and code in owned.get(category, [])}


class ManualProductionServices(CityServices):
    """Shared start/timer component; settlement-owning subclasses are mounted.

    The default recipe validator is narrow. Mounted subclasses own their
    settlement and decide which building and recipe pairs they support.
    """

    FIELD = "building200_041_01_01_1_1"
    PRODUCE_TYPE = "manual"
    APPLY_LESSON_POLICY = False  # Unmounted start-only component.
    # Ordinary resource recipes only: special flower/random drops are excluded.
    PRODUCTS = frozenset({"product060_023_01_01_1_1", "product060_001_01_01_1_1"})

    def __init__(self, service: Any, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        self.clock = clock

    def register(self, registry: Any, *, apis: frozenset[str]) -> None:
        # No default whitelist. GameplayService deliberately does not call this.
        for api, bulk in (("politic/task/submitProduceTask", False),
                          ("politic/task/submitBulkProduceTasks", True)):
            if api in apis:
                registry.register(api, self.service._guard(
                    api, partial(self.call, api, partial(self.submit, bulk=bulk))))

    @staticmethod
    def no_modifiers(player: dict) -> None:
        # Legacy method name retained for existing settlement engines.
        validate_formation(player)

    def submit(self, player: dict, params: dict, *, bulk: bool = False) -> dict:
        # Work on a private candidate even for direct component callers.
        candidate = copy.deepcopy(player)
        payload = self._submit(candidate, params, bulk=bulk)
        player.clear()
        player.update(candidate)
        return payload

    def validate_recipe(self, record: dict, row: dict, code: Any, defines: dict) -> None:
        if (record.get("buildingTypeId") != self.FIELD or row.get("produceType") != self.PRODUCE_TYPE
                or durability_kind(record.get("durability"), defines) != "infinite"):
            raise ValueError("no stub response: unsupported manual production building")
        if (not isinstance(row.get("products"), list) or not isinstance(code, str)
                or code not in self.PRODUCTS or code not in row["products"]):
            raise ValueError("no stub response: unsupported production recipe")

    def _submit(self, player: dict, params: dict, *, bulk: bool) -> dict:
        self.current_map(player)
        self.no_modifiers(player)
        keys = self.ids(params.get("buildingIds") if bulk else [params.get("buildingId")])
        codes = params.get("productIds") if bulk else [params.get("productId")]
        if not isinstance(codes, list) or len(codes) != len(keys):
            raise ValueError("productIds must match buildingIds")
        now_value = self.clock()
        # Integer Unix seconds are consumed by PoliticBuildingParameter.updateTask.
        if isinstance(now_value, bool) or not isinstance(now_value, (int, float)):
            raise ValueError("no stub response: invalid production clock")
        if not math.isfinite(now_value) or now_value < 0:
            raise ValueError("no stub response: invalid production clock")
        now = int(now_value)
        if now > 9007199254740991:
            raise ValueError("no stub response: production clock out of range")
        output, costs = {}, {}
        catalogue, levels, defines = self.table("product"), self.table("building_level"), self.table("defines")
        missions = self.service.missions.rows() if self.APPLY_LESSON_POLICY else {}
        lesson_started = False
        for key, code in zip(keys, codes):
            key, record, row = self.owned(player, key)
            # Replaying bulk success reruns payoutCosts in the original client.
            # No response replay, even for an identical active recipe.
            if key in player["produce"]:
                raise ValueError("no stub response: production already exists; reload authoritative map/resources")
            self.idle(player, key, record)
            self.validate_recipe(record, row, code, defines)
            product = catalogue.get(code)
            if not isinstance(product, dict):
                raise ValueError("no stub response: referenced product row missing")
            if self.APPLY_LESSON_POLICY:
                allowed = recipe_available(player, row, code, product, missions)
            else:
                allowed = (product.get("openMission") == "null"
                           and integer(product.get("openLevel")) <= integer(player["entity"].get("level"), 1))
            if not allowed:
                raise ValueError("production recipe is locked or unsupported")
            if self.APPLY_LESSON_POLICY and code == FIELD_LESSON_RECIPE:
                if lesson_started:
                    raise ValueError("only one field lesson production can be active")
                lesson_started = True
            grade = integer(row.get("grade"), 1)
            level = integer(record.get("level"), 1, grade * 10)
            step = levels.get(f"{row.get('levelUpTypeId')}{grade * 1000 + level}")
            if not isinstance(step, dict):
                raise ValueError("no stub response: referenced production level row missing")
            # The table's lowercase intervalRatio is NOT the dead accessor's
            # uppercase IntervalRatio. Only the unchanged original timing subset.
            if step.get("intervalRatio") != 1:
                raise ValueError("no stub response: modified production intervals are unsupported")
            # Compatibility policy for this unmodified subset: schedule the
            # displayed table duration. No original server timing capture exists.
            due = now + integer(product.get("dueInterval"), 1)
            if due > 9007199254740991:
                raise ValueError("no stub response: production dueTime out of range")
            for resource, amount in production_costs(product, step).items():
                if resource not in player["resources"]:
                    raise ValueError("no stub response: unsupported production cost resource")
                costs[resource] = integer(costs.get(resource, 0) + amount)
            output[key] = {"productId": code, "createdTime": float(now), "dueTime": float(due)}
        points = player["actionPoints"]["politicPoint"]
        if integer(points.get("point")) < len(keys) or any(
                integer(player["resources"][kind].get("amount")) < amount for kind, amount in costs.items()):
            raise ValueError("insufficient resources or politic points")
        points["point"] -= len(keys)
        for kind, amount in costs.items():
            player["resources"][kind]["amount"] -= amount
        for key, task in output.items():
            player["produce"][key] = task
            player["buildings"][key]["status"] = "producing"
        # At dueTime the client timer becomes harvestable; merely reading a map
        # does not grant rewards, change durability, or accrue building/player XP.
        return ({"producings": copy.deepcopy(output), "now": float(now)} if bulk
                else {"dueTime": output[keys[0]]["dueTime"], "now": float(now)})
