"""Player inventory, profile and ordinary-shop APIs verified against PC callbacks.

Only supported catalogue entries can be bought. No lottery, enhancement, event
schedule, reward probability or warehouse cooldown is inferred here.
"""
from __future__ import annotations

import copy
import math
from functools import partial
from typing import Any

from app.business import response_shapes
from app.business.decks import character_id
from app.tables import TableError


def integer(value: Any, minimum: int = 0, maximum: int = 2147483647) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("integer parameter required")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError("integer parameter required")
    if not minimum <= value <= maximum:
        raise ValueError("integer parameter out of range")
    return int(value)


class PlayerServices:
    def __init__(self, service: Any) -> None:
        self.service = service

    def register(self, registry: Any) -> None:
        handlers = {
            "common/getEquips": partial(self.inventory, name="equips"),
            "common/getTactics": partial(self.inventory, name="tactics"),
            "deck/getCharactersInStore": partial(self.inventory, name="storedCharacters"),
            "deck/getProtectedCharacterIds": partial(self.protected, kind="characters"),
            "deck/getProtectedEquipIds": partial(self.protected, kind="equips"),
            "deck/setCharacterProtect": partial(self.protect, kind="characters", field="characterIds"),
            "deck/setEquipProtect": partial(self.protect, kind="equips", field="equipIds"),
            "deck/getCharacterStoreInfo": self.storage_info,
            "deck/getDeckBonus": self.deck_bonus,
            "politic/mypage/getPlayerProfile": self.profile,
            "politic/mypage/setSelfIntroduction": self.set_profile,
            "politic/map/setMapName2": self.set_map_name,
            "politic/mypage/getLessonStates": self.lesson_states,
            "politic/support_item/getPotions": self.potions,
            "politic/shop/getShopItems": self.shop_items,
            "politic/shop/buyShopItem": self.buy_item,
        }
        for api, action in handlers.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def table(self, name: str) -> dict:
        try:
            return self.service.catalog.load(name)
        except TableError as exc:
            raise ValueError(f"stub has no assets: required table {name}") from exc

    def call(self, api: str, action: Any, params: dict, session: dict | None) -> dict:
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, player, dirty = found
        before = copy.deepcopy(player)
        try:
            payload = action(player, params)
        except ValueError as exc:
            return self.service._failure(api, str(exc))
        if dirty or player != before:
            self.service._save(player, player_id)
        return response_shapes.success(api, copy.deepcopy(payload))

    @staticmethod
    def inventory(player: dict, params: dict, *, name: str) -> dict:
        return player.get(name) or {}

    @staticmethod
    def protected(player: dict, params: dict, *, kind: str) -> dict:
        # DeckScene iterates Values and converts IDs to strings; no envelope.
        values = sorted(set((player.get("protectedCards") or {}).get(kind) or []))
        return {str(index): value for index, value in enumerate(values)}

    @staticmethod
    def protect(player: dict, params: dict, *, kind: str, field: str) -> dict:
        if type(params.get("enable")) is not bool or not isinstance(params.get(field), list) or not params[field]:
            raise ValueError("enable must be boolean and card ids a nonempty array")
        ids = [character_id(value) for value in params[field]]
        owned = dict(player.get(kind) or {})
        if kind == "characters":
            owned.update(player.get("storedCharacters") or {})
        if any(key not in owned for key in ids):
            raise ValueError("cannot protect an unowned card")
        protected = player.setdefault("protectedCards", {})
        values = set(protected.get(kind) or [])
        values = values | set(ids) if params["enable"] else values - set(ids)
        protected[kind] = sorted(values)
        return {}

    @staticmethod
    def storage_info(player: dict, params: dict) -> dict:
        stored = player.get("characterStore") or {}
        return {"characterCount": float(len(player.get("storedCharacters") or {})),
                **{key: float(stored.get(key) or 0) for key in
                   ("extendSlot", "extendLimit", "lastOpenDate", "nextOpenLimit")}}

    @staticmethod
    def deck_bonus(player: dict, params: dict) -> dict:
        # No ranked or time-limited bonuses have been activated in this service.
        # A catalogue's existence is not evidence that its event is currently open.
        return {"deck": {kind: {slot: {"id": value, "bonus": {}}
                               for slot, value in ((player.get("decks") or {}).get(kind, {}).get("0", {}).get("ids") or {}).items()}
                         for kind in ("attack", "defense", "politic", "quest")}}

    def profile(self, player: dict, params: dict) -> dict:
        entity = player["entity"]
        profile = player.get("selfIntroduction") or {}
        return {"username": entity["username"], "level": float(entity["level"]),
                "country": entity["country"],
                **copy.deepcopy(player["actionPoints"]),
                "characterCount": float(len(player["characters"])),
                "buildingCount": float(len(player["buildings"])),
                "tacticCount": float(sum(int(row.get("amount") or 0) for row in (player.get("tactics") or {}).values())),
                "friendCount": float(len(player.get("friends") or {})),
                "raidBossPoint": float(player.get("raidBossPoint") or 0),
                "rank": str(player.get("countryRankId") or ""),
                "souls": {key: float((player.get("souls") or {}).get(key) or 0)
                          for key in ("red", "blue", "purple", "yellow", "green", "black", "white")},
                "selfIntroduction": {"message": profile.get("message", ""),
                                     "habits": profile.get("habits", {"0": "none", "1": "none", "2": "none"})},
                "eachKokudaka": {"0": float(player.get("kokudaka") or 0)}}

    def set_profile(self, player: dict, params: dict) -> dict:
        message, habits = params.get("message"), params.get("habits")
        self.validate_text(message, "self_introduction_message")
        table = self.table("habit")
        if not isinstance(habits, dict) or set(habits) != {"0", "1", "2"}:
            raise ValueError("three habit slots are required")
        if any(not isinstance(value, str) or value not in table and value != "none" for value in habits.values()):
            raise ValueError("unknown habit")
        player["selfIntroduction"] = {"message": message, "habits": copy.deepcopy(habits)}
        return {}

    def validate_text(self, value: Any, key: str) -> None:
        defines = self.table("defines")
        low, high = defines.get(key + "_min_length"), defines.get(key + "_max_length")
        if not low or not high:
            raise ValueError("stub has no assets: text length rule missing")
        if not isinstance(value, str):
            raise ValueError("text parameter required")
        try:
            length = len(value.encode("utf-16-le")) // 2
        except UnicodeError as exc:
            raise ValueError("invalid text encoding") from exc
        if not int(low["value"]) <= length <= int(high["value"]):
            raise ValueError("text length is outside the client table limit")

    def set_map_name(self, player: dict, params: dict) -> dict:
        if integer(params.get("mapId")) != 0:
            raise ValueError("sub-map naming is not implemented")
        self.validate_text(params.get("mapName"), "mapname")
        player.setdefault("mapNames", {})["0"] = params["mapName"]
        return {}

    def lesson_states(self, player: dict, params: dict) -> dict:
        done = set(player.get("lessonsDone") or [])
        return {"states": {str(int(code.removeprefix("lesson_"))): "C" if code in done else "L"
                           for code in self.table("lesson") if code.startswith("lesson_")}}

    def potion_amounts(self, player: dict, *, category: str | None = None) -> dict:
        result = {}
        for code, row in self.table("potion").items():
            if category is not None and row.get("category") != category:
                continue
            amount = int(player["items"].get(row.get("itemID")) or 0)
            if amount > 0:
                result[code] = {"amount": float(amount)}
        return result

    def potions(self, player: dict, params: dict) -> dict:
        amounts = self.potion_amounts(player)
        # Explicit zero balance for the full-auto-skip potion (never a free grant).
        amounts.setdefault("potion0000102", {"amount": 0.0})
        return {"potions": amounts}

    def supported_goods(self, player: dict, row: dict, index: int = 0) -> dict[str, int]:
        if not row.get("isInitialSale"):
            raise ValueError("shop unlock conditions are not implemented")
        if row.get("isNew") or row.get("discount"):
            raise ValueError("discount sale rules are not implemented")
        ids, amounts = row.get("itemIds"), row.get("quantities")
        if not isinstance(ids, list) or not ids or not isinstance(amounts, list) or len(ids) != len(amounts):
            raise ValueError("invalid shop catalogue quantities")
        if row.get("isSet"):
            if index != 0:
                raise ValueError("set purchases require index zero")
            selected = list(zip(ids, amounts))
        else:
            if index >= len(ids):
                raise ValueError("shop item index out of range")
            selected = [(ids[index], amounts[index])]
        drafts = self.table("item04")
        potion_items = {row.get("itemID") for row in self.table("potion").values()}
        country = player["entity"]["country"]
        result = {}
        for item_id, amount in selected:
            if item_id.startswith("countryshop_"):
                item_id = (self.table("shop_item_country").get(item_id) or {}).get(country)
            if not item_id or item_id not in drafts and item_id not in potion_items:
                raise ValueError("shop delivery category is not implemented")
            if item_id in drafts and (drafts[item_id].get("category") != "draft" or not drafts[item_id].get("enable")):
                raise ValueError("unsupported draft item")
            result[item_id] = result.get(item_id, 0) + integer(amount, 1)
        return result

    @staticmethod
    def costs(row: dict, quantity: int) -> dict[str, int]:
        types, amounts = row.get("costTypes") or [], row.get("costAmounts") or []
        if len(types) != len(amounts):
            raise ValueError("invalid shop catalogue costs")
        costs = {}
        for kind, amount in zip(types, amounts):
            # ShopUpdate.setPrice replaces costAmounts for credit with row.credit;
            # it does not add both prices together.
            amount = row.get("credit") if kind == "credit" else amount
            costs[kind] = costs.get(kind, 0) + integer(amount) * quantity
        if not any(costs.values()):
            raise ValueError("zero-cost shop sale is not enabled")
        return costs

    def shop_items(self, player: dict, params: dict) -> dict:
        category = params.get("category")
        if not isinstance(category, str):
            raise ValueError("shop category required")
        rows = self.table("shop_item")
        # Missing catalogues are asset failures, not an empty successful shop.
        for name in ("item04", "potion", "shop_item_country"):
            self.table(name)
        result = {}
        for code, row in rows.items():
            if row.get("category") != category:
                continue
            try:
                self.supported_goods(player, row)
                self.costs(row, 1)
            except ValueError:
                continue
            result[code] = {"state": "open", "isNewBuyable": False, "discount": False}
        return {"shopItems": result, "recommendedItems": {}}

    def buy_item(self, player: dict, params: dict) -> dict:
        if params.get("storetable") != "shop_item":
            raise ValueError("only the normal shop catalogue is supported")
        quantity = integer(params.get("quantity"), 1)
        index = integer(params.get("index"))
        item_id = params.get("shopItemId")
        if not isinstance(item_id, str):
            raise ValueError("shopItemId required")
        row = self.table("shop_item").get(item_id)
        if not row:
            raise ValueError("shop item not found")
        goods = self.supported_goods(player, row, index)
        costs = self.costs(row, quantity)
        if any(kind not in player["resources"] for kind in costs):
            raise ValueError("unsupported shop currency")
        if any(int(player["resources"][key].get("amount") or 0) < amount for key, amount in costs.items()):
            raise ValueError("insufficient resources")
        for key, amount in costs.items():
            player["resources"][key]["amount"] -= amount
        for key, amount in goods.items():
            player["items"][key] = int(player["items"].get(key) or 0) + amount * quantity
        return {"resources": copy.deepcopy(player["resources"]),
                "result": {key: float(player["items"][key]) for key in goods}}
