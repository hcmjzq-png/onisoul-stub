"""Server-side action-point recovery matching the original PC's 120s interval.

Integer points, retained partial interval and offline catch-up are persistence
policy. Legacy zero timestamps start a fresh interval without retroactive gifts.
"""
from __future__ import annotations

from app.business.player_services import integer

RECOVER_INTERVAL = 120  # Original PC Configs.get_RecoverIntervalTime @ 0x4378c.
ACTION_POINT_KEYS = ("politicPoint", "missionPoint", "battlePoint")
MAX_TIMESTAMP = 9007199254740991


def recover_action_points(player: dict, now: int) -> None:
    now = integer(now, 1, MAX_TIMESTAMP)
    for key in ACTION_POINT_KEYS:
        _recover(player["actionPoints"][key], now)


def _recover(box: dict, now: int) -> None:
    point, maximum = integer(box["point"]), integer(box["maxPoint"])
    if point >= maximum:
        # Do not accumulate recovery while full, or destroy excess owned points.
        box["confirmTime"] = 0.0
        return
    stamp = integer(box.get("confirmTime", 0), 0, MAX_TIMESTAMP)
    if stamp == 0:
        box["confirmTime"] = float(now)
        return
    if now < stamp:
        return  # Clock rollback cannot create points or reset an active interval.
    recovered = (now - stamp) // RECOVER_INTERVAL
    if recovered:
        box["point"] = min(maximum, point + recovered)
        box["confirmTime"] = (0.0 if box["point"] == maximum
                              else float(stamp + recovered * RECOVER_INTERVAL))


def sync_action_point_timers(player: dict, now: int) -> None:
    """Start a timer after spending from full and stop it at the cap."""
    now = integer(now, 1, MAX_TIMESTAMP)
    for key in ACTION_POINT_KEYS:
        box = player["actionPoints"][key]
        if box["point"] >= box["maxPoint"]:
            box["confirmTime"] = 0.0
        elif not box.get("confirmTime"):
            box["confirmTime"] = float(now)
