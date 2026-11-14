"""C-group opt-in handlers; not mounted by GameplayService.

Evidence and conservative support limits: docs/analysis/parallel-342/c-card-growth/.
Uses PlayerServices.call and GameplayService's lock/save/revision boundary.
"""
from __future__ import annotations

import time
from functools import partial
from typing import Any

from app.business.decks import KINDS, character_id
from app.business.player_services import PlayerServices, integer

SOUL_COLORS = ("red", "blue", "purple", "yellow", "green", "black", "white")


class CardGrowthServices(PlayerServices):
    def register(self, registry: Any) -> None:
        handlers = {
            "deck/sellCharacters": partial(self.sell, kind="characters", table="character", field="characterIds"),
            "deck/sellEquips": partial(self.sell, kind="equips", table="equip", field="equipIds"),
            "deck/transferStoreCharacters": self.transfer,
            "politic/lottery/getSouls": self.souls,
        }
        for api, action in handlers.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def call(self, api: str, action: Any, params: dict, session: dict | None) -> dict:
        result = super().call(api, action, params, session)
        if api == "politic/lottery/getSouls" and "errorReason" not in result:
            # onikujiWork.initSoul casts EVERY root value to double.
            return {color: result[color] for color in SOUL_COLORS}
        return result

    @staticmethod
    def ids(value: Any, *, allow_empty: bool = False) -> list[str]:
        if not isinstance(value, list) or not allow_empty and not value:
            raise ValueError("card ids must be an array")
        ids = [character_id(item) for item in value]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate card ids")
        return ids

    @staticmethod
    def references(player: dict, kind: str) -> set[str]:
        """Conservative service eligibility, NOT an original auction contract."""
        decks = player.get("decks") or {}
        result = set()
        if kind == "characters" and (decks.get("avatar") or {}).get("id"):
            result.add(character_id(decks["avatar"]["id"]))
        field = "ids" if kind == "characters" else "equip"
        for name in KINDS:
            for deck in (decks.get(name) or {}).values():
                for value in (deck.get(field) or {}).values():
                    if value != "empty":
                        result.add(character_id(value))
        return result

    @staticmethod
    def require_player(player: dict) -> None:
        if not (player.get("entity") or {}).get("created"):
            raise ValueError("created player required")

    def sell(self, player: dict, params: dict, *, kind: str, table: str, field: str) -> dict:
        self.require_player(player)
        ids = self.ids(params.get(field))
        if len(ids) > 8:
            raise ValueError("sale batch exceeds client eight-card limit")
        owned = player.get(kind) or {}
        if kind == "characters" and set(owned) & set(player.get("storedCharacters") or {}):
            raise ValueError("no stub response: duplicate inventory identity requires repair")
        blocked = self.references(player, kind) | set((player.get("protectedCards") or {}).get(kind) or [])
        if any(key not in owned or key in blocked for key in ids):
            raise ValueError("card is unowned, protected or referenced by a deck/avatar")
        rows = self.table(table)
        total = 0
        for key in ids:
            row = rows.get(owned[key].get("baseId"))
            if not row or "sellPrice" not in row:
                # A table exists but its referenced row/field is invalid, not a missing asset file.
                raise ValueError("no stub response: sale table row or sellPrice missing")
            total += integer(row["sellPrice"])
        gold = player["resources"]["gold"]
        amount = integer(gold["amount"])
        if amount + total > integer(gold["maxAmount"]):
            # Overflow settlement is not proven: reject the entire sale.
            raise ValueError("no stub response: sale gold overflow is unsupported")
        for key in ids:
            del owned[key]
        gold["amount"] = amount + total
        player.setdefault("counters", {})["characterCount" if kind == "characters" else "equipCount"] = len(owned)
        return {"sellPrice": float(total), field: {str(i): float(key) for i, key in enumerate(ids)}}

    def transfer(self, player: dict, params: dict) -> dict:
        self.require_player(player)
        into = self.ids(params.get("toStoreIds"), allow_empty=True)
        out = self.ids(params.get("toCharacterIds"), allow_empty=True)
        if not into and not out or set(into) & set(out):
            raise ValueError("nonempty, disjoint transfer directions required")
        owned, stored = player.get("characters") or {}, player.get("storedCharacters") or {}
        if set(owned) & set(stored):
            raise ValueError("no stub response: duplicate inventory identity requires repair")
        if any(key not in owned for key in into) or any(key not in stored for key in out):
            raise ValueError("transfer source does not own requested card")
        if set(into) & self.references(player, "characters"):
            raise ValueError("cannot store a deck/avatar character")
        info = player.get("characterStore") or {}
        # nextOpenLimit is supplied by the server; no C# linkage proves the defines
        # interval is the original server default. Require an explicit saved policy.
        if "nextOpenLimit" not in info:
            raise ValueError("no stub response: warehouse cooldown policy not configured")
        interval = integer(info["nextOpenLimit"], 1)
        now = int(time.time())
        if now - integer(info.get("lastOpenDate", 0), maximum=9007199254740991) <= interval:
            raise ValueError("warehouse is cooling down")
        if info.get("extendSlot") or info.get("extendLimit"):
            raise ValueError("no stub response: paid warehouse extension unsupported")
        row = self.table("defines").get("default_extend_character_store")
        if not row or "value" not in row:
            raise ValueError("no stub response: warehouse capacity table row missing")
        limit = integer(row["value"])
        carrying = integer(self.service._possession_limits(player)["character"]["result"])
        if len(stored) + len(into) - len(out) > limit or len(owned) + len(out) - len(into) > carrying:
            raise ValueError("transfer exceeds destination capacity")
        for key in into:
            stored[key] = owned.pop(key)
        for key in out:
            owned[key] = stored.pop(key)
        player["characters"], player["storedCharacters"] = owned, stored
        # Commit time as lastOpenDate is an explicitly documented compatibility policy.
        player["characterStore"] = {**info, "lastOpenDate": now, "nextOpenLimit": interval}
        player.setdefault("counters", {})["characterCount"] = len(owned)
        return self.storage_info(player, {})

    @staticmethod
    def souls(player: dict, params: dict) -> dict:
        CardGrowthServices.require_player(player)
        saved = player.get("souls") or {}
        # Existing profile uses the same balance mapping; absent means zero, never a grant.
        return {color: float(integer(saved.get(color, 0))) for color in SOUL_COLORS}
