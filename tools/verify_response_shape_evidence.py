#!/usr/bin/env python3
"""Verify response-shape evidence against a decompiled client source tree."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.business.response_shapes import (  # noqa: E402
    BARE_MAP_EVIDENCE,
    SCALAR_ROOT_EVIDENCE,
)

EVIDENCE_RE = re.compile(r"^(?P<file>[^\\/:]+\.cs):(?P<method>[A-Za-z_][A-Za-z0-9_]*)$")
MODIFIERS = (
    "public|private|protected|internal|static|virtual|override|sealed|abstract|"
    "async|extern|unsafe|new|partial"
)
RETURN_TYPE = r"[A-Za-z_][A-Za-z0-9_.]*(?:\s*<[^\n;{}()]+>)?(?:\[\])?\??"


@dataclass(frozen=True)
class EvidenceResult:
    api: str
    shape: str
    evidence: str
    ok: bool
    error: str = ""
    file: str = ""


def declaration_pattern(method: str) -> re.Pattern[str]:
    return re.compile(
        rf"^[ \t]*(?:(?:{MODIFIERS})\s+)*(?:{RETURN_TYPE}\s+)"
        rf"{re.escape(method)}\s*\(",
        re.MULTILINE,
    )


def source_index(source_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in sorted(source_root.rglob("*.cs")):
        if path.is_file():
            index.setdefault(path.name, []).append(path)
    return index


def validate_evidence(
    evidence: dict[str, str],
    shape: str,
    index: dict[str, list[Path]],
) -> list[EvidenceResult]:
    results: list[EvidenceResult] = []
    for api, value in sorted(evidence.items()):
        matched = EVIDENCE_RE.fullmatch(value)
        if matched is None:
            results.append(
                EvidenceResult(api, shape, value, False, "invalid file:method syntax")
            )
            continue
        filename = matched.group("file")
        method = matched.group("method")
        candidates = index.get(filename, [])
        if not candidates:
            results.append(
                EvidenceResult(api, shape, value, False, "source file not found", filename)
            )
            continue
        pattern = declaration_pattern(method)
        declared = next(
            (
                path
                for path in candidates
                if pattern.search(path.read_text(encoding="utf-8-sig", errors="replace"))
            ),
            None,
        )
        if declared is None:
            results.append(
                EvidenceResult(
                    api,
                    shape,
                    value,
                    False,
                    "method declaration not found",
                    filename,
                )
            )
            continue
        results.append(
            EvidenceResult(
                api,
                shape,
                value,
                True,
                file=filename,
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="decompiled client source root")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args(argv)

    source_root = Path(args.source).resolve()
    if not source_root.is_dir():
        parser.error(f"source directory not found: {source_root}")
    index = source_index(source_root)
    results = validate_evidence(BARE_MAP_EVIDENCE, "bare_map", index)
    results.extend(validate_evidence(SCALAR_ROOT_EVIDENCE, "scalar_root", index))
    failures = [result for result in results if not result.ok]

    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print(f"[shape-evidence] checked={len(results)} failed={len(failures)}")
        for result in failures:
            print(f"[shape-evidence] {result.api}: {result.evidence} ({result.error})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
