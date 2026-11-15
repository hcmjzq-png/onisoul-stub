"""Repeatable opt-in integration test runner; credentials only from test env vars."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import unittest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int, help="disposable loopback MySQL, not 3306")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    sys.path[:0] = [str(root), str(root / "tests")]
    os.environ["ONI_I_MYSQL_TEST"] = "1"
    os.environ["ONI_I_TEST_PORT"] = str(args.port)
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_research331_i_mysql.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    from test_research331_i_mysql import MySQLTransactionsTest
    summary = {"tests": result.testsRun, "failures": len(result.failures),
               "errors": len(result.errors), "skipped": len(result.skipped),
               "mysql_version": getattr(MySQLTransactionsTest, "version", "unavailable"),
               "database": "new oni_i_test_<uuid>; dropped after run",
               "workers": "4 independent spawn processes; 48 transfers / 48 repeated receipt attempts",
               "production_data_accessed": False}
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
