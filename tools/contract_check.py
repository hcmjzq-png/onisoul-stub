"""契约一致性检查（只读）：把 Stub 读到的契约跑一遍结构性校验并打印计数。

用法：
    python3 tools/contract_check.py

检查项：
    - 端点表可解析、非空
    - 调用图每条边的两端都在端点表里
    - 批次非空、成员都已登记
    - 响应键里能取到类型的比例（用于说明占位响应覆盖了多少字段）
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app.business import contract


def main() -> int:
    eps = contract.endpoints()
    edges = contract.edges()
    batches = contract.batches()
    scenes = contract.scenes()

    issues: list[str] = []
    if not eps:
        issues.append("端点表为空")
    for a, b, via in edges:
        if a not in eps or b not in eps:
            issues.append(f"边指向未登记端点: {a} -> {b}")
    for batch in batches:
        if not batch["endpoints"]:
            issues.append(f"空批次: {batch['name']}")
        for api in batch["endpoints"]:
            if api not in eps:
                issues.append(f"{batch['name']} 含未登记端点 {api}")

    keys = [f for info in eps.values() for f in info["response"]]
    typed = [f for f in keys if f["type"]]

    print(f"端点        {len(eps)}")
    print(f"调用边      {len(edges)}")
    print(f"场景        {len(scenes)}  {sorted(scenes)}")
    print(f"批次        {len(batches)}（scene {len(scenes)} + fanout {len(batches) - len(scenes)}）")
    print(f"响应键      {len(keys)}，其中有类型 {len(typed)}")
    print(f"问题        {len(issues)}")
    for item in issues[:10]:
        print(f"  - {item}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
