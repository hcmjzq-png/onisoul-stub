"""Uninstalled D-group resource-auction read services.

Original protocol: WebApiClient.cs:4423-4456; AuctionDataManager.cs:775-807,
1070-1121. Snapshot classes, expiry calculation, tie breaking and bounds are
server implementation choices, NOT recovered server schema or trading rules.
The integrator must supply one consistent public-listing snapshot. No default
empty market, inventory grants, taxes, write handlers or cross-player commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from app.business.player_services import PlayerServices


LONG_MAX = 2**63 - 1
RESOURCE_TYPES = frozenset(("gold", "food", "wood", "iron"))


def auction_integer(value: Any, minimum: int = 0, maximum: int = LONG_MAX) -> int:
    """Accept decimal strings used by the client, never bool/fraction/NaN."""
    if isinstance(value, str):
        if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
            raise ValueError("invalid auction integer")
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid auction integer")
    return value


@dataclass(frozen=True)
class ResourceListing:
    """Internal public snapshot row; item_sn identifies the listing, not owner."""

    item_sn: str
    resource_type: str
    price: int
    num: int
    period: int
    expires_at: int


@dataclass(frozen=True)
class ResourceSnapshot:
    """Internal contract: all active public rows and timestamp from one read."""

    observed_at: int
    listings: tuple[ResourceListing, ...]


class EconomyServices(PlayerServices):
    def __init__(self, service: Any,
                 resource_snapshot: Callable[[], ResourceSnapshot] | None = None) -> None:
        super().__init__(service)
        self.resource_snapshot = resource_snapshot

    def register(self, registry: Any) -> None:
        # Registry preserves final bodies. These consumers require bare maps;
        # shared response_shapes changes belong to the integration branch.
        for name, search in (("auctionResourceBrowse", False), ("auctionResourceSearch", True)):
            api = "auction/" + name
            registry.register(api, self.service._guard(api, partial(self.resource_query, search=search)))

    def resource_query(self, params: dict, session: dict | None, *, search: bool) -> dict:
        if not self.service._player_id(session):
            return {"errorReason": "authentication required"}
        # Read-only: do not normalize/save a player on a market query. The HTTP
        # session layer authenticates the token, as for existing PlayerServices.
        try:
            return self._resource_query(params, search=search)
        except ValueError as exc:
            return {"errorReason": str(exc)}

    def _resource_query(self, params: dict, *, search: bool) -> dict:
        page = auction_integer(params.get("page_index"), maximum=2147483647)
        # 300 is the original resource browser page size; cap is a local limit.
        size = auction_integer(params.get("item_per_page"), minimum=1, maximum=300)
        sort = params.get("sortby")
        order = params.get("order")
        if sort not in ("credit", "amount", "remain_time") or order not in ("ascending", "descending"):
            raise ValueError("unsupported auction sort/order")
        kind, low_price, high_price, low_amount, high_amount = "all", 0, LONG_MAX, 0, LONG_MAX
        if search:
            kind = params.get("resource_type")
            if kind not in (*RESOURCE_TYPES, "all"):
                raise ValueError("unsupported auction resource")
            low_price, high_price, low_amount, high_amount = (
                auction_integer(params.get(key))
                for key in ("price_min", "price_max", "amount_min", "amount_max")
            )
            if low_price > high_price or low_amount > high_amount:
                raise ValueError("reversed auction range")
        if self.resource_snapshot is None:
            raise ValueError("no stub response: resource auction snapshot provider is not integrated")
        snapshot = self.resource_snapshot()
        if not isinstance(snapshot, ResourceSnapshot) or not isinstance(snapshot.listings, tuple):
            raise ValueError("invalid internal auction snapshot")
        now = auction_integer(snapshot.observed_at)
        rows, seen = [], set()
        for row in snapshot.listings:
            if not isinstance(row, ResourceListing):
                raise ValueError("invalid internal auction listing")
            if not isinstance(row.item_sn, str) or not row.item_sn or row.item_sn in seen:
                raise ValueError("invalid or duplicate internal listing id")
            seen.add(row.item_sn)
            if row.resource_type not in RESOURCE_TYPES:
                raise ValueError("invalid internal auction resource")
            for value in (row.price, row.num, row.period):
                auction_integer(value, minimum=1)
            expiry = auction_integer(row.expires_at)
            if expiry <= now or kind != "all" and kind != row.resource_type:
                continue
            if low_price <= row.price <= high_price and low_amount <= row.num <= high_amount:
                rows.append(row)
        field = {"credit": "price", "amount": "num", "remain_time": "expires_at"}[sort]
        # A stable listing-id tie break is local policy, not an original rule.
        rows.sort(key=lambda row: row.item_sn)
        rows.sort(key=lambda row: getattr(row, field), reverse=order == "descending")
        selected = rows[page * size:(page + 1) * size]
        # Root numeric keys are display slots (ParseSingleResourceData); item_sn
        # carries the buy identifier. String scalars preserve Int64 precision.
        return {str(index): {"item_sn": row.item_sn, "resource_type": row.resource_type,
                             "price": str(row.price), "num": str(row.num),
                             "period": str(row.period), "remain_time": str(row.expires_at - now)}
                for index, row in enumerate(selected)}
