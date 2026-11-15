"""Read-only reconciliation of nine handoffs, current registration and local proofs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from app.main import build_registry


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = ROOT / "docs/analysis/research-331"
    assigned = rows(plan / "assignments.tsv")
    registry = build_registry()
    errors, groups, proofs = [], {}, []
    mounted = sorted(row["endpoint"] for row in assigned
                     if registry._handlers[row["endpoint"]].__module__ != "app.business.placeholders")
    for folder in sorted((plan / "results").iterdir()):
        if not (folder / "endpoints.tsv").is_file():
            continue
        group = folder.name[0].upper()
        supplied = rows(folder / "endpoints.tsv")
        names = [row.get("endpoint", row.get("api")) for row in supplied]
        expected = {row["endpoint"] for row in assigned if row["group"] == group}
        if len(names) != len(set(names)) or set(names) != expected:
            errors.append(f"handoff inventory mismatch: {group}")
        groups[group] = {"assigned": len(expected), "mounted": len(expected & set(mounted)),
                         "remaining": len(expected - set(mounted))}
        proofs.extend(path for path in folder.glob("*.json")
                      if ("proof" in path.name or "evidence" in path.name)
                      and "external" not in path.name)

    cache, checked = {}, set()
    def inspect(value, origin):
        if isinstance(value, list):
            for child in value:
                inspect(child, origin)
        elif isinstance(value, dict):
            path = value.get("path", value.get("source"))
            digest = value.get("sha256")
            if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
                target = Path(path)
                relative = not target.is_absolute()
                if relative:
                    target = ROOT / target
                key = str(target.resolve())
                if key not in cache:
                    try:
                        raw = target.read_bytes()
                        cache[key] = (hashlib.sha256(raw).hexdigest(),
                                      hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest())
                    except OSError:
                        cache[key] = ()
                accepted = cache[key] if relative else cache[key][:1]
                if digest not in accepted:
                    errors.append(f"missing or changed proof file: {origin.name}: {path}")
                checked.add(key)
            for child in value.values():
                inspect(child, origin)
    for proof in proofs:
        inspect(json.loads(proof.read_text(encoding="utf-8-sig")), proof)
    placeholder_count = sum(h.__module__ == "app.business.placeholders"
                            for h in registry._handlers.values())
    if len(assigned) != 331 or len(set(row["endpoint"] for row in assigned)) != 331:
        errors.append("historical assignment inventory must contain 331 unique endpoints")
    if set(groups) != set("ABCDEFGHI"):
        errors.append("missing group handoff")
    if placeholder_count + len(mounted) != 331:
        errors.append("current placeholders and newly mounted entries do not reconcile")
    result = {"registered": len(registry.known()), "dedicated": len(registry.known()) - placeholder_count,
              "placeholders": placeholder_count, "newly_mounted": mounted, "groups": groups,
              "proof_files": len(proofs), "unique_local_paths_checked": len(checked),
              "proof_scope": "explicit path/source + sha256 pairs; relative text may use LF; not a web-source or full semantic audit",
              "errors": errors}
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
