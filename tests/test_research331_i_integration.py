"""Verify the unapplied registry integration patch without editing shared files."""
from __future__ import annotations

from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import Mock

from app.business.admin_debug_services import DISABLED_ENDPOINTS


class IntegrationPatchTest(unittest.TestCase):
    def test_registry_patch_blocks_direct_dispatch_without_adding_handlers(self):
        root = Path(__file__).resolve().parents[1]
        patch_path = root / "docs/analysis/research-331/results/i-infrastructure/integration.patch"
        patch_text = patch_path.read_text("utf-8")
        base = subprocess.check_output([
            "git", "show", "8023c3fee8e525040d101fee8bf843b48b3256d3:app/business/registry.py"
        ], cwd=root).decode("utf-8")
        # Reconstruct this single hunk in memory; no shared working-tree mutation.
        hunk = patch_text.split("@@", 2)[2].splitlines(keepends=True)[1:]
        before = "".join(line[1:] for line in hunk if line.startswith((" ", "-")))
        after = "".join(line[1:] for line in hunk if line.startswith((" ", "+")))
        self.assertEqual(base.count(before), 1)
        module = types.ModuleType("research331_i_patched_registry")
        exec(compile(base.replace(before, after), "registry.integration.patch", "exec"), module.__dict__)
        registry = module.Registry().register_contract_defaults()
        self.assertEqual(len(registry.known()), 402)
        handler = Mock(side_effect=AssertionError("disabled handler invoked"))
        for api in DISABLED_ENDPOINTS:
            registry.register(api, handler)
            status, body = registry.dispatch(api, {"isAdmin": True}, {"role": "admin"})
            self.assertEqual(status, 200)
            self.assertFalse(body["succeeded"])
            self.assertIn("errorReason", body)
        handler.assert_not_called()
        self.assertEqual(registry.dispatch("missing/api", {}, None)[0], 404)


if __name__ == "__main__":
    unittest.main()
