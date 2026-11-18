"""Ordinary shop eligibility and persistent building milestones."""
from __future__ import annotations

from collections.abc import Iterable

from app.business.mission_chain import UNLOCK_BITS

SHOP_UNLOCKS = "shopUnlockedItems"


def shop_item_is_open(player: dict, code: str, row: dict) -> bool:
    return bool(player["unlockBits"] & UNLOCK_BITS["unlockShop"]) and (
        row.get("isInitialSale") is True or code in player.get(SHOP_UNLOCKS, ())
    )


def remember_shop_unlocks(player: dict, definitions: dict, buildings: Iterable[dict]) -> None:
    saved = player.get(SHOP_UNLOCKS)
    unlocked = {item for item in saved if isinstance(item, str)} if isinstance(saved, list) else set()
    for record in buildings:
        if not isinstance(record, dict) or record.get("status") not in ("none", "waiting", "producing"):
            continue
        level = record.get("level")
        if type(level) not in (int, float):
            continue
        row = definitions.get(record.get("buildingTypeId"), {})
        for number in range(1, 4):
            target_level = row.get(f"openLevel{number}")
            targets = row.get(f"openShopItemId{number}")
            if isinstance(targets, list) and type(target_level) is int and 1 <= target_level <= level:
                unlocked.update(item for item in targets if isinstance(item, str) and item)
    player[SHOP_UNLOCKS] = sorted(unlocked)
