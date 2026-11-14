"""Database bootstrap and transaction boundaries without a running MySQL."""
from __future__ import annotations

import unittest
import types
from unittest.mock import MagicMock, patch

from app import config, db


class SchemaBootstrapTest(unittest.TestCase):
    def test_bootstrap_connection_does_not_select_a_missing_database(self):
        driver = types.ModuleType("pymysql")
        driver.connect = MagicMock()
        cursors = types.ModuleType("pymysql.cursors")
        cursors.DictCursor = object()
        with patch.dict("sys.modules", {"pymysql": driver, "pymysql.cursors": cursors}):
            db._connect(select_database=False)
            self.assertIsNone(driver.connect.call_args.kwargs["database"])
            db._connect()
            self.assertEqual(
                driver.connect.call_args.kwargs["database"], config.load_config().db.name
            )

    def test_default_schema_creates_configured_database_before_tables(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cfg = config.load_config()
        configured = config.Config(
            cfg.host, cfg.port,
            config.DBConfig("127.0.0.1", 3306, "oni_test`local", "test", ""),
        )
        with patch.object(db, "_connect", return_value=connection) as connect:
            with patch.object(config, "load_config", return_value=configured):
                db.init_schema()

        connect.assert_called_once_with(select_database=False)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(statements[0].startswith(
            "CREATE DATABASE IF NOT EXISTS `oni_test``local`"
        ))
        self.assertEqual(statements[1], "USE `oni_test``local`")
        self.assertEqual(sum("CREATE TABLE IF NOT EXISTS" in s for s in statements), 3)
        self.assertFalse(any("USE game_db" in s for s in statements))
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_schema_error_is_propagated_and_connection_closed(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = RuntimeError("DDL failed")
        with patch.object(db, "_connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "DDL failed"):
                db.init_schema()
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


class TransactionTest(unittest.TestCase):
    def test_commit_failure_rolls_back_and_closes_connection(self):
        connection = MagicMock()
        connection.commit.side_effect = RuntimeError("commit failed")
        with patch.object(db, "_connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                with db.connection():
                    pass
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
