"""零字段端点处置清单与契约表的口径必须一致。

`docs/analysis/verify/no_key_final.txt` 原先按 `.<方法名>(` 字面点判定 `usage`，
与契约 `call_sites` 列对不上（27 条）。本测试把那批口径差钉死：

- 清单行数 == 契约里 `key_count == 0` 的端点数（有键的端点不得留在清单里）；
- `usage == "called"` 当且仅当契约 `call_sites` 非空；
- 有调用点的行必须给出形态（`shape` 不能是 `-`）。
"""
from __future__ import annotations

import io
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTORY = os.path.join(ROOT, "docs", "analysis", "verify", "no_key_final.txt")
CONTRACT = os.path.join(ROOT, "docs", "analysis", "api_contract.tsv")


def _tsv(path: str) -> list[dict[str, str]]:
    lines = io.open(path, encoding="utf-8").read().split("\n")
    head = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        if line.strip():
            out.append(dict(zip(head, line.split("\t"))))
    return out


class NoKeyInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inv = _tsv(INVENTORY)
        cls.contract = {row["endpoint"]: row for row in _tsv(CONTRACT)}

    def test_inventory_matches_zero_key_endpoints(self) -> None:
        zero = {ep for ep, row in self.contract.items() if row["key_count"] == "0"}
        listed = {row["endpoint"] for row in self.inv}
        self.assertEqual(listed - zero, set(), "清单里混进了已有响应键的端点")
        self.assertEqual(zero - listed, set(), "契约零字段端点没进清单")

    def test_usage_agrees_with_contract_call_sites(self) -> None:
        bad = []
        for row in self.inv:
            sites = self.contract[row["endpoint"]]["call_sites"].strip()
            expected = "called" if sites else "no_call_site"
            if row["usage"] != expected:
                bad.append((row["endpoint"], row["usage"], expected, sites))
        self.assertEqual(bad, [], f"usage 与 call_sites 不一致: {bad[:5]}")

    def test_called_rows_have_classified_shape(self) -> None:
        bad = [row["endpoint"] for row in self.inv
               if row["usage"] == "called" and row["shape"] in ("-", "")]
        self.assertEqual(bad, [], f"有调用点却没归形态: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
