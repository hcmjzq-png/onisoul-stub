"""Main-city base kokudaka; original interpolation, explicit aggregation policy.

Installed completed buildings count during production too. Storage and active
construction do not count. Officer/skill modifiers and subcities are separate,
unimplemented components; this projection never imports an old cached score.
"""
from __future__ import annotations

from app.business.city_production_rules import preview_amount
from app.business.player_services import integer


class KokudakaError(ValueError):
    """Missing source/state must not be presented as a zero score."""


def main_city_kokudaka(player: dict, buildings: dict) -> int:
    total = 0
    for record in player.get("buildings", {}).values():
        if record.get("deployedMapKey") != "map001" or record.get("status") == "building":
            continue
        if record.get("status") not in ("none", "waiting", "producing", "dead"):
            raise KokudakaError("no stub response: unsupported building state for base kokudaka")
        row = buildings.get(record.get("buildingTypeId"))
        if row is None:
            raise KokudakaError("no stub response: unknown building base kokudaka reference")
        if not isinstance(row, dict) or any(key not in row for key in ("grade", "kokudakaMin", "kokudakaMax")):
            raise KokudakaError("stub has no assets: building base kokudaka definition missing")
        try:
            total = integer(total + preview_amount(row["grade"], record.get("level"),
                                                   row["kokudakaMin"], row["kokudakaMax"]))
        except ValueError as exc:
            raise KokudakaError("no stub response: invalid building base kokudaka inputs") from exc
    return total
