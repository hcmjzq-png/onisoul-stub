"""Resource escrow component for I's atomic(player_ids=..., shared_keys=...) UoW.

Not registered as HTTP handlers. Rules, authenticated actor, stable operation ID
and consistent shared-record reader must be supplied by integration. Fee rates,
level/slot limits and direct delivery are explicit policies, not recovered facts.
No production defaults and no independent player saves inside a transaction.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import hashlib
import json
import time
from typing import Any, Callable

from app.business.economy_services import (RESOURCE_TYPES, ResourceListing,
                                           ResourceSnapshot, auction_integer)


MARKET_KEY = ("economy", "resource-market-v1")
MAX_AMOUNT = 2147483647  # Existing player resource/client int bound.


@dataclass(frozen=True)
class ResourceMarketRules:
    base_tax: str
    amount_multiplier: str
    seller_ratio: str
    minimum_level: int
    slot_count: int
    periods: tuple[int, ...]
    evidence: str
    delivery: str  # Must explicitly opt into direct-refuse-overflow.


class ResourceMarket:
    def __init__(self, *, atomic: Callable[..., Any] | None = None,
                 read_market: Callable[[], dict | None] | None = None,
                 rules: ResourceMarketRules | None = None,
                 clock: Callable[[], int] | None = None) -> None:
        self.atomic, self.read_market, self.rules = atomic, read_market, rules
        self.clock = clock or (lambda: int(time.time()))

    @staticmethod
    def identifier(value: Any) -> str:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError("invalid internal identity")
        return value

    def config(self) -> tuple[Decimal, Decimal, Decimal]:
        if self.atomic is None or self.read_market is None or not isinstance(self.rules, ResourceMarketRules):
            raise ValueError("no stub response: atomic resource market/rules not integrated")
        r = self.rules
        if not isinstance(r.evidence, str) or not r.evidence or r.delivery != "direct-refuse-overflow":
            raise ValueError("no stub response: explicit market rule/delivery policy required")
        auction_integer(r.minimum_level, 1, MAX_AMOUNT)
        auction_integer(r.slot_count, 1, 100)
        if not isinstance(r.periods, tuple) or not r.periods:
            raise ValueError("no stub response: market periods required")
        for period in r.periods:
            auction_integer(period, 1, MAX_AMOUNT)
        try:
            if any(not isinstance(v, str) or len(v) > 30 for v in (r.base_tax, r.amount_multiplier, r.seller_ratio)):
                raise ValueError("decimal strings required")
            values = tuple(Decimal(v) for v in (r.base_tax, r.amount_multiplier, r.seller_ratio))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("invalid market coefficients") from exc
        if any(not v.is_finite() or v < 0 or v > MAX_AMOUNT for v in values) or not 0 <= values[2] <= 1:
            raise ValueError("invalid market coefficients")
        return values

    @staticmethod
    def market(value: dict | None, *, create: bool = False) -> dict:
        if value is None and create:
            return {"schema": 1, "listings": {}, "receipts": {}}
        if (not isinstance(value, dict) or value.get("schema") != 1
                or not isinstance(value.get("listings"), dict) or not isinstance(value.get("receipts"), dict)):
            raise ValueError("no stub response: market record absent or invalid")
        occupied = set()
        for key, row in value["listings"].items():
            if (not isinstance(row, dict) or row.get("id") != key
                    or not isinstance(row.get("seller"), str) or not row["seller"]
                    or not isinstance(row.get("resource"), str) or row["resource"] not in RESOURCE_TYPES
                    or row.get("phase") not in ("listed", "sold", "returned")):
                raise ValueError("no stub response: corrupt market listing")
            for field in ("price", "amount", "period"):
                if type(row.get(field)) is not int:
                    raise ValueError("no stub response: corrupt market integer")
                auction_integer(row[field], 1, MAX_AMOUNT)
            for field in ("fee", "sellerProceeds", "slot"):
                auction_integer(row.get(field), 0, MAX_AMOUNT)
            if row["sellerProceeds"] > row["price"]:
                raise ValueError("no stub response: invalid seller proceeds")
            created = auction_integer(row.get("createdAt"), 0, 2**53 - 1)
            if auction_integer(row.get("expiresAt"), 0, 2**53 - 1) != created + row["period"]:
                raise ValueError("no stub response: corrupt market expiry")
            identity = (row["seller"], row["slot"])
            if row["phase"] == "listed":
                if identity in occupied:
                    raise ValueError("no stub response: duplicate occupied market slot")
                occupied.add(identity)
        return value

    def player(self, unit: Any, actor: str) -> dict:
        player = unit.players.get(actor)
        if (not isinstance(player, dict) or player.get("entity", {}).get("playerId") != actor
                or player["entity"].get("created") is not True):
            raise ValueError("created authenticated player required")
        return player

    def eligible(self, player: dict) -> None:
        if auction_integer(player["entity"].get("level"), 1, MAX_AMOUNT) < self.rules.minimum_level:
            raise ValueError("resource market level locked")

    @staticmethod
    def balance(player: dict, resource: str, delta: int) -> None:
        box = player.get("resources", {}).get(resource)
        if not isinstance(box, dict):
            raise ValueError("no stub response: missing resource balance")
        current = auction_integer(box.get("amount"), 0, MAX_AMOUNT)
        # Credit uses existing server/client int capacity, never a payment grant.
        limit = MAX_AMOUNT if resource == "credit" else auction_integer(box.get("maxAmount"), 0, MAX_AMOUNT)
        after = current + delta
        if after < 0:
            raise ValueError("insufficient market balance")
        if delta > 0 and after > limit:
            raise ValueError("no stub response: market delivery overflow; inbox delivery unsupported")
        box["amount"] = after

    def receipt(self, market: dict, actor: str, operation: str, intent: dict) -> str:
        self.identifier(actor)
        self.identifier(operation)
        key = hashlib.sha256(json.dumps([actor, operation], separators=(",", ":")).encode()).hexdigest()
        old = market["receipts"].get(key)
        if old is not None:
            if old.get("intent") != intent or old.get("actor") != actor:
                raise ValueError("operation identity reused with different intent")
            # Error prevents repeated client success callbacks. Receipt is retained.
            raise ValueError("market operation already committed")
        return key

    @staticmethod
    def wire(row: dict, now: int) -> dict:
        return {"item_sn": row["id"], "resource_type": row["resource"], "price": str(row["price"]),
                "num": str(row["amount"]), "period": str(row["period"]),
                "remain_time": str(max(0, row["expiresAt"] - now))}

    def post(self, actor: str, params: dict, operation: str) -> dict:
        base, multiplier, ratio = self.config()
        actor = self.identifier(actor)
        resource = params.get("resource_type")
        if not isinstance(resource, str) or resource not in RESOURCE_TYPES:
            raise ValueError("invalid market resource")
        amount = auction_integer(params.get("num"), 1, MAX_AMOUNT)
        price = auction_integer(params.get("price"), 1, MAX_AMOUNT)
        period = auction_integer(params.get("period"), 1, MAX_AMOUNT)
        slot = auction_integer(params.get("slot_id"), 0, self.rules.slot_count - 1)
        if period not in self.rules.periods:
            raise ValueError("unsupported market duration")
        # Exact decimal policy; original float preview rounding needs capture.
        fee = auction_integer(int((base + Decimal(amount) * multiplier * period / 3600)
                                  .to_integral_value(rounding=ROUND_FLOOR)), 0, MAX_AMOUNT)
        proceeds = int((Decimal(price) * ratio).to_integral_value(rounding=ROUND_FLOOR))
        intent = dict(action="post", resource=resource, amount=amount, price=price, period=period, slot=slot)
        with self.atomic(player_ids=(actor,), shared_keys=(MARKET_KEY,)) as unit:
            market = self.market(unit.records[MARKET_KEY], create=True)
            key = self.receipt(market, actor, operation, intent)
            player = self.player(unit, actor)
            self.eligible(player)
            if any(r["seller"] == actor and r["slot"] == slot and r["phase"] == "listed"
                   for r in market["listings"].values()):
                raise ValueError("market slot is occupied, including expired escrow")
            now = auction_integer(self.clock(), 0, 2**53 - 1)
            listing_id = key  # Unique actor/operation receipt identity; never recycled.
            if listing_id in market["listings"]:
                raise ValueError("market identity collision")
            self.balance(player, resource, -amount)
            self.balance(player, "gold", -fee)
            market["listings"][listing_id] = dict(id=listing_id, seller=actor, slot=slot,
                resource=resource, amount=amount, price=price, period=period, createdAt=now,
                expiresAt=auction_integer(now + period, 0, 2**53 - 1), phase="listed",
                fee=fee, sellerProceeds=proceeds, evidence=self.rules.evidence)
            market["receipts"][key] = dict(actor=actor, intent=intent, listing=listing_id)
            unit.records[MARKET_KEY] = market
            response = {"result": 1, "item_sn": listing_id, "resources": copy.deepcopy(player["resources"])}
        return response  # Never expose success before context COMMIT completes.

    def buy(self, actor: str, item_sn: str, operation: str) -> dict:
        self.config()
        actor, item_sn = self.identifier(actor), self.identifier(item_sn)
        observed = self.market(self.read_market())["listings"].get(item_sn)
        if not isinstance(observed, dict):
            raise ValueError("no stub response: listing not found")
        seller = self.identifier(observed.get("seller"))
        if seller == actor:
            raise ValueError("cannot buy own listing")
        # Discovery is untrusted for settlement; owner and phase are rechecked
        # after I acquires sorted player locks, then the market shared lock.
        with self.atomic(player_ids=tuple(sorted((actor, seller))), shared_keys=(MARKET_KEY,)) as unit:
            market = self.market(unit.records[MARKET_KEY])
            intent = dict(action="buy", listing=item_sn)
            key = self.receipt(market, actor, operation, intent)
            row = market["listings"].get(item_sn)
            now = auction_integer(self.clock(), 0, 2**53 - 1)
            if not row or row["seller"] != seller or row["phase"] != "listed" or now >= row["expiresAt"]:
                raise ValueError("listing unavailable or expired")
            buyer, owner = self.player(unit, actor), self.player(unit, seller)
            self.eligible(buyer)
            self.balance(buyer, "credit", -row["price"])
            self.balance(buyer, row["resource"], row["amount"])
            self.balance(owner, "credit", row["sellerProceeds"])
            row.update(phase="sold", buyer=actor, settledAt=now)
            market["receipts"][key] = dict(actor=actor, intent=intent, listing=item_sn)
            response = {"result": 1, "item_sn": item_sn, "resources": copy.deepcopy(buyer["resources"])}
        return response

    def off_shelf(self, actor: str, item_sn: str, operation: str) -> dict:
        self.config()
        actor, item_sn = self.identifier(actor), self.identifier(item_sn)
        with self.atomic(player_ids=(actor,), shared_keys=(MARKET_KEY,)) as unit:
            market = self.market(unit.records[MARKET_KEY])
            intent = dict(action="off", listing=item_sn)
            key = self.receipt(market, actor, operation, intent)
            row = market["listings"].get(item_sn)
            if not row or row["seller"] != actor or row["phase"] != "listed":
                raise ValueError("listing not owned or already settled")
            owner = self.player(unit, actor)
            self.balance(owner, row["resource"], row["amount"])
            row.update(phase="returned", settledAt=auction_integer(self.clock(), 0, 2**53 - 1))
            market["receipts"][key] = dict(actor=actor, intent=intent, listing=item_sn)
            response = {"result": 1, "item_sn": item_sn, "resources": copy.deepcopy(owner["resources"])}
        return response

    def snapshot(self) -> ResourceSnapshot:
        self.config()
        market = self.market(self.read_market())
        now = auction_integer(self.clock(), 0, 2**53 - 1)
        return ResourceSnapshot(now, tuple(ResourceListing(r["id"], r["resource"], r["price"], r["amount"],
            r["period"], r["expiresAt"]) for r in market["listings"].values()
            if r["phase"] == "listed" and r["expiresAt"] > now))

    def selling(self, actor: str) -> dict:
        base, multiplier, _ = self.config()
        actor = self.identifier(actor)
        # A read transaction pins owner plus shared rows and validates identity.
        with self.atomic(player_ids=(actor,), shared_keys=(MARKET_KEY,)) as unit:
            self.player(unit, actor)
            market = self.market(unit.records[MARKET_KEY])
            now = auction_integer(self.clock(), 0, 2**53 - 1)
            result = {str(r["slot"]): self.wire(r, now) for r in market["listings"].values()
                      if r["seller"] == actor and r["phase"] == "listed"}
            result["params"] = {"base": str(base), "amount_mul": str(multiplier)}
        return result
