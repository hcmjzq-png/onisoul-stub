"""Event producers and projections; dictionaries are internal, never wire fields.

The caller commits returned player + ledger in ONE shared transaction. There is
no SQL, production storage adapter, automatic migration or score-import API.
City policy is deliberately limited to a main city with no politic officers.
Gold-only, no-war national power is an explicit simulator policy, not the full
original national-power economy. Missing coverage is never an empty history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
from typing import Any, Callable, Protocol

from app.business.player_services import integer
from app.business.rankings_periods import METRICS, Period, period_pair, validate_periods
from app.tables import TableError


def client_integer(value: Any) -> int:
    value = integer(value)
    if struct.unpack("!f", struct.pack("!f", value))[0] != value:
        raise ValueError("no stub response: score cannot be represented by client Int32/float32")
    return value


def table(catalog: Any, name: str) -> dict:
    try:
        return catalog.load(name)
    except TableError as exc:
        raise ValueError(f"stub has no assets: required table {name}") from exc


def building_kokudaka(row: dict, level: Any) -> int:
    """BuildingsTableAccessor.cs:637-642, including EVERY float32 operation."""
    grade = integer(row.get("grade"), 1, 10)
    level = integer(level, 1, grade * 10)
    low = integer(row.get("kokudakaMin"))
    high = integer(row.get("kokudakaMax"), low)
    f32 = lambda n: struct.unpack("!f", struct.pack("!f", n))[0]
    step = f32(f32(high - low) / f32(grade * 10 - 1))
    return client_integer(math.floor(f32(f32(low) + f32(f32(level - 1) * step))))


def city_source(player: dict, catalog: Any) -> dict:
    """Current installed/completed buildings; never historical inventory counts.

    Summation/exclusion is compatibility-policy. Skill composition is NOT
    inferred: any occupied politic slot or subcity fails closed for A to extend.
    """
    entity = player["entity"]
    if entity.get("created") is not True or entity.get("currentMapKey") != "map001":
        raise ValueError("no stub response: only created main-city players supported")
    for deck in player.get("decks", {}).get("politic", {}).values():
        if any(value != "empty" for value in deck.get("ids", {}).values()):
            raise ValueError("no stub response: politic skill kokudaka requires A rules")
    rows = table(catalog, "building")
    contributions = {}
    for key, record in sorted(player["buildings"].items()):
        deployed = record.get("deployedMapKey")
        if deployed == "none":
            continue
        if deployed != "map001":
            raise ValueError("no stub response: subcity kokudaka requires A rules")
        status = record.get("status")
        if status == "building":
            continue
        if status not in ("none", "waiting"):
            raise ValueError("no stub response: unsupported building state for kokudaka")
        code = record.get("buildingTypeId")
        row = rows.get(code)
        if not isinstance(row, dict):
            raise ValueError("no stub response: invalid building row reference")
        contributions[key] = {"buildingTypeId": code, "level": record["level"],
                              "score": building_kokudaka(row, record["level"]),
                              "tableSha256": hashlib.sha256(json.dumps(row, sort_keys=True,
                                  ensure_ascii=False).encode()).hexdigest()}
    score = client_integer(sum(row["score"] for row in contributions.values()))
    return {"score": score, "eachKokudaka": {"0": score}, "buildings": contributions,
            "policy": "main-city-no-politic-v1"}


def new_ledger(plans: dict, *, coverage_start: int, realm: str,
               gold_only_no_war: bool = False) -> dict:
    """Explicit new-realm initialization only. Never call this on a missing file."""
    validate_periods(plans)
    integer(coverage_start, 0, 2**53 - 1)
    if not isinstance(realm, str) or not realm or type(gold_only_no_war) is not bool:
        raise ValueError("explicit realm/policy required")
    for metric in METRICS:
        period_pair(plans, metric, coverage_start)
    return {"schema": 1, "revision": 0, "realm": realm, "plans": copy.deepcopy(plans),
            "coverageStart": coverage_start, "watermark": coverage_start,
            "goldOnlyNoWar": gold_only_no_war, "events": {}}


def validate_ledger(ledger: dict, now: int) -> None:
    required = {"schema", "revision", "realm", "plans", "coverageStart", "watermark", "goldOnlyNoWar", "events"}
    if (not isinstance(ledger, dict) or not required <= set(ledger)
            or type(ledger.get("schema")) is not int or ledger["schema"] != 1):
        raise ValueError("no stub response: ranking ledger missing or unsupported")
    validate_periods(ledger["plans"])
    integer(ledger["coverageStart"], 0, 2**53 - 1)
    integer(ledger["watermark"], ledger["coverageStart"], 2**53 - 1)
    integer(ledger["revision"], 0, 2**53 - 1)
    integer(now, ledger["watermark"], 2**53 - 1)
    if not isinstance(ledger["events"], dict):
        raise ValueError("no stub response: invalid event ledger")
    if type(ledger["goldOnlyNoWar"]) is not bool or not isinstance(ledger["realm"], str) or not ledger["realm"]:
        raise ValueError("no stub response: invalid realm policy")
    for key, event in ledger["events"].items():
        if not isinstance(event, dict) or not {"operationId", "at", "kind", "sequence", "playerId", "username", "country"} <= set(event):
            raise ValueError("no stub response: incomplete ranking event")
        if key != event["operationId"] or event["kind"] not in ("city", "gold"):
            raise ValueError("no stub response: invalid ranking event identity/type")
        if any(not isinstance(event[k], str) or not event[k] for k in ("operationId", "playerId", "username", "country")):
            raise ValueError("no stub response: invalid ranking participant")
        integer(event["sequence"], 1)
        integer(event["at"], ledger["coverageStart"], ledger["watermark"])
        if event["kind"] == "city":
            source = event.get("source")
            if not isinstance(source, dict) or not {"score", "eachKokudaka", "buildings", "policy"} <= set(source):
                raise ValueError("no stub response: incomplete city source")
            client_integer(source["score"])
            client_integer(event.get("limit"))
        else:
            gain = integer(event.get("gain"), 1)
            if integer(event.get("gold"), 1000) != gain * 1000:
                raise ValueError("no stub response: invalid charged gold event")
            city = ledger["events"].get(event.get("cityOperation"))
            if (not isinstance(city, dict) or city.get("kind") != "city"
                    or city.get("playerId") != event["playerId"] or city.get("country") != event["country"]
                    or city.get("sequence", 0) >= event["sequence"]):
                raise ValueError("no stub response: missing city provenance for gold event")
    ordered = events_in_order(ledger)
    if ([e["sequence"] for e in ordered] != list(range(1, len(ordered) + 1))
            or any(a["at"] > b["at"] for a, b in zip(ordered, ordered[1:]))):
        raise ValueError("no stub response: invalid ranking event order")


def seal_through(ledger: dict, now: int) -> dict:
    """Persist under I's shared lock before publishing a view/processing a write.

    A delayed writer with a pre-cutover time cannot rewrite a published period.
    This is a watermark, not a fabricated event or score. Read adapters may
    avoid a save if the watermark already equals now.
    """
    validate_ledger(ledger, now)
    updated = copy.deepcopy(ledger)
    if now != updated["watermark"]:
        updated["watermark"] = now
        updated["revision"] += 1
    return updated


def events_in_order(ledger: dict) -> list[dict]:
    # JSON objects have no semantic ordering; DB encoders can sort their keys.
    return sorted(ledger["events"].values(), key=lambda event: event["sequence"])


def _event(player: dict, ledger: dict, operation_id: str, now: int, kind: str) -> dict:
    validate_ledger(ledger, now)
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 200:
        raise ValueError("no stub response: trusted operation identity required")
    if operation_id in ledger["events"]:
        # Success replay would repeat client resource subtraction / gainPoint.
        raise ValueError("no stub response: ranking operation already committed; refresh state")
    entity = player["entity"]
    if entity.get("created") is not True:
        raise ValueError("created player required")
    identity = {k: str(entity[k]) for k in ("playerId", "username", "country")}
    if any(not value for value in identity.values()):
        raise ValueError("ranking identity required")
    # Country transfer is not implemented. Do not silently reattribute history.
    if any(e["playerId"] == identity["playerId"] and e["country"] != identity["country"]
           for e in ledger["events"].values()):
        raise ValueError("no stub response: ranking country transfer unsupported")
    return {**identity, "at": now, "kind": kind, "operationId": operation_id,
            "sequence": len(ledger["events"]) + 1}


def _append(ledger: dict, event: dict) -> dict:
    updated = copy.deepcopy(ledger)
    updated["events"][event["operationId"]] = event
    updated["watermark"] = event["at"]
    updated["revision"] += 1
    return updated


def record_city(player: dict, ledger: dict, catalog: Any, *, operation_id: str,
                now: int) -> tuple[dict, dict]:
    """Run after A's accepted city mutation, before that mutation is committed."""
    event = _event(player, ledger, operation_id, now, "city")
    period_pair(ledger["plans"], "kokudaka", now)
    source = city_source(player, catalog)
    event["source"] = source
    scale = table(catalog, "defines").get("scale_kokudaka_for_dedication", {}).get("value")
    scale = integer(scale, 1)
    updated = copy.deepcopy(player)
    updated["kokudaka"] = source["score"]
    previous_limit = max((e["limit"] for e in ledger["events"].values()
                          if e["kind"] == "city" and e["playerId"] == event["playerId"]), default=0)
    updated["rankingDedicationLimit"] = client_integer(max(previous_limit, source["score"] * scale))
    event["limit"] = updated["rankingDedicationLimit"]
    return updated, _append(ledger, event)


def _rows(ledger: dict, metric: str, period: Period) -> list[dict]:
    if period.start < ledger["coverageStart"]:
        raise ValueError("no stub response: period predates authoritative ledger coverage")
    values = {}
    for event in events_in_order(ledger):
        if event["at"] >= period.end:
            continue
        if metric == "kokudaka" and event["kind"] == "city":
            values[event["playerId"]] = {**{k: event[k] for k in ("playerId", "username", "country")},
                                        "score": event["source"]["score"]}
        elif metric != "kokudaka" and event["kind"] == "gold" and event["at"] >= period.start:
            key = event["country"] if metric == "national_power" else event["playerId"]
            row = values.setdefault(key, {**{k: event[k] for k in ("playerId", "username", "country")}, "score": 0})
            row["score"] += event["gain"]
            row["username"] = event["username"]
    for row in values.values():
        client_integer(row["score"])
    return list(values.values())


def ranked(rows: list[dict], *, national: bool = False) -> list[dict]:
    identity = "country" if national else "playerId"
    ordered = sorted(rows, key=lambda row: (-row["score"], row[identity]))
    result, previous, rank = [], None, 0
    for index, row in enumerate(ordered):
        if row["score"] != previous:
            rank = index + 1
        previous = row["score"]
        client_integer(rank)
        record = {"countryId": row["country"]} if national else {k: row[k] for k in ("playerId", "username", "country")}
        result.append({**record, "score": float(row["score"]), "rank": float(rank)})
    return result


def project_pair(ledger: dict, metric: str, country: str, now: int) -> tuple[list[dict], list[dict] | None]:
    validate_ledger(ledger, now)
    if metric != "kokudaka" and ledger["goldOnlyNoWar"] is not True:
        raise ValueError("no stub response: full dedication/national-power sources unavailable")
    current, last = period_pair(ledger["plans"], metric, now)
    def project(period: Period) -> list[dict]:
        rows = _rows(ledger, metric, period)
        return ranked(rows if metric == "national_power" else [r for r in rows if r["country"] == country],
                      national=metric == "national_power")
    # Unknown pre-coverage history stays unknown; it must not break current-only reads.
    return project(current), project(last) if last and last.start >= ledger["coverageStart"] else None


def donate_gold(player: dict, ledger: dict, catalog: Any, params: dict, *,
                operation_id: str, now: int) -> tuple[dict, dict, dict]:
    """Internal transaction command; original HTTP has NO trustworthy retry ID.

    Only explicit gold-only/no-war realms support this path. Client category,
    article and callbacks are original; the operation ID is server-internal.
    """
    event = _event(player, ledger, operation_id, now, "gold")
    if ledger["goldOnlyNoWar"] is not True:
        raise ValueError("no stub response: gold-only no-war policy disabled")
    if params.get("category") != "gold" or not isinstance(params.get("article"), dict) or set(params["article"]) != {"item11_0000101"}:
        raise ValueError("no stub response: only gold dedication supported")
    amount = integer(params["article"]["item11_0000101"], 1000)
    if amount % 1000:
        raise ValueError("gold dedication must use 1000-gold steps")
    # A city event must already be committed in this shared state. Neither a
    # legacy player.kokudaka nor an artificial limit can authorize expenditure.
    city = next((e for e in reversed(events_in_order(ledger))
                 if e["kind"] == "city" and e["playerId"] == event["playerId"]), None)
    if city is None or city["source"] != city_source(player, catalog):
        raise ValueError("no stub response: current authoritative city event required")
    limit = client_integer(city["limit"])
    period, _ = period_pair(ledger["plans"], "dedication", now)
    current = _rows(ledger, "dedication", period)
    old = next((r["score"] for r in current if r["playerId"] == event["playerId"]), 0)
    gain = amount // 1000
    point = client_integer(old + gain)
    if point > limit:
        raise ValueError("dedication limit exceeded")
    balance = integer(player["resources"]["gold"]["amount"])
    if balance < amount:
        raise ValueError("insufficient gold")
    event.update(gold=amount, gain=gain, cityOperation=city["operationId"], policy="gold-only-no-war-v1")
    updated_ledger = _append(ledger, event)
    # Validate EVERY affected projection before any deduction can be committed.
    projections = {metric: project_pair(updated_ledger, metric, event["country"], now)[0]
                   for metric in ("dedication", "dedication_monthly", "national_power")}
    mine = next(r for r in projections["dedication"] if r["playerId"] == event["playerId"])
    nation = next(r for r in projections["national_power"] if r["countryId"] == event["country"])
    dedication = {"point": float(point), "limit": float(limit), "rank": mine["rank"]}
    updated = copy.deepcopy(player)
    updated["resources"]["gold"]["amount"] = balance - amount
    # Do not persist stale period-sensitive rank/point in the legacy player blob.
    payload = {"gainPoint": float(gain), "bonus": {}, "dedication": dedication,
               "nationalPower": nation["score"], "myRank": {"rank": mine["rank"], "countryRank": nation["rank"]}}
    return updated, updated_ledger, payload


def national_context_data(ledger: dict, country: str, now: int) -> tuple[str, int]:
    """D must hold the shared ledger transaction through its purchase/save."""
    rows, _ = project_pair(ledger, "national_power", country, now)
    period, _ = period_pair(ledger["plans"], "national_power", now)
    power = next((int(r["score"]) for r in rows if r["countryId"] == country), 0)
    return f"{ledger['realm']}:{period.key}", power


Transition = Callable[[dict, dict], tuple[dict, dict, dict]]


class RankingStore(Protocol):
    def transact(self, player_id: str, transition: Transition) -> dict:
        """Lock player then shared ledger; atomically CAS BOTH or commit neither.

        Load latest values inside lock, call transition once, return its payload
        only after durable commit. Conflict/crash must not replay success.
        """
        ...


class RankingTransactions:
    """Production business coordinator; persistence adapter belongs to group I."""

    def __init__(self, store: RankingStore, catalog: Any, clock: Callable[[], int]) -> None:
        self.store, self.catalog, self.clock = store, catalog, clock

    def city(self, player_id: str, action: Callable[[dict], dict], *, operation_id: str) -> dict:
        def transition(player: dict, ledger: dict) -> tuple[dict, dict, dict]:
            now = self.clock()  # acquire time AFTER shared transaction acquisition
            _event(player, ledger, operation_id, now, "city")
            updated = copy.deepcopy(player)
            payload = action(updated)  # A's actual validated building mutation
            updated, result = record_city(updated, ledger, self.catalog,
                                          operation_id=operation_id, now=now)
            return updated, result, {**payload, "kokudaka": float(updated["kokudaka"])}
        return self.store.transact(player_id, transition)

    def gold(self, player_id: str, params: dict, *, operation_id: str) -> dict:
        return self.store.transact(player_id, lambda player, ledger: donate_gold(
            player, ledger, self.catalog, params, operation_id=operation_id, now=self.clock()))
