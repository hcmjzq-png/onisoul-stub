"""Verified nine-grid line geometry, not an event or random-reward producer.

NineGridDataManager.cs:200-258 defines these eight lines. Acquisition eligibility,
event identity, cost schedule and prize distribution remain unsupported; neither
inventory scans nor GenFake* client examples may produce collection rights.
"""
from __future__ import annotations

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6),
         (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def completed_lines(collected: tuple[bool, ...]) -> tuple[int, ...]:
    """Input is an already-authorized snapshot, never raw player inventory."""
    if (not isinstance(collected, tuple) or len(collected) != 9
            or any(type(value) is not bool for value in collected)):
        raise ValueError("nine authoritative boolean collection flags required")
    return tuple(index for index, line in enumerate(LINES)
                 if all(collected[cell] for cell in line))
