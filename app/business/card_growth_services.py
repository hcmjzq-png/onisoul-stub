"""C-group handlers; GameplayService mounts sales and saved soul balances only.

Evidence and support limits: docs/analysis/research-331/results/c-card-growth/.
Uses PlayerServices.call and GameplayService's lock/save/revision boundary.
"""
from __future__ import annotations

import copy
import hashlib
import time
from functools import partial
from typing import Any, Callable

from app.business.decks import KINDS, character_id
from app.business.player_services import PlayerServices, integer
from app.business.card_growth_transactions import OperationContext, settle_once

SOUL_COLORS = ("red", "blue", "purple", "yellow", "green", "black", "white")


class CardGrowthServices(PlayerServices):
    def register_mutations(
        self, registry: Any, *, operation_context: Callable[[], OperationContext | None]
    ) -> None:
        """Candidate registration requiring a real, reviewed transport adapter.

        Normal GameplayService.register does not invoke this method. The original
        client has no nonce. Test providers must never become production defaults.
        """
        for api in ("politic/support_item/useDopingItem",
                    "politic/support_item/useDopingRemoveItem", "deck/sellTactics"):
            registry.register(api, partial(self.mutate, api, operation_context))

    def mutate(self, api: str, provider: Callable[[], OperationContext | None],
               params: dict, session: dict | None) -> dict:
        request = copy.deepcopy(params)

        def action(player: dict, body: dict) -> dict:
            self.require_player(player)
            if api not in ("politic/support_item/useDopingItem",
                           "politic/support_item/useDopingRemoveItem", "deck/sellTactics"):
                raise ValueError("no stub response: unsupported card growth mutation")
            context = provider()
            if not isinstance(context, OperationContext):
                raise ValueError("no stub response: trusted operation context unavailable")
            context.validate(self.service._player_id(session), api, body)
            if api == "deck/sellTactics":
                return settle_once(player, context, partial(
                    self._sell_tactics, params=body, operation_id=context.operation_id))
            handler = self.use_doping if api.endswith("/useDopingItem") else self.remove_doping
            return settle_once(player, context, partial(handler, params=body))

        return self.service._guard(api, partial(self.call, api, action))(request, session)

    def sell_tactics_with_receipt(
        self, params: dict, session: dict | None, *, operation_id: str
    ) -> dict:
        """Integration-only transaction entry, NOT an original request field.

        The trusted dispatcher must supply a durable ID, identical for transport
        retries and different for each new intent. Never derive it from the body,
        a token or a time bucket. The original client supplies no such ID, so this
        method is deliberately NOT registered as a public HTTP handler.
        """
        api = "deck/sellTactics"
        # Snapshot before taking the lock: the caller cannot mutate the request
        # between validation, settlement and receipt persistence.
        request = copy.deepcopy(params)
        action = partial(self._sell_tactics, operation_id=operation_id)
        return self.service._guard(api, partial(self.call, api, action))(request, session)

    def register(self, registry: Any, *, apis: frozenset[str] | None = None) -> None:
        handlers = {
            "deck/sellCharacters": partial(self.sell, kind="characters", table="character", field="characterIds"),
            "deck/sellEquips": partial(self.sell, kind="equips", table="equip", field="equipIds"),
            "deck/transferStoreCharacters": self.transfer,
            "politic/lottery/getSouls": self.souls,
        }
        for api, action in handlers.items():
            if apis is None or api in apis:
                registry.register(api, self.service._guard(api, partial(self.call, api, action)))

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

    def _sell_tactics(self, player: dict, params: dict, *, operation_id: str) -> dict:
        """All quantities, gold and receipt commit in PlayerServices.call's save."""
        self.require_player(player)
        if (not isinstance(operation_id, str) or not operation_id.isascii()
                or not 1 <= len(operation_id) <= 128
                or any(not (c.isalnum() or c in "-_.:") for c in operation_id)):
            raise ValueError("no stub response: trusted sale operation id required")
        raw = params.get("tactics")
        if set(params) - {"token", "tactics"}:
            raise ValueError("unexpected tactic sale request field")
        if not isinstance(raw, dict) or not 1 <= len(raw) <= 8:
            raise ValueError("tactics must contain one to eight card types")
        if any(not isinstance(key, str) or not key for key in raw):
            raise ValueError("tactic ids must be nonempty strings")
        quantities = {key: integer(value, 1) for key, value in sorted(raw.items())}
        # Service-internal durable ledger; not sent as a protocol field. No TTL
        # or eviction: expiring a receipt would make a delayed retry spend again.
        receipts = player.get("cardGrowthTacticSales", {})
        if not isinstance(receipts, dict):
            raise ValueError("no stub response: invalid tactic sale ledger")
        receipt_key = hashlib.sha256(operation_id.encode("ascii")).hexdigest()
        if receipt_key in receipts:
            receipt = receipts[receipt_key]
            if not isinstance(receipt, dict) or not isinstance(receipt.get("quantities"), dict):
                raise ValueError("no stub response: invalid tactic sale receipt")
            if receipt["quantities"] != quantities:
                raise ValueError("sale operation id was already used for different quantities")
            # DeckSale_Tactics adds sellPrice and subtracts tactics on EVERY
            # success. Replaying the old payload corrupts the client's balances.
            raise ValueError("sale already committed; refresh tactics and resources")
        # Bound this initial internal ledger without silently evicting receipts.
        # This is a service support limit, not an original game limit.
        if len(receipts) >= 1024:
            raise ValueError("no stub response: tactic sale receipt archive required")
        owned = player.get("tactics") or {}
        referenced = set()
        for kind in KINDS:
            for deck in ((player.get("decks") or {}).get(kind) or {}).values():
                referenced.update((deck.get("tactics") or {}).values())
        if any(key not in owned or key in referenced for key in quantities):
            raise ValueError("tactic is unowned or referenced by a deck")
        rows = self.table("tactics")
        remaining = {}
        total = 0
        for key, quantity in quantities.items():
            remaining[key] = integer(owned[key].get("amount", 0)) - quantity
            if remaining[key] < 0:
                raise ValueError("insufficient tactic quantity")
            row = rows.get(key)
            if not row or "sellPrice" not in row:
                raise ValueError("no stub response: tactic sale table row or sellPrice missing")
            total += quantity * integer(row["sellPrice"])
        gold = player["resources"]["gold"]
        amount = integer(gold["amount"])
        if total > 2147483647 or amount + total > integer(gold["maxAmount"]):
            raise ValueError("no stub response: sale gold overflow is unsupported")
        # Callback subtracts sold quantities; zero rows may remain in inventory.
        payload = {"sellPrice": float(total),
                   "tactics": {key: float(value) for key, value in quantities.items()}}
        for key, value in remaining.items():
            owned[key]["amount"] = value
        gold["amount"] = amount + total
        player["cardGrowthTacticSales"] = {**receipts, receipt_key: {
            "quantities": quantities, "payload": copy.deepcopy(payload)}}
        return payload

    def doping_target(self, player: dict, params: dict, *, remove: bool) -> tuple[str, dict]:
        self.require_player(player)
        allowed = {"token", "potionId", "characterId"} | (set() if remove else {"count"})
        if set(params) - allowed:
            raise ValueError("unexpected doping request field")
        key = character_id(params.get("characterId"))
        owned, stored = player.get("characters", {}), player.get("storedCharacters", {})
        if not isinstance(owned, dict) or not isinstance(stored, dict) or set(owned) & set(stored):
            raise ValueError("no stub response: invalid or duplicate character inventory")
        target = owned.get(key)
        if not isinstance(target, dict):
            raise ValueError("doping requires an owned carried character")
        # Conservative support policy: do not change protected or assigned cards.
        # This is not a claim that original item usage shares material-sale rules.
        if (key in self.references(player, "characters")
                or key in (player.get("protectedCards", {}).get("characters", []))):
            raise ValueError("character is protected or referenced by a deck/avatar")
        if target.get("baseId") not in self.table("character"):
            raise ValueError("no stub response: character base row missing")
        for stat in ("atk", "def", "int"):
            if integer(target.get(stat)) < integer(target.get(stat + "Add")):
                raise ValueError("no stub response: inconsistent character doping totals")
        return key, target

    def doping_row(self, potion_id: str, *, remove: bool = False) -> dict:
        supported = ({"potion0000201"} if remove else
                     {f"potion00004{i:02d}" for i in range(1, 21)})
        if not isinstance(potion_id, str) or potion_id not in supported:
            raise ValueError("no stub response: unsupported doping potion")
        row = self.table("potion").get(potion_id)
        if (not isinstance(row, dict) or row.get("id") != potion_id
                or row.get("category") != ("dopingRemove" if remove else "doping")
                or not isinstance(row.get("itemID"), str) or not row["itemID"].startswith("item07_")):
            raise ValueError("no stub response: invalid doping potion row")
        if not remove:
            uses, effects = row.get("uses"), row.get("effects")
            if (uses not in (["atk"], ["def"], ["int"], ["atk", "def", "int"])
                    or not isinstance(effects, list) or len(effects) != len(uses)
                    or row.get("range") != [-1, -1]):
                raise ValueError("no stub response: unsupported doping effects or range")
            for effect in effects:
                integer(effect, 1)
        return row

    def use_doping(self, player: dict, params: dict) -> dict:
        """Original 20 stones, full batches only: no clipping or guessed refunds."""
        _key, target = self.doping_target(player, params, remove=False)
        potion_id = params.get("potionId")
        row = self.doping_row(potion_id)
        count = integer(params.get("count"), 1, 10)
        if count not in (1, 5, 10):
            raise ValueError("unsupported doping batch; client offers 1, 5 or 10")
        grade, level = integer(target.get("grade"), 1), integer(target.get("level"), 1)
        level_row = self.table("characterLevel").get(f"{grade}_{level}")
        if not isinstance(level_row, dict) or "cap" not in level_row:
            raise ValueError("no stub response: character level cap row missing")
        cap = integer(level_row["cap"], 1)
        items = player.get("items")
        if not isinstance(items, dict):
            raise ValueError("no stub response: invalid item inventory")
        remaining = integer(items.get(row["itemID"], 0)) - count
        if remaining < 0:
            raise ValueError("insufficient doping items")
        changed = copy.deepcopy(target)
        for stat, effect in zip(row["uses"], row["effects"]):
            delta = count * integer(effect, 1)
            if integer(target[stat]) + delta > cap:
                raise ValueError("no stub response: partial or over-cap doping unsupported")
            changed[stat] = target[stat] + delta
            changed[stat + "Add"] = target[stat + "Add"] + delta
        items[row["itemID"]] = remaining
        target.update(changed)
        return {"potion": {potion_id: {"amount": float(remaining)}},
                "character": copy.deepcopy(target)}

    def remove_doping(self, player: dict, params: dict) -> dict:
        """Preview's descending-effect conversion, only exactly representable adds."""
        _key, target = self.doping_target(player, params, remove=True)
        potion_id = params.get("potionId")
        bell = self.doping_row(potion_id, remove=True)
        items = player.get("items")
        if not isinstance(items, dict):
            raise ValueError("no stub response: invalid item inventory")
        bell_left = integer(items.get(bell["itemID"], 0)) - 1
        if bell_left < 0:
            raise ValueError("insufficient removal items")
        refunds, balances, changed = {}, {potion_id: {"amount": float(bell_left)}}, copy.deepcopy(target)
        item_balances = {bell["itemID"]: bell_left}
        for stat, first in (("atk", 1), ("def", 6), ("int", 11)):
            remaining = integer(target[stat + "Add"])
            rows = [(f"potion00004{i:02d}", self.doping_row(f"potion00004{i:02d}"))
                    for i in range(first, first + 5)]
            for pid, row in sorted(rows, key=lambda pair: pair[1]["effects"][0], reverse=True):
                if row["uses"] != [stat]:
                    raise ValueError("no stub response: inconsistent refund stone row")
                amount, remaining = divmod(remaining, integer(row["effects"][0], 1))
                if not amount:
                    continue
                item_id = row["itemID"]
                if item_id in item_balances:
                    raise ValueError("no stub response: overlapping refund item references")
                total = integer(items.get(item_id, 0)) + amount
                integer(total)  # Reject overflow atomically; never route to an invented inbox.
                refunds[pid], balances[pid] = float(amount), {"amount": float(total)}
                item_balances[item_id] = total
            if remaining:
                raise ValueError("no stub response: nonrepresentable doping remainder")
            changed[stat] = target[stat] - target[stat + "Add"]
            changed[stat + "Add"] = 0
        if not refunds:
            raise ValueError("character has no removable doping")
        items.update(item_balances)
        target.update(changed)
        return {"addItems": refunds, "changeItems": balances, "character": copy.deepcopy(target)}

    @staticmethod
    def souls(player: dict, params: dict) -> dict:
        CardGrowthServices.require_player(player)
        saved = player.get("souls") or {}
        # Existing profile uses the same balance mapping; absent means zero, never a grant.
        return {color: float(integer(saved.get(color, 0))) for color in SOUL_COLORS}
