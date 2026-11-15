import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tools.cleanup_duplicate_players import plan, apply


class DuplicateCleanupTest(unittest.TestCase):
    def test_keep_created_then_latest_and_ignore_empty_names(self):
        def row(pid, name, created, updated):
            return dict(player_id=pid, state_json=json.dumps({'entity': {'username': name, 'created': created}}), updated_at=updated)
        rows = [row('new-uncreated', '同名', False, 100), row('old-created', '同名', True, 1),
                row('keep', '同名', True, 2), row('empty1', '', False, 1), row('empty2', '', False, 2),
                row('different-case', 'A', True, 1), row('different-case2', 'a', True, 1)]
        result = plan(rows)
        self.assertEqual(len(result['groups']), 1)
        self.assertEqual(result['groups'][0]['keep'], 'keep')
        self.assertEqual({r['player_id'] for r in result['groups'][0]['delete']}, {'new-uncreated', 'old-created'})

    def test_changed_plan_refuses_deletion_and_backup_write(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with tempfile.TemporaryDirectory() as tmp, patch('tools.cleanup_duplicate_players.db.connection', return_value=connection):
            backup = Path(tmp) / 'backup.json'
            with self.assertRaisesRegex(ValueError, 'plan changed'):
                apply({'version': 1, 'groups': [{'name': 'stale'}]}, backup)
            self.assertFalse(backup.exists())
        self.assertEqual(cursor.execute.call_count, 1)
