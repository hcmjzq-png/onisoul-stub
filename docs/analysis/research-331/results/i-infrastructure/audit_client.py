"""Reproduce the I inventory from the read-only original ILSpy tree, not old AI code."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    out = Path(__file__).resolve().parent
    root = out.parents[4]
    sys.path.insert(0, str(root))
    from app.business.admin_debug_services import CONTROLLED_ADMIN, DISABLED_ENDPOINTS, TEST_HELPERS
    proof = json.loads((root / "docs/analysis/static-review-20261115/source-proof.json").read_text("utf-8"))
    web = args.source_root / "WebApiClient.cs"
    digest = hashlib.sha256(web.read_bytes()).hexdigest()
    assert digest == proof["source_artifacts"]["WebApiClient.cs"], "original source hash mismatch"
    sources = {p.name: p.read_text("utf-8").splitlines() for p in args.source_root.rglob("*.cs")}
    lines = sources["WebApiClient.cs"]
    records = []
    wrappers = {}
    for index, line in enumerate(lines):
        match = re.search(r'httpCall\("([^"]+)"', line)
        if not match or match[1] not in DISABLED_ENDPOINTS:
            continue
        method_line = next(i for i in range(index, -1, -1)
                           if re.search(r'^\s*public void \w+\(', lines[i]))
        method = re.search(r'public void (\w+)\(', lines[method_line])[1]
        parameters = re.findall(r'\.Add\("([^"]+)"', "\n".join(lines[method_line:index]))
        callers = [f"{file}:{i+1}" for file, content in sources.items() if file != "WebApiClient.cs"
                   for i, text in enumerate(content) if re.search(r'\.' + re.escape(method) + r'\s*\(', text)]
        category = ("受控管理" if match[1] in CONTROLLED_ADMIN else
                    "测试辅助" if match[1] in TEST_HELPERS else "保留关闭")
        wrappers[match[1]] = {"method": method, "declaration_line": method_line + 1,
                              "http_call_line": index + 1, "request_keys": parameters,
                              "lexical_callers": callers,
                              "caller_limit": "lexical references only; not proof of UI reachability/authorization"}
        records.append({"endpoint": match[1], "category": category, "status": "保留关闭",
                        "protocol_evidence": f"WebApiClient.cs:{method_line+1}-{index+1}",
                        "request_keys": ",".join(parameters),
                        "caller_evidence": ";".join(callers[:5]) or "未找到点调用；不代表不存在动态调用",
                        "verdict": "compatibility-policy",
                        "rules_gap": "原包装不能证明服务端授权/业务规则；不恢复调试数值或奖励",
                        "tables_assets": "不新增表行规则/客户端资源；不是 stub has no assets",
                        "state_producer": "无管理员身份/发行账本" if category == "受控管理" else "调试状态生产保持关闭",
                        "runtime": "真实 HTTP GET/POST 权限回归；Unity 未验收",
                        "implementation": "app/auth.py + app/business/admin_debug_services.py",
                        "pending": "direct Registry guard 见 integration.patch；不新增玩法 handler"})
    assert set(wrappers) == DISABLED_ENDPOINTS and len(records) == 32
    with (out / "endpoints.tsv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda r: r["endpoint"]))
    files = {"WebApiClient.cs", "GameRestarter.cs", "BootUp.cs", "SessionKeeper.cs"}
    files.update(ref.split(":")[0] for record in wrappers.values() for ref in record["lexical_callers"])
    evidence = {"access_date": "2026-11-15", "target": "2014-07-12 国际中文版 PC 原安装包",
                "assembly_sha256": proof["assembly_sha256"], "source_root": str(args.source_root),
                "source_proof": "docs/analysis/static-review-20261115/source-proof.json",
                "files": {name: hashlib.sha256((args.source_root / name).read_bytes()).hexdigest()
                          for name in sorted(files)}, "endpoints": wrappers,
                "new_findings": [
                    "forcePresents sends playerIds/text/rewards without token; this is not administrator authorization",
                    "debugLoginCog precedes token issue; it is not a safe pre-auth allowlist justification",
                    "GameRestarter.cs:79-99 requires errorReason to suppress a success callback",
                    "32 entries remain closed under authenticated, unauthenticated and observe modes"],
                "old_report": "No earlier I report: parallel-342/review explicitly reserved these 32 entries",
                "no_rule_claim": "No debug reward/level/period/gift values adopted from wrappers or tests"}
    (out / "client-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
