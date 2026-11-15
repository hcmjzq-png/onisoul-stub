"""Validate the submitted patch without modifying a shared public file."""
import csv
from pathlib import Path
import unittest

from app.business.rankings_services import LedgerRankingsServices
from app.business.registry import Registry
from app.tables import TableCatalog
from tools.gameplay_smoke import MemorySessions, MemoryState
from tests.patch_context import apply_context


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/analysis/research-331/results/g-rankings"


class GIntegrationTest(unittest.TestCase):
    def test_patch_registers_exactly_eight_only_with_explicit_provider(self):
        relative = "app/business/gameplay.py"
        source = (ROOT / relative).read_text(encoding="utf-8")
        patch = (RESULTS / "integration.patch").read_text(encoding="utf-8")
        section = patch.split("--- a/" + relative + "\n", 1)[1].split("--- a/docs/", 1)[0]
        out = apply_context(source, section)
        namespace = {"__name__": "app.business.gameplay"}
        exec(compile(out, relative, "exec"), namespace)
        catalog = TableCatalog(ROOT / "tests/fixtures/gameplay/tables",
                               ROOT / "tests/fixtures/gameplay/tables/table_list.tsv")
        def registry(provider=None):
            state = MemoryState()
            service = namespace["GameplayService"](catalog=catalog, load_state=state.load,
                save_state=state.save, session_store=MemorySessions(), rankings_read_view=provider)
            return service.register(Registry()).register_contract_defaults()
        base = registry()
        injected = registry(lambda: self.fail("registration must not query or invent ranking state"))
        changed = {api for api in base.known()
                   if base._handlers[api].__module__ != injected._handlers[api].__module__}
        self.assertEqual(changed, set(LedgerRankingsServices.APIS))
        self.assertEqual(len(base.known()), 402)
        # GameplayService alone omits two handlers mounted by app.main.
        baseline_placeholders = sum(h.__module__ == "app.business.placeholders" for h in base._handlers.values())
        self.assertEqual(sum(h.__module__ == "app.business.placeholders" for h in injected._handlers.values()), baseline_placeholders - 8)
        for api in ("common/dedicate", "common/getBriefOfNationalPower"):
            self.assertEqual(injected._handlers[api].__module__, "app.business.placeholders")

    def test_manifest_retains_all_51_and_distinguishes_components_from_integration(self):
        with (RESULTS / "endpoints.tsv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        prior = ROOT / "docs/analysis/parallel-342/g-rankings/reviewed-endpoints.tsv"
        with prior.open(encoding="utf-8", newline="") as handle:
            original = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 51)
        self.assertEqual({r["endpoint"] for r in rows}, {r["endpoint"] for r in original})
        self.assertEqual(sum(r["status"] == "component-complete; pending-integration" for r in rows), 8)
        self.assertTrue(all(r["runtime_acceptance"] == "not-run" for r in rows))


if __name__ == "__main__":
    unittest.main()
