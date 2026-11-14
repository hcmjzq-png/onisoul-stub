#!/usr/bin/env python3
"""Verify response-shape evidence against a decompiled client source tree."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.business.response_shapes import (  # noqa: E402
    BARE_MAP_EVIDENCE,
    SCALAR_ROOT_EVIDENCE,
)

EVIDENCE_RE = re.compile(
    r"^(?P<file>[^\\/:]+\.cs):(?P<method>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:@0x(?P<offset>[0-9A-Fa-f]+))?$"
)
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
    method: str = ""
    offset: str = ""


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
        offset = matched.group("offset") or ""
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
                    method,
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
                method=method,
                offset=offset,
            )
        )
    return results


def parse_evidence(evidence: dict[str, str], shape: str) -> list[EvidenceResult]:
    """Parse evidence syntax without requiring a decompiled source tree."""
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
        offset = matched.group("offset") or ""
        if not offset:
            results.append(
                EvidenceResult(
                    api,
                    shape,
                    value,
                    False,
                    "missing IL method body offset",
                    filename,
                    method,
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
                method=method,
                offset=offset,
            )
        )
    return results


def validate_il_offsets(
    results: list[EvidenceResult], assembly_path: str, entry: str
) -> list[EvidenceResult]:
    try:
        from tools.oni_il import (
            AssemblyModel,
            extract_container_entry,
            is_unity_web_data,
        )
    except ModuleNotFoundError:
        from oni_il import (  # type: ignore
            AssemblyModel,
            extract_container_entry,
            is_unity_web_data,
        )

    source = Path(assembly_path).expanduser().resolve()
    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        if is_unity_web_data(source):
            temp = tempfile.TemporaryDirectory(prefix="onisoul-shape-evidence-")
            assembly = Path(temp.name) / entry
            extracted = extract_container_entry(source, entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        locations = {
            (body.name, model.image_offset(body.file_offset))
            for body in model.iter_bodies()
        }
    finally:
        if temp is not None:
            temp.cleanup()

    checked: list[EvidenceResult] = []
    for result in results:
        if not result.ok or not result.offset:
            checked.append(result)
            continue
        location = (result.method, int(result.offset, 16))
        if location in locations:
            checked.append(result)
        else:
            checked.append(
                EvidenceResult(
                    result.api,
                    result.shape,
                    result.evidence,
                    False,
                    "IL method body offset not found",
                    result.file,
                    result.method,
                    result.offset,
                )
            )
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="decompiled client source root")
    parser.add_argument(
        "--assembly",
        help="optional Assembly-CSharp.dll or UnityWebData container for IL offset checks",
    )
    parser.add_argument(
        "--entry", default="Assembly-CSharp.dll", help="UnityWebData entry name"
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args(argv)

    if not args.source and not args.assembly:
        parser.error("provide --source and/or --assembly")
    if args.source:
        source_root = Path(args.source).resolve()
        if not source_root.is_dir():
            parser.error(f"source directory not found: {source_root}")
        index = source_index(source_root)
        results = validate_evidence(BARE_MAP_EVIDENCE, "bare_map", index)
        results.extend(validate_evidence(SCALAR_ROOT_EVIDENCE, "scalar_root", index))
    else:
        results = parse_evidence(BARE_MAP_EVIDENCE, "bare_map")
        results.extend(parse_evidence(SCALAR_ROOT_EVIDENCE, "scalar_root"))
    if args.assembly:
        results = validate_il_offsets(results, args.assembly, args.entry)
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
