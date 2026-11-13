"""Optimistic player-state revision tests."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.state import player as player_state


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, row):
        self.cursor_obj = FakeCursor(row)

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StateRevisionTest(unittest.TestCase):
    def test_stale_snapshot_is_rejected(self):
        row = {"state_json": json.dumps({"entity": {}, "_revision": 3})}
        connection = FakeConnection(row)
        with patch.object(player_state.db, "connection", return_value=connection):
            with self.assertRaises(player_state.StateConflictError):
                player_state.save({"_revision": 2, "entity": {}}, "p")

    def test_save_increments_revision(self):
        row = {"state_json": json.dumps({"entity": {}, "_revision": 3})}
        connection = FakeConnection(row)
        state = {"_revision": 3, "entity": {"playerId": "p"}}
        with patch.object(player_state.db, "connection", return_value=connection):
            player_state.save(state, "p")
        self.assertEqual(state["_revision"], 4)
        self.assertTrue(
            any(query[0].startswith("UPDATE players") for query in connection.cursor_obj.queries)
        )

    def test_new_player_starts_at_revision_one(self):
        connection = FakeConnection(None)
        state = {"_revision": 0, "entity": {"playerId": "p"}}
        with patch.object(player_state.db, "connection", return_value=connection):
            player_state.save(state, "p")
        self.assertEqual(state["_revision"], 1)
        self.assertTrue(
            any(query[0].startswith("INSERT INTO players") for query in connection.cursor_obj.queries)
        )


if __name__ == "__main__":
    unittest.main()
