"""Internal, event-sourced turfWar enrollment; no combat or settlement engine.

The operator must declare an actual event and its country allocation explicitly.
Neither an old news date, a table row nor a query opens an event. Declaration is
NOT an HTTP endpoint. All fields here are emulator storage, not wire fields.
See research-331/results/f-war for version limits and the I-group transaction.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


def _fail(reason: str) -> None:
    raise ValueError("no stub response: " + reason)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value


def timestamp(value: Any) -> float:
    if (type(value) not in (int, float) or not 0 <= value <= 253402271999
            or not math.isfinite(value)):
        _fail("invalid campaign timestamp")
    return float(value)


def _digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_plan(plan: Any) -> None:
    if not isinstance(plan, dict) or set(plan) != {
        "eventId", "opensAt", "closesAt", "countryTeams", "battlefields", "authorizationRef"
    }:
        _fail("invalid turfWar declaration")
    if not _text(plan["eventId"]) or not _text(plan["authorizationRef"]):
        _fail("event identity and operator authorization reference required")
    if timestamp(plan["opensAt"]) >= timestamp(plan["closesAt"]):
        _fail("invalid turfWar interval")
    countries, fields = plan["countryTeams"], plan["battlefields"]
    if (not isinstance(countries, dict) or not countries
            or any(not _text(k) or k == "none" or v not in ("east", "west")
                   for k, v in countries.items())
            or set(countries.values()) != {"east", "west"}):
        _fail("explicit allocation of countries to both teams required")
    # This component supports the three active slots in the 20140712 table.
    # It does not select three arbitrary rows out of the 111-row catalogue.
    if (not isinstance(fields, dict) or len(fields) != 3
            or any(not _text(k) or not _text(v) or k == "none" or v == "none"
                   for k, v in fields.items()) or len(set(fields.values())) != 3):
        _fail("three distinct active battlefield catalogue IDs required")


def declare_turf_war(*, event_id: str, opens_at: float, closes_at: float,
                     country_teams: dict, authorization_ref: str, now: float,
                     countries: dict, battlefields: dict, catalogue: dict) -> dict:
    """Construct a new declaration for insert-if-absent in an I-owned store.

    country_teams is an operator-approved allocation, NOT a recovered matching
    algorithm. This function has no random/default teams or sample schedule.
    Storage must reject reused IDs, including closed events; do not overwrite.
    """
    for name, table in (("country_setting", countries),
                        ("turf_war_battlefield", battlefields),
                        ("turf_war_battlefield_catalog", catalogue)):
        if not isinstance(table, dict) or not table:
            raise ValueError(f"stub has no assets: required table {name}")
    if not isinstance(country_teams, dict) or set(country_teams) != set(countries):
        _fail("country allocation must cover the supplied country table exactly")
    if any(not isinstance(row, dict) or row.get("id") != key
           for key, row in countries.items()):
        _fail("invalid country table reference")
    fields = {}
    for slot, row in battlefields.items():
        if (not isinstance(row, dict) or row.get("id") != slot
                or not _text(row.get("catalogId"))):
            _fail("invalid active battlefield row")
        catalog_id = row["catalogId"]
        catalog_row = catalogue.get(catalog_id)
        if not isinstance(catalog_row, dict) or catalog_row.get("id") != catalog_id:
            _fail("active battlefield references an unavailable catalogue row")
        fields[slot] = catalog_id
    plan = dict(eventId=event_id, opensAt=timestamp(opens_at), closesAt=timestamp(closes_at),
                countryTeams=copy.deepcopy(country_teams), battlefields=fields,
                authorizationRef=authorization_ref)
    _validate_plan(plan)
    created = timestamp(now)
    if created >= plan["opensAt"]:
        _fail("declaration must precede opening; historical schedule import unsupported")
    return {"version": 1, "plan": plan, "planHash": _digest(plan),
            "declaredAt": created, "journal": []}


def replay_turf_war(event: Any) -> tuple[dict[str, dict], bool]:
    """Validate the whole journal before projecting any member or accepting writes.

    No manually seeded query snapshot can substitute for an entry event. The
    checksum catches accidental plan edits; it is not an authorization signature.
    """
    if (not isinstance(event, dict) or set(event) != {
            "version", "plan", "planHash", "declaredAt", "journal"}
            or type(event["version"]) is not int or event["version"] != 1):
        _fail("turfWar event unavailable or unsupported schema")
    plan = event["plan"]
    _validate_plan(plan)
    if event["planHash"] != _digest(plan):
        _fail("turfWar declaration changed")
    last = timestamp(event["declaredAt"])
    if last >= plan["opensAt"] or not isinstance(event["journal"], list):
        _fail("invalid turfWar journal")
    members: dict[str, dict] = {}
    closed = False
    for seq, row in enumerate(event["journal"], 1):
        if (not isinstance(row, dict) or type(row.get("seq")) is not int
                or row["seq"] != seq or closed):
            _fail("invalid turfWar journal sequence")
        at = timestamp(row.get("at"))
        if at < last:
            _fail("campaign time moved backwards")
        last = at
        kind = row.get("kind")
        if kind == "closed":
            if set(row) != {"seq", "kind", "at"} or at < plan["closesAt"]:
                _fail("invalid campaign closure")
            closed = True
            continue
        if not plan["opensAt"] <= at < plan["closesAt"]:
            _fail("enrollment outside the declared interval")
        pid = row.get("playerId")
        if not _text(pid):
            _fail("invalid enrollment player")
        if kind == "entered":
            country = row.get("country")
            if (set(row) != {"seq", "kind", "at", "playerId", "country"}
                    or not _text(country) or country not in plan["countryTeams"] or pid in members):
                _fail("invalid or duplicate enrollment")
            members[pid] = {"country": country, "team": plan["countryTeams"][country],
                            "battlefield": "none"}
        elif kind == "selected":
            field = row.get("battlefield")
            if (set(row) != {"seq", "kind", "at", "playerId", "battlefield"}
                    or not _text(field) or field not in plan["battlefields"].values()
                    or pid not in members or members[pid]["battlefield"] != "none"):
                _fail("invalid or repeated battlefield selection")
            members[pid]["battlefield"] = field
        else:
            _fail("unsupported campaign event kind")
    return members, closed


def turf_war_phase(event: dict, now: float) -> str:
    """INTERNAL phase only; closed does not mean resolved or reward-eligible."""
    _, closed = replay_turf_war(event)
    now = timestamp(now)
    last = event["journal"][-1]["at"] if event["journal"] else event["declaredAt"]
    if now < last:
        _fail("campaign time moved backwards")
    if closed or now >= event["plan"]["closesAt"]:
        return "closed"
    return "scheduled" if now < event["plan"]["opensAt"] else "open"


def append_turf_event(event: dict, kind: str, now: float, **values: Any) -> None:
    """Validate a detached candidate before mutating the transaction's draft."""
    candidate = copy.deepcopy(event)
    candidate["journal"].append(dict(seq=len(candidate["journal"]) + 1,
                                     kind=kind, at=timestamp(now), **values))
    replay_turf_war(candidate)
    event["journal"] = candidate["journal"]


def close_turf_war(event: dict, now: float) -> None:
    """Explicit scheduler action: archive enrollment, never invent a result."""
    if turf_war_phase(event, now) != "closed":
        _fail("campaign has not ended")
    if not replay_turf_war(event)[1]:
        append_turf_event(event, "closed", now)
