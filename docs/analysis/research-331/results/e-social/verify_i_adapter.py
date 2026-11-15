"""Load I's unmerged state/db read-only, and test E without copying shared files.

python .../verify_i_adapter.py --infrastructure-root D:/onisoul-worktrees/research-331-i-infrastructure
Default uses a disposable SQLite DB-API bridge. --mysql-port opts into a new
UUID-named database on a disposable loopback MySQL. Neither uses production.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--infrastructure-root", required=True, type=Path)
    parser.add_argument("--mysql-port", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mysql_port:
        os.environ["ONI_E_MYSQL_TEST"] = "1"
        os.environ["ONI_E_TEST_PORT"] = str(args.mysql_port)
    root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(root))
    import app
    import app.business  # pin E's business package before adding I's state path
    app.__path__.insert(0, str(args.infrastructure_root.resolve() / "app"))
    from app import state, db
    assert callable(state.atomic_players)
    print(json.dumps({"state_source": state.__file__, "db_source": db.__file__,
        "adapter_sha256": hashlib.sha256((args.infrastructure_root / "app/state/transactions.py").read_bytes()).hexdigest(),
        "backend": "isolated MySQL" if args.mysql_port else "disposable SQLite DB-API bridge; NOT InnoDB validation"}))
    name = "Research331EMySQLTest" if args.mysql_port else "Research331EIAdapterTest"
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_research331_e_i_adapter." + name)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.output:
        from tests.test_research331_e_i_adapter import Research331EMySQLTest
        args.output.write_text(json.dumps({"tests": result.testsRun, "failures": len(result.failures),
            "errors": len(result.errors), "skipped": len(result.skipped),
            "backend": getattr(Research331EMySQLTest, "version", "SQLite dialect bridge"),
            "adapter_sha256": hashlib.sha256((args.infrastructure_root / "app/state/transactions.py").read_bytes()).hexdigest(),
            "database": "fresh oni_e_test_<uuid>, dropped after run" if args.mysql_port else "disposable SQLite",
            "production_data_accessed": False}, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
