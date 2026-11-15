"""Uninstalled static background sales and one-per-period national draft sales.

Policy switches/context are explicit simulator choices, not original schedules.
Background purchases use player.items; A still reads backgroundOwnership.
An ownership adapter/migration and mapId contract are required before mounting.
National periods/power must be supplied by an authoritative, locked context.
No default open period, fabricated national score, or multi-account write.
"""
from __future__ import annotations

import copy
from contextlib import nullcontext
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, ContextManager

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


@dataclass(frozen=True)
class NationalShopContext:
    """Internal: globally unique quota period, actual country and current power."""

    country: str
    period: str
    power: int


class EconomyShopServices(PlayerServices):
    def __init__(self, service: Any, *, static_background_sales: bool = False,
                 national_context: Callable[[str], ContextManager[NationalShopContext]] | None = None) -> None:
        super().__init__(service)
        self.static_background_sales = static_background_sales
        self.national_context = national_context

    def register(self, registry: Any) -> None:
        for name, action, national in (
            ("getBackgroundItems", self.background_items, False),
            ("buyBackgroundItem", self.buy_background, False),
            ("getShopItemsFromNationalPower", self.national_items, True),
            ("buyShopItemFromNationalPower", self.buy_national, True),
        ):
            api = "politic/shop/" + name
            registry.register(api, self.service._guard(api, partial(self.call_shop, api, action, national)))

    def call_shop(self, api: str, action: Any, national: bool, params: dict, session: dict | None) -> dict:
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, loaded, _ = found
        player = copy.deepcopy(loaded)
        try:
            if not player["entity"].get("created"):
                raise ValueError("created player required")
            country = player["entity"]["country"]
            if national and self.national_context is None:
                raise ValueError("no stub response: national shop context is not integrated")
            context = self.national_context(country) if national else nullcontext(None)
            # Context holds country/period stable THROUGH the player's atomic save.
            # Provider must obey player->country lock order and validate before save.
            with context as gate:
                if national:
                    if (not isinstance(gate, NationalShopContext) or gate.country != country
                            or not isinstance(gate.period, str) or not gate.period):
                        raise ValueError("invalid national shop context")
                    integer(gate.power)
                payload = action(player, params, gate)
                if player != loaded:
                    self.service._save(player, player_id)
            return response_shapes.success(api, payload)
        except ValueError as exc:
            return self.service._failure(api, str(exc))

    def row(self, table: str, key: Any) -> dict:
        if not isinstance(key, str) or not key:
            raise ValueError("item id required")
        row = self.table(table).get(key)
        if not isinstance(row, dict):
            # A loaded table with a missing reference is NOT a missing asset file.
            raise ValueError(f"no stub response: invalid {table} row reference {key}")
        return row

    def background_goods(self, row: dict) -> list[str]:
        if not self.static_background_sales:
            raise ValueError("no stub response: static background sales policy is disabled")
        if row.get("isEnable") is not True or row.get("category") not in ("near", "far"):
            raise ValueError("background sale disabled")
        ids = row.get("itemIds")
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str):
            raise ValueError("no stub response: only single background goods supported")
        table, category = ("item13", "nearground") if row["category"] == "near" else ("item14", "farground")
        item = self.row(table, ids[0])
        if item.get("enable") is not True or item.get("category") != category:
            raise ValueError("invalid background category or disabled item")
        integer(row.get("credit"), 1)
        return ids

    def background_items(self, player: dict, params: dict, gate: Any = None) -> dict:
        if not self.static_background_sales:
            raise ValueError("no stub response: static background sales policy is disabled")
        if params.get("category") not in ("near", "far"):
            raise ValueError("background category must be near or far")
        result = {}
        for code, row in self.table("shop_item_bg").items():
            if row.get("category") != params["category"] or row.get("isEnable") is not True:
                continue
            item = self.background_goods(row)[0]
            if integer(player["items"].get(item, 0)) == 0:
                result[code] = {}  # consumer reads keys only; value is compatibility choice
        return {"shopItems": result}

    def buy_background(self, player: dict, params: dict, gate: Any = None) -> dict:
        row = self.row("shop_item_bg", params.get("shopItemId"))
        item = self.background_goods(row)[0]
        # One owned item. A's selection still needs an ownership adapter.
        # Retry never charges twice.
        if integer(player["items"].get(item, 0)) == 0:
            price = integer(row["credit"], 1)
            balance = integer(player["resources"]["credit"]["amount"])
            if balance < price:
                raise ValueError("insufficient credit")
            player["resources"]["credit"]["amount"] = balance - price
            player["items"][item] = 1
        return {"resources": copy.deepcopy(player["resources"])}

    @staticmethod
    def national_supported(row: dict) -> bool:
        # Wider quotas need a request identity to distinguish retry from new sale.
        return (row.get("limitPerPerson") == 1 and row.get("isSet") is True
                and row.get("costTypes") == ["gold"] and row.get("discount") == 0
                and row.get("credit") == 0 and row.get("quantities") == [1])

    def national_goods(self, player: dict, row: dict) -> tuple[str, int, int]:
        if not self.national_supported(row):
            raise ValueError("no stub response: only one-per-period gold draft sets supported")
        ids, costs = row.get("itemIds"), row.get("costAmounts")
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or not isinstance(costs, list) or len(costs) != 1:
            raise ValueError("invalid national shop catalogue")
        item_id = ids[0]
        if item_id.startswith("countryshop_"):
            item_id = self.row("shop_item_country", item_id).get(player["entity"]["country"])
        item = self.row("item04", item_id)
        if item.get("enable") is not True or item.get("category") != "draft":
            raise ValueError("unsupported national shop delivery")
        draft = self.row("draft", item.get("parameterId"))
        self.row("building", draft.get("buildType"))
        thresholds = [integer(goal.get("nationalPower")) for goal in self.table("national_power_goal").values()
                      if row.get("goal") in goal.get("incentives", [])]
        if len(thresholds) != 1:
            raise ValueError("no stub response: ambiguous national goal reference")
        return item_id, integer(costs[0], 1), thresholds[0]

    @staticmethod
    def purchased(player: dict, period: str, code: str) -> bool:
        # Internal ledger; period must be global, not different for each country.
        return code in player.get("economyNationalPurchases", {}).get(period, {})

    def national_items(self, player: dict, params: dict, gate: NationalShopContext) -> dict:
        result = {}
        for code, row in self.table("national_power_shop_item").items():
            if not self.national_supported(row):
                continue
            _, _, threshold = self.national_goods(player, row)
            result[code] = {"state": "open" if gate.power >= threshold else "lock",
                            "remain": 0.0 if self.purchased(player, gate.period, code) else 1.0}
        return {"shopItems": result, "recommendedItems": {}}

    def buy_national(self, player: dict, params: dict, gate: NationalShopContext) -> dict:
        if integer(params.get("index"), -1) != -1 or integer(params.get("quantity"), 1) != 1:
            raise ValueError("only index=-1 quantity=1 supported")
        code = params.get("shopItemId")
        row = self.row("national_power_shop_item", code)
        item, price, threshold = self.national_goods(player, row)
        if self.purchased(player, gate.period, code):
            # Success would make ShopItemNationalPower.addDraft increment again.
            raise ValueError("national shop item already purchased in this period")
        if gate.power < threshold:
            raise ValueError("national shop goal locked")
        balance = integer(player["resources"]["gold"]["amount"])
        # Existing draft amounts may include legacy drafts outside items.
        total = self.service._draft_amounts(player).get(self.row("item04", item)["parameterId"], 0)
        if integer(total) >= 99:  # ShopItemNationalPower.checkDraftAmount
            raise ValueError("draft capacity exceeded")
        if balance < price:
            raise ValueError("insufficient gold")
        player["resources"]["gold"]["amount"] = balance - price
        player["items"][item] = integer(player["items"].get(item, 0)) + 1
        player.setdefault("economyNationalPurchases", {}).setdefault(gate.period, {})[code] = item
        return {"resources": copy.deepcopy(player["resources"])}
