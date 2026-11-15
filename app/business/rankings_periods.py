"""Explicit simulator periods. No inferred Japanese/Taiwan maintenance clock."""
from __future__ import annotations

from dataclasses import dataclass

from app.business.player_services import integer


METRICS = ("kokudaka", "dedication", "dedication_monthly", "national_power")


@dataclass(frozen=True)
class Period:
    key: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("period identity required")
        integer(self.start, 0, 2**53 - 1)
        integer(self.end, self.start + 1, 2**53 - 1)


def validate_periods(plans: dict) -> None:
    if not isinstance(plans, dict) or set(plans) != set(METRICS):
        raise ValueError("no stub response: explicit plans for all ranking metrics required")
    for rows in plans.values():
        if not isinstance(rows, list) or not rows:
            raise ValueError("no stub response: empty period plan")
        if any(not isinstance(row, dict) or set(row) != {"key", "start", "end"} for row in rows):
            raise ValueError("invalid explicit period record")
        periods = [Period(**row) for row in rows]
        if len({p.key for p in periods}) != len(periods):
            raise ValueError("duplicate period identity")
        if any(a.end != b.start for a, b in zip(periods, periods[1:])):
            raise ValueError("periods must be ordered and contiguous")


def period_pair(plans: dict, metric: str, now: int) -> tuple[Period, Period | None]:
    integer(now, 0, 2**53 - 1)
    if metric not in METRICS:
        raise ValueError("no stub response: unsupported ranking metric")
    periods = [Period(**row) for row in plans[metric]]
    for index, period in enumerate(periods):
        if period.start <= now < period.end:
            return period, periods[index - 1] if index else None
    raise ValueError("no stub response: no configured ranking period at server time")
