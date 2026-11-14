"""Group A: verified inventory sales and explicitly owned background selection.

Not mounted by GameplayService. Production settlement remains unimplemented.
backgroundOwnership/mapBackgrounds are proposed SERVER-INTERNAL save fields,
not original wire fields. No ownership is granted by these handlers.
"""
from __future__ import annotations

from functools import partial
from typing import Any

from app.business.city_services import CityServices
from app.business.player_services import integer


class CityProductionServices(CityServices):
    def register(self, registry: Any) -> None:
        for api, action in {
            "politic/shop/sellBuildings": self.sell_buildings,
            "politic/map/getBackgrounds": self.backgrounds,
            "politic/map/setBackground": self.set_background,
        }.items():
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
        self.current_map(player)
        owned = player.get("backgroundOwnership")
        if not isinstance(owned, dict):
            raise ValueError("no stub response: background ownership has not been migrated")
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
            codes = owned.get(category)
            # Empty lists crash mypageBgItemSelect.SelectItemCode; do not
            # invent a default background to make the selector appear usable.
            if not isinstance(codes, list) or not codes:
                raise ValueError("no stub response: both background categories need verified ownership")
            if any(not isinstance(code, str) or code not in known[category] for code in codes):
                raise ValueError("no stub response: owned background is outside supported catalogue")
            result[category] = {code: {} for code in codes}
        return result

    def set_background(self, player: dict, params: dict) -> dict:
        self.current_map(player)
        if integer(params.get("mapId")) != 0:
            raise ValueError("no stub response: sub-map background selection is unsupported")
        owned = self.backgrounds(player, {})
        chosen = {}
        for category in ("nearGround", "farGround"):
            code = params.get(category)
            if not isinstance(code, str) or code not in owned[category]:
                raise ValueError("background not owned in the requested category")
            chosen[category] = code
        player.setdefault("mapBackgrounds", {})["0"] = chosen
        return {}

    @staticmethod
    def selected_background(player: dict) -> dict:
        """Integration helper for getMapData.map; never grants ownership."""
        selected = (player.get("mapBackgrounds") or {}).get("0", {})
        owned = player.get("backgroundOwnership") or {}
        return {category: code for category, code in selected.items()
                if category in ("nearGround", "farGround")
                and isinstance(code, str) and code in owned.get(category, [])}
