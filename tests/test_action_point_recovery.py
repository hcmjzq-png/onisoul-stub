"""Trusted-time recovery, old save initialization, cap and debit cadence."""
from __future__ import annotations

import copy
import unittest

from app.business.action_points import mark_politic_point_spend, recover_politic_points


class ActionPointRecoveryTest(unittest.TestCase):
    def player(self, point: int, stamp: float = 1000.0) -> dict:
        return {"actionPoints": {"politicPoint": {"point": point, "maxPoint": 25, "confirmTime": stamp}}}

    def test_elapsed_intervals_keep_remainder_and_reloads_do_not_replay(self) -> None:
        player = self.player(5)
        recover_politic_points(player, 1359)
        self.assertEqual(player["actionPoints"]["politicPoint"], {"point": 7, "maxPoint": 25, "confirmTime": 1240.0})
        before = copy.deepcopy(player)
        recover_politic_points(player, 1359)
        self.assertEqual(player, before)
        recover_politic_points(player, 1360)
        self.assertEqual(player["actionPoints"]["politicPoint"]["point"], 8)

    def test_legacy_zero_starts_now_and_rollback_never_grants(self) -> None:
        player = self.player(20, 0)
        recover_politic_points(player, 2000000000)
        self.assertEqual(player["actionPoints"]["politicPoint"]["point"], 20)
        before = copy.deepcopy(player)
        recover_politic_points(player, 1999999999)
        self.assertEqual(player, before)

    def test_full_or_excess_never_accumulates_free_recovery(self) -> None:
        for amount in (25, 40):
            player = self.player(amount)
            recover_politic_points(player, 10000)
            self.assertEqual(player["actionPoints"]["politicPoint"]["point"], amount)
            self.assertEqual(player["actionPoints"]["politicPoint"]["confirmTime"], 0)
        player = self.player(24)
        recover_politic_points(player, 10000)
        self.assertEqual(player["actionPoints"]["politicPoint"]["point"], 25)

    def test_spending_from_full_starts_timer_and_further_spend_keeps_it(self) -> None:
        player = self.player(24, 0)
        mark_politic_point_spend(player, 1000)
        player["actionPoints"]["politicPoint"]["point"] -= 1
        mark_politic_point_spend(player, 1050)
        self.assertEqual(player["actionPoints"]["politicPoint"]["confirmTime"], 1000)
        recover_politic_points(player, 1120)
        self.assertEqual(player["actionPoints"]["politicPoint"]["point"], 24)
