"""Original quantities plus explicitly authorized compatible reward selection.

Named groups select one entry by their interpolated weights. The original
literal 'none' group is treated as independent percentage rolls. A saved task
generation seeds automatic rewards so failed/retried harvests cannot reroll.
These selection semantics are a local compatibility rule, not recovered code.
"""
from __future__ import annotations

from collections import defaultdict
import random
import math

from app.business.city_production_rules import preview_amount, reward_slot, _float32
from app.business.player_services import integer
from app.business.production_inventory import ProductionInventory

# Missing original Nanban G3+ row: use its latest existing G2 reward row.
# This alias is internal policy; the original product/reward files are untouched.
REWARD_FALLBACKS = {"reward01_02_00027_01": "reward01_02_00026_01"}


def reward_weight(grade: int, level: int, minimum: int, maximum: int) -> int:
    grade, level = integer(grade, 1), integer(level, 1, grade * 10)
    minimum, maximum = integer(minimum), integer(maximum)
    step = _float32(_float32(maximum - minimum) / _float32(grade * 10 - 1))
    return integer(math.floor(_float32(_float32(minimum) + _float32(_float32(level - 1) * step))))


def resolve_rewards(service, record: dict, row: dict, product: dict, *, seed: str = "catalog") -> dict:
    inventory = ProductionInventory(service)
    catalogue = inventory.table("reward01_politic")
    requested = product.get("rewardId")
    reward_id = requested if requested in catalogue else REWARD_FALLBACKS.get(requested)
    reward = catalogue.get(reward_id)
    if not isinstance(reward, dict):
        raise ValueError("stub has no assets: production reward definition missing")
    grade, level = integer(row.get("grade"), 1), integer(record.get("level"), 1)
    rng, groups = random.Random(seed), defaultdict(list)
    for index in range(1, 11):
        slot = reward_slot(reward, index)
        if slot is None:
            continue
        inventory.route(slot.item_id)
        weight = reward_weight(grade, level, slot.ratio_min, slot.ratio_max)
        amount = preview_amount(grade, level, slot.count_min, slot.count_max)
        groups[slot.group].append((slot.item_id, weight, amount))
    if not groups:
        raise ValueError("no stub response: production reward has no active slots")
    amounts = {}

    def add(code, amount):
        if amount:
            amounts[code] = integer(amounts.get(code, 0) + amount)

    for group, entries in groups.items():
        if group in ("none", ""):
            for code, weight, amount in entries:
                if rng.random() * 100 < min(100, weight):
                    add(code, amount)
            continue
        total = sum(weight for _, weight, _ in entries)
        if total <= 0:
            continue
        roll = rng.random() * total
        for code, weight, amount in entries:
            roll -= weight
            if roll < 0:
                add(code, amount)
                break
    return {"reward": amounts, "buildingExp": integer(product.get("buildingExp")),
            "rewardPolicy": "group-weights-v1", "emptyAllowed": True,
            "rewardSourceId": reward_id}
