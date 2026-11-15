"""Projections of trusted saved campaign data, never a pairing/settlement engine.

Only fields read by original HTML mediators are emitted. The caller must obtain
rows from an authoritative producer; absence of rows is not an empty campaign.
"""
from __future__ import annotations

import struct
from typing import Any

from app.business.player_services import integer


def _map(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("campaign record must be an object")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("campaign identifier must be a nonempty string")
    return value


def _indexed(value: Any, counts: tuple[int, ...]) -> dict:
    value = _map(value)
    if len(value) not in counts or set(value) != {str(i) for i in range(len(value))}:
        raise ValueError("campaign country slots are incomplete")
    return value


def _client_rate(value: Any) -> int:
    # HTMLStrategyMatchMediator_History.cs:237-239 -> HashAccessFuncs.getInt:
    # parse float32, then cast to Int32. Preserve authoritative values or fail;
    # this is a projection support boundary, not an original rating cap.
    value = integer(value, minimum=-2147483648)
    if struct.unpack("!f", struct.pack("!f", value))[0] != value:
        raise ValueError("campaign rate cannot be represented by client Int32/float32")
    return value


def siege_pairings(rows: list[dict]) -> dict:
    """HTMLSiegeMediator.request: root pairings, numeric slots from zero.

    Supports the observed single defender and one/two attackers shape only.
    Display ranks, translated names and isMe are created by the client.
    """
    pairings = {}
    for index, row in enumerate(rows):
        row = _map(row)
        pairings[str(index)] = {
            side: {key: _text(value) for key, value in
                   _indexed(row.get(side), counts).items()}
            for side, counts in (("defender", (1,)), ("attacker", (1, 2)))
        }
    return {"pairings": pairings}


def strategy_history(rows: list[dict]) -> dict:
    """HTMLStrategyMatchMediator_History.analize full-history projection.

    Ordering comes from the trusted producer. No sorting by guessed cycle,
    default winner, reward, country matching or rating computation is performed.
    This bounded component emits totalCount equal to the complete stored rows;
    pagination semantics of the original service are unknown.
    """
    records = {}
    for index, row in enumerate(rows):
        row = _map(row)
        opened = row.get("openTime")
        # DateTime.AddSeconds consumes this value. Bound to the client date range.
        if type(opened) not in (int, float) or not 0 <= opened <= 253402271999:
            raise ValueError("invalid history openTime")
        decisions = _map(row.get("decisions"))
        if not decisions or set(decisions) != {f"match_{i:02}" for i in range(1, len(decisions) + 1)}:
            raise ValueError("history decisions must be contiguous from match_01")
        projected = {}
        for key, decision in decisions.items():
            decision = _map(decision)
            match = {"winner": _text(decision.get("winner"))}
            for side, counts in (("a", (1,)), ("b", (1, 2))):
                countries = _indexed(decision.get(side), counts)
                match[side] = {}
                for slot, country in countries.items():
                    country = _map(country)
                    match[side][slot] = {
                        "countryId": _text(country.get("countryId")),
                        "rate": _client_rate(country.get("rate")),
                    }
            projected[key] = match
        records[str(index)] = {"openTime": opened, "decisions": projected}
    return {"totalCount": len(records), "records": records}
