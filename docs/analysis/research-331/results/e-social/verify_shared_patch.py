"""Execute the shared regression test changes without editing any shared path."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from build_integration_patch import build
import app
import app.main
from app import state


def forbidden_db(_):
    raise AssertionError("shared baseline tests must not access a social database")


def main():
    texts, _ = build()
    periodic = types.ModuleType("app.business.periodic")
    exec(compile(texts["app/business/periodic.py"], "<E-periodic-patch>", "exec"), periodic.__dict__)
    candidate = types.ModuleType("app.main")
    with patch.dict(sys.modules, {"app.business.periodic": periodic}):
        exec(compile(texts["app/main.py"], "<E-main-patch>", "exec"), candidate.__dict__)
    regression = types.ModuleType("tests.e_shared_regression")
    regression.__file__ = str(Path(__file__).resolve().parents[5] / "tests/test_parallel_342_integration.py")
    with patch.dict(sys.modules, {"app.main": candidate}), patch.object(app, "main", candidate), \
            patch.object(state, "atomic_players", forbidden_db, create=True):
        exec(compile(texts["tests/test_parallel_342_integration.py"], "<E-shared-regression-patch>", "exec"),
             regression.__dict__)
        suite = unittest.defaultTestLoader.loadTestsFromModule(regression)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
