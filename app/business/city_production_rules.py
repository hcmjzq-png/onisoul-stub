"""Original-client production calculations, NOT a harvest settlement engine.

All helpers are pure. Reward slots are catalogue data, never granted rewards.
No probability, road multiplier, finite-durability decrement or experience gain
is inferred. Mounted production subsets define their own settlement policies.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any

from app.business.player_services import integer


def _float32(value: int | float) -> float:
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("float32 calculation out of range") from exc
    if not math.isfinite(result):
        raise ValueError("finite float32 required")
    return result


def production_costs(product: dict, building_level: dict) -> dict[str, int]:
    """PoliticBuilding.getProductCosts: float32 multiply then truncate.

    This differs from getLevelUpCosts' thousandths rounding. These are client
    costs before any unverified server-side skill/modifier policy.
    """
    ratio = building_level.get("costRatio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio < 0:
        raise ValueError("no stub response: invalid production costRatio")
    ratio = _float32(ratio)
    kinds, amounts = product.get("costTypes"), product.get("costAmounts")
    if not isinstance(kinds, list) or not isinstance(amounts, list) or len(kinds) != len(amounts):
        raise ValueError("no stub response: inconsistent production cost arrays")
    if any(not isinstance(kind, str) or not kind for kind in kinds) or len(set(kinds)) != len(kinds):
        raise ValueError("no stub response: invalid or duplicate production resource")
    result = {}
    for kind, amount in zip(kinds, amounts):
        scaled = _float32(_float32(integer(amount)) * ratio)
        result[kind] = integer(math.trunc(scaled))
    return result


def preview_amount(grade: int, level: int, minimum: int, maximum: int) -> int:
    """UserStatus.calcAmount; UI preview ONLY, excludes item15 damage items."""
    grade = integer(grade, 1, 214748364)
    level = integer(level, 1, grade * 10)
    minimum, maximum = integer(minimum), integer(maximum)
    if maximum < minimum:
        raise ValueError("no stub response: reversed preview quantity bounds")
    step = _float32(_float32(maximum - minimum) / _float32(grade * 10 - 1))
    result = _float32(_float32(minimum) + _float32(_float32(level - 1) * step))
    return integer(math.floor(result))


@dataclass(frozen=True)
class RewardSlot:
    """Read-only table metadata; ratio values are not probabilities."""
    index: int
    group: str
    ratio_min: int
    ratio_max: int
    item_id: str
    count_min: int
    count_max: int


def reward_slot(row: dict, index: int) -> RewardSlot | None:
    """RewardTableAccessor.getReward's numeric-ratio gate, strict on bad rows.

    Unity MiniJSON decodes numbers as double. Nonnumeric ratios become zero;
    when both are zero the client ignores even nonzero counts/item IDs.
    None means inactive, not a missing row/file (caller must resolve those).
    """
    index = integer(index, 1, 10)  # this original reward01 catalogue has 10 slots
    ratios = []
    for suffix in ("min", "max"):
        key = f"ratio{index}{suffix}"
        if key not in row:
            raise ValueError("no stub response: reward ratio field missing")
        value: Any = row[key]
        if type(value) in (int, float):
            if not math.isfinite(value):
                raise ValueError("no stub response: nonfinite reward ratio")
            ratios.append(integer(math.trunc(value)))
        else:
            ratios.append(0)
    if ratios == [0, 0]:
        return None
    group, item = row.get(f"group{index}"), row.get(f"itemId{index}")
    if not isinstance(group, str) or not isinstance(item, str):
        raise ValueError("no stub response: reward slot identifiers missing")
    return RewardSlot(index, group, *ratios, item,
                      integer(row.get(f"count{index}min")), integer(row.get(f"count{index}max")))


def durability_kind(value: int, defines: dict) -> str:
    """PoliticBuildingParameter.IsInfiniteDurability/IsDead; no mutation.

    Do not use a >= comparison for the infinite sentinel or fill in missing
    persisted durability from the client's default 10001.
    """
    row = defines.get("infinite_building_durability")
    if not isinstance(row, dict):
        raise ValueError("no stub response: infinite durability definition missing")
    sentinel = integer(row.get("value"), 1)
    value = integer(value, -2147483648)
    return "infinite" if value == sentinel else "dead" if value <= 0 else "finite"


def harvest_display_point_cost(count: int, defines: dict) -> int:
    """PoliticFSMAutoHarvest.noticeResult / PluginRunner_DoHarvest.

    Used by the mounted batch settlement. Count production tasks only; the
    original auto-harvest list excludes construction. Single harvests cost one.
    """
    count = integer(count, 1)
    if count == 1:
        return 1
    row = defines.get("politic_auto_harvest_point")
    if not isinstance(row, dict):
        raise ValueError("no stub response: auto harvest point definition missing")
    return integer(row.get("value"), 1)
