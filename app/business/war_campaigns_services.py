"""F-group integration component; not mounted by GameplayService.

Liveness, siege pairings and strategy history read authoritative saved data.
No campaign, troop, schedule, result, reward or default alive value is invented.
The _warCampaigns storage schema is INTERNAL, not original wire protocol.
"""
from __future__ import annotations

import math
import time
from functools import partial
from typing import Any, Callable

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer
from app.business.war_campaigns_views import siege_pairings, strategy_history


class WarCampaignsServices(PlayerServices):
    """Use the existing authentication/load and per-player lock infrastructure.

    A trusted future campaign transaction must write _warCampaigns.strategy:
    {ownerId: str, observedAt: Unix seconds, validUntil: Unix seconds,
     isAlive: bool}. Expiry is an internal freshness boundary, NOT event dates.
    This module intentionally provides no public mutation/import endpoint.
    """

    def __init__(self, service: Any, clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        self.clock = clock

    def register(self, registry: Any) -> None:
        api = "strategy/isAlive"
        registry.register(api, self.service._guard(api, partial(self.read_alive, api)))
        for api, projector in (("siege/getPairings", siege_pairings),
                               ("strategy/getStrategyWinLossRecords", strategy_history)):
            registry.register(api, self.service._guard(api, partial(self.read_records, api, projector)))

    def read_records(self, api: str, projector: Callable[[list[dict]], dict], params: dict, session: dict | None) -> dict:
        """INTERNAL queries[api] record: ownerId/observedAt/validUntil/complete/rows.

        complete=True explicitly certifies a full dataset, including a real empty
        history. No HTTP endpoint writes these snapshots. Future producers must
        publish/invalidate them in their authoritative campaign transaction.
        """
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        if set(params) - {"token"}:
            return self.service._failure(api, "unexpected campaign query parameter")
        campaigns = player.get("_warCampaigns")
        queries = campaigns.get("queries") if isinstance(campaigns, dict) else None
        record = queries.get(api) if isinstance(queries, dict) else None
        if not isinstance(record, dict) or record.get("ownerId") != player_id:
            return self.service._failure(api, "no stub response: authoritative campaign records unavailable")
        start, end = record.get("observedAt"), record.get("validUntil")
        if (record.get("complete") is not True or not isinstance(record.get("rows"), list)
                or not _timestamp(start) or not _timestamp(end) or not start <= self.clock() < end):
            return self.service._failure(api, "no stub response: incomplete or stale campaign records")
        try:
            payload = projector(record["rows"])
        except ValueError as exc:
            return self.service._failure(api, f"no stub response: {exc}")
        return response_shapes.success(api, payload)

    def read_alive(self, api: str, params: dict, session: dict | None) -> dict:
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        # No selectors or client-supplied observations: this endpoint is self-only.
        if set(params) - {"token"}:
            return self.service._failure(api, "unexpected strategy/isAlive parameter")
        campaigns = player.get("_warCampaigns")
        observation = campaigns.get("strategy") if isinstance(campaigns, dict) else None
        if not isinstance(observation, dict) or observation.get("ownerId") != player_id:
            return self.service._failure(api, "no stub response: authoritative strategy observation unavailable")
        start, end = observation.get("observedAt"), observation.get("validUntil")
        if (type(observation.get("isAlive")) is not bool
                or not _timestamp(start) or not _timestamp(end)
                or not start <= self.clock() < end):
            return self.service._failure(api, "no stub response: invalid or stale strategy observation")
        # StrategyHUDController.cs:985-989 unboxes a root boolean.
        # Do not persist normalization on a query, or leak internal metadata.
        return response_shapes.success(api, {"isAlive": observation["isAlive"]})


def _timestamp(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value <= 253402300799 and math.isfinite(value)


def mercenary_hire_cost(defines: dict, count: int) -> int:
    """Verified menu quote only, NOT entry validation or a resource mutation.

    StrategySelect_army.Cost multiplies count by Defines.mercenaryPrice;
    StrategySelect.entryStrategy subtracts that cost in the success callback.
    Force capacity, team eligibility and entry idempotency remain unimplemented.
    """
    count = integer(count)
    if not isinstance(defines, dict) or not defines:
        raise ValueError("stub has no assets: required table defines")
    row = defines.get("mercenaryPrice")
    if not isinstance(row, dict) or "value" not in row:
        raise ValueError("missing defines.mercenaryPrice row/value")
    price = integer(row["value"])
    cost = price * count
    if cost > 2147483647:
        raise ValueError("mercenary quote exceeds client integer range")
    return cost


def command_cost_terms(table: dict, command: str) -> tuple[tuple[str, str, int | float], ...]:
    """Decode original parallel cost arrays, without guessing their formulas.

    Internal integration utility only. `force`, `diffMaxForce` and `fixed`
    remain declarations; this function does not quote or charge any action.
    A missing table is an asset error; a missing row is a reference error.
    """
    if not isinstance(table, dict) or not table:
        raise ValueError("stub has no assets: required table strategy_command")
    if not isinstance(command, str) or command not in table:
        raise ValueError("unknown strategy_command row")
    row = table[command]
    if not isinstance(row, dict):
        raise ValueError("invalid strategy_command row")
    arrays = [row.get(key) for key in ("costTypes", "costCalculationTypes", "costAmounts")]
    if any(not isinstance(array, list) for array in arrays) or len({len(array) for array in arrays}) != 1:
        raise ValueError("invalid strategy_command cost arrays")
    terms = []
    for resource, calculation, amount in zip(*arrays):
        if (not isinstance(resource, str) or not resource
                or not isinstance(calculation, str) or not calculation
                or type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
            raise ValueError("invalid strategy_command cost term")
        terms.append((resource, calculation, amount))
    return tuple(terms)
