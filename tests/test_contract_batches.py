"""契约层与批次回归：保证 Stub 对 402 个已知端点「不撞 404、形状合法、图闭合」。

这些用例只校验**契约一致性**，不校验业务语义：
    - docs/analysis 的 tsv 与 app/business/contract_data.json 不漂移
    - 402 个端点全部可派发且返回 200
    - 响应里已声明类型的键，Python 类型与契约一致
    - 416 条端点→端点边的两端都可派发（按调用图批量发请求时不会 404）
    - 115 个批次（5 场景 + 110 扇出）成员全部已知
"""
from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path

from app.business import contract
from app.main import build_registry

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "analysis"

REQUIRED_KEYS = {"succeeded"}


def _tsv(name: str) -> list[dict[str, str]]:
    with io.open(DOCS / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _py_type_ok(value: object, typ: str) -> bool:
    if typ in ("int", "long"):
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "double":
        return isinstance(value, float)
    if typ == "bool":
        return isinstance(value, bool)
    if typ == "string":
        return isinstance(value, str)
    if typ == "Hashtable":
        return isinstance(value, dict)
    return True


class ContractDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = build_registry()

    def test_reads_tsv_directly(self):
        """契约层直接读 docs/analysis 的 tsv，端点集合必须与文档逐行一致。"""
        rows = _tsv("api_contract.tsv")
        endpoints = {(r["endpoint"] or "").strip() for r in rows if (r["endpoint"] or "").strip()}
        self.assertEqual(endpoints, set(contract.endpoints()))

        graph = _tsv("api_call_graph.tsv")
        self.assertEqual(len(graph), len(contract.edges()))

    def test_all_endpoints_dispatch_200(self):
        missing = []
        for api in contract.endpoints():
            status, body = self.reg.dispatch(api, {"token": "t"}, None)
            if status != 200:
                missing.append((api, status))
        self.assertEqual(missing, [], f"未登记或派发失败: {missing[:5]}")

    def test_unknown_endpoint_is_404(self):
        status, body = self.reg.dispatch("no/such/endpoint", {}, None)
        self.assertEqual(status, 404)
        self.assertFalse(body["succeeded"])

    def test_typed_response_keys_present_and_typed(self):
        bad = []
        for api in contract.endpoints():
            status, body = self.reg.dispatch(api, {}, None)
            for field in contract.response(api):
                key, typ = field["key"], field["type"]
                if not typ or "<" in key or ">" in key or key in {"succeeded", "now"}:
                    continue
                if key not in body:
                    bad.append((api, key, "缺失"))
                elif not _py_type_ok(body[key], typ):
                    bad.append((api, key, f"类型错: {type(body[key]).__name__} != {typ}"))
        self.assertEqual(bad, [], f"契约字段不达标: {bad[:5]}")

    def test_untyped_keys_not_fabricated(self):
        """源码里没取到类型的键不猜，避免给错类型让客户端强转崩。"""
        bad = []
        for api in contract.endpoints():
            status, body = self.reg.dispatch(api, {}, None)
            for field in contract.response(api):
                if field["type"]:
                    continue
                key = field["key"]
                if "<" in key or ">" in key or key in {"succeeded", "now"}:
                    continue
                if key in body:
                    bad.append((api, key))
        self.assertEqual(bad, [], f"多余键: {bad[:5]}")

    def test_edges_closed(self):
        known = set(contract.endpoints())
        unknown = [tuple(e) for e in contract.edges() if e[0] not in known or e[1] not in known]
        self.assertEqual(unknown, [], f"边指向未登记端点: {unknown[:5]}")
        self.assertGreater(len(contract.edges()), 400)

    def test_batches_known(self):
        batches = contract.batches()
        self.assertEqual(len(batches), 115)
        known = set(contract.endpoints())
        for batch in batches:
            self.assertTrue(batch["endpoints"], f"空批次: {batch['name']}")
            for api in batch["endpoints"]:
                self.assertIn(api, known, f"{batch['name']} 含未登记端点 {api}")

    def test_scene_batches_map(self):
        scenes = contract.scenes()
        self.assertEqual(
            sorted(scenes), ["deck", "migrationLogin", "politic", "strategy", "vsBattle"]
        )
        for scene, triggers in scenes.items():
            for api in triggers:
                self.assertIn(scene, contract.endpoints()[api]["triggers_scene"])


if __name__ == "__main__":
    unittest.main()
