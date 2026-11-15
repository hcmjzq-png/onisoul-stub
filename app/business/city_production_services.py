"""Group A: verified inventory sales and explicitly owned background selection.

GameplayService mounts inventory sales only. Production settlement is unimplemented.
items/mapBackgrounds are SERVER-INTERNAL save fields, not original wire fields.
The original background UI is subcity-only (mapId=1). It needs a verified
subcity provider before mounting; no ownership or city unlock is granted here.
"""
from __future__ import annotations

from functools import partial
from typing import Any, Callable

from app.business.city_services import CityServices
from app.business.player_services import integer


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
