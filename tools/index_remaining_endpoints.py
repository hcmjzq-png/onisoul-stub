#!/usr/bin/env python3
"""Index every endpoint in a fixed backlog against the verified client source.

Caller-file table references are leads, not endpoint dependencies. Existing
response fields are unreviewed candidates, not newly verified contracts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def index(source: Path, backlog: Path, out: Path) -> dict:
    baseline = rows(backlog)
    endpoints = {row["endpoint"] for row in baseline}
    calls = rows(ROOT / "docs/analysis/static-review-20261115/direct-callers.tsv")
    contract = {r["endpoint"]: r for r in rows(ROOT / "docs/analysis/api_contract.tsv")}
    il = {r["endpoint"]: r for r in rows(ROOT / "docs/analysis/static-review-20261115/endpoints.tsv")}
    web = (source / "WebApiClient.cs").read_text(encoding="utf-8-sig")
    expected = json.loads((ROOT / "docs/analysis/static-review-20261115/source-proof.json").read_text())["source_artifacts"]["WebApiClient.cs"]
    if hashlib.sha256((source / "WebApiClient.cs").read_bytes()).hexdigest() != expected:
        raise ValueError("WebApiClient source does not match the verified installer")
    wrappers: dict[str, list[str]] = {}
    for match in re.finditer(r'^\tpublic void (\w+)\([^\n]*\)\n\t\{(.*?)^\t\}', web, re.M | re.S):
        for api in re.findall(r'httpCall\("([^"]+)"', match.group(2)):
            wrappers.setdefault(api, []).append(f"WebApiClient.cs:{web.count(chr(10), 0, match.start()) + 1}:{match.group(1)}")
    files = {p.stem: p for p in source.rglob("*.cs")}
    hashes = {"WebApiClient.cs": expected}
    result = []
    for api in sorted(endpoints):
        callers = sorted({r["caller"] for r in calls if r["endpoint"] == api})
        caller_files = sorted({c.split("/")[0].split("::")[0] for c in callers})
        leads = set()
        for name in caller_files:
            path = files.get(name)
            if path is None:
                continue
            text = path.read_text(encoding="utf-8-sig")
            hashes[str(path.relative_to(source)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
            leads.update(re.findall(r'\b([A-Za-z_]\w*TableAccessor)\b', text))
        typed = int(il[api]["prior_typed_response_keys"])
        untyped = int(il[api]["prior_untyped_response_keys"])
        result.append({
            "endpoint": api, "wrapper_source": ";".join(wrappers.get(api, [])),
            "wrapper_signatures": il[api]["wrapper_signatures"],
            "direct_il_refs": il[api]["direct_il_refs"], "direct_callers": ";".join(callers),
            "request_key_candidates": il[api]["wrapper_literal_key_candidates"],
            "branched_request_wrapper": il[api]["branched_wrapper"],
            "computed_request_key": il[api]["has_computed_key_candidate"],
            "unreviewed_response_candidates": contract[api]["response_keys"],
            "typed_response_candidates": typed, "untyped_response_candidates": untyped,
            "caller_file_table_leads": ";".join(sorted(leads)),
            "review_status": "indexed_only; semantic review in reviewed-endpoints.tsv if present",
        })
    out.mkdir(parents=True, exist_ok=True)
    with (out / "all-357-evidence.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(result)
    summary = {
        "baseline_count": len(endpoints), "wrapper_source_found": sum(bool(r["wrapper_source"]) for r in result),
        "no_direct_il_refs": sum(int(r["direct_il_refs"]) == 0 for r in result),
        "no_typed_response_candidates": sum(not r["typed_response_candidates"] for r in result),
        "branched_wrappers": sum(r["branched_request_wrapper"] == "1" for r in result),
        "by_module": dict(sorted(Counter(api.split("/")[0] for api in endpoints).items())),
        "source_hashes": hashes,
        "scope": "All baseline endpoints indexed, not all business semantics verified. Zero direct refs do not prove unused; table mentions apply to whole caller files, not necessarily this endpoint.",
    }
    (out / "index-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in summary.items() if k != "source_hashes"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--backlog", type=Path, default=ROOT / "docs/analysis/quest-contract-20261115/remaining-endpoints.tsv")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/analysis/remaining-services-20261115")
    args = parser.parse_args()
    print(json.dumps(index(args.source, args.backlog, args.out), ensure_ascii=False))
