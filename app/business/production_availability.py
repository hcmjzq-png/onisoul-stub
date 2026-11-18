"""Local recipe policy for a one-time production lesson and ordinary play."""
from __future__ import annotations

from app.business.mission_validation import state_of
from app.business.player_services import integer


FIELD_LESSON_RECIPE = "product060_023_01_01_1_1"
FIELD_LESSON_HARVESTED = "fieldLessonHarvested"
STARTER_INDUSTRIES = frozenset(("item05_0200039", "item05_0200040", "item05_0200041"))


def field_lesson_available(player: dict, missions: dict) -> bool:
    return (
        state_of(player, missions, "po_mission_00004") == "closed"
        and state_of(player, missions, "po_mission_00005") == "accepted"
        and player.get(FIELD_LESSON_HARVESTED) is not True
        and not any(task.get("productId") == FIELD_LESSON_RECIPE for task in player["produce"].values())
    )


def recipe_available(player: dict, building: dict, code: str, product: dict, missions: dict) -> bool:
    if product.get("openMission") != "null":
        raise ValueError("product mission unlock rules are not implemented")
    if code == FIELD_LESSON_RECIPE:
        return field_lesson_available(player, missions)
    if building.get("itemId") in STARTER_INDUSTRIES and building.get("produceType") == "manual":
        seconds = integer(product.get("dueInterval"), 1)
        if seconds < 60:
            return False
        if seconds == 900:
            return True
    return integer(product.get("openLevel")) <= integer(player["entity"].get("level"), 1)
