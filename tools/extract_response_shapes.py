#!/usr/bin/env python3
"""Emit the response-shape verdict for every contract endpoint.

Bare-map overrides come from ``app.business.response_shapes`` and now carry PC
IL method-body offsets. All other endpoints use the common WebApiClient
envelope/error path, whose IL evidence is emitted on every row.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
from pathlib import Path

try:
    from tools.oni_il import (
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
        parse_tsv_rows,
    )
except ModuleNotFoundError:
    from oni_il import (  # type: ignore
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
        parse_tsv_rows,
    )

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.business.response_shapes import (  # noqa: E402
    BARE_MAP_EVIDENCE,
    SCALAR_ROOT_EVIDENCE,
)

EVIDENCE_RE = re.compile(r"^(?P<file>[^:]+\.cs):(?P<method>[^@]+)@0x(?P<offset>[0-9A-Fa-f]+)$")
FIELDS = ["endpoint", "shape", "evidence", "evidence_offset", "basis"]


def _method_evidence(model: AssemblyModel, value: str) -> tuple[str, int]:
    matched = EVIDENCE_RE.fullmatch(value)
    if matched is None:
        raise OniAnalysisError(f"invalid evidence syntax: {value}")
    name = matched.group("method")
    offset = int(matched.group("offset"), 16)
    matches = [
        body
        for body in model.iter_bodies()
        if body.name == name and model.image_offset(body.file_offset) == offset
    ]
    if len(matches) != 1:
        raise OniAnalysisError(
            f"evidence {value} resolves to {len(matches)} method bodies"
        )
    body = matches[0]
    return body.display_name, offset


def _global_envelope_evidence(model: AssemblyModel) -> tuple[str, int]:
    by_name = {}
    for body in model.iter_bodies():
        if body.owner == "WebApiClient" and body.name in ("_httpCall", "CheckExceedTimes"):
            by_name[body.name] = body
    missing = {"_httpCall", "CheckExceedTimes"} - set(by_name)
    if missing:
        raise OniAnalysisError(f"missing WebApiClient methods: {', '.join(sorted(missing))}")
    offset = model.image_offset(by_name["_httpCall"].file_offset)
    return (
        f"WebApiClient::_httpCall@0x{model.image_offset(by_name['_httpCall'].file_offset):X} -> "
        f"WebApiClient::CheckExceedTimes@0x{model.image_offset(by_name['CheckExceedTimes'].file_offset):X}",
        offset,
    )


def extract(
    model: AssemblyModel, contract_path: Path
) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows = parse_tsv_rows(contract_path, ["endpoint"])
    envelope, envelope_offset = _global_envelope_evidence(model)
    evidence_bodies: dict[str, tuple[str, int]] = {}
    for api, value in {**BARE_MAP_EVIDENCE, **SCALAR_ROOT_EVIDENCE}.items():
        evidence_bodies[api] = _method_evidence(model, value)

    output: list[dict[str, str]] = []
    for row in rows:
        endpoint = row["endpoint"]
        if endpoint in BARE_MAP_EVIDENCE:
            shape = "bare_map"
            evidence = BARE_MAP_EVIDENCE[endpoint]
            source_method, offset = evidence_bodies[endpoint]
            basis = f"root enumeration override: {source_method}"
        else:
            shape = "envelope"
            evidence = envelope
            offset = envelope_offset
            basis = "default successful/error envelope path"
        output.append(
            {
                "endpoint": endpoint,
                "shape": shape,
                "evidence": evidence,
                "evidence_offset": f"0x{offset:X}",
                "basis": basis,
            }
        )
    stats = {
        "endpoints": len(output),
        "bare_map": sum(row["shape"] == "bare_map" for row in output),
        "envelope": sum(row["shape"] == "envelope" for row in output),
        "scalar_root": len(SCALAR_ROOT_EVIDENCE),
    }
    return output, stats


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="assembly DLL or UnityWebData container")
    parser.add_argument(
        "--entry", default="Assembly-CSharp.dll", help="UnityWebData entry name"
    )
    parser.add_argument(
        "--contract",
        default=str(ROOT / "docs/analysis/api_contract.tsv"),
        help="api_contract.tsv",
    )
    parser.add_argument("--out", required=True, help="output TSV")
    args = parser.parse_args(argv)

    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source = Path(args.input).expanduser().resolve()
        if is_unity_web_data(source):
            temp = tempfile.TemporaryDirectory(prefix="onisoul-shapes-")
            assembly = Path(temp.name) / args.entry
            extracted = extract_container_entry(source, args.entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        rows, stats = extract(model, Path(args.contract))
        write_tsv(Path(args.out), rows)
        print(
            "[response-shapes] "
            f"endpoints={stats['endpoints']} "
            f"bare_map={stats['bare_map']} envelope={stats['envelope']} "
            f"scalar_root={stats['scalar_root']}"
        )
    except (OSError, OniAnalysisError, MethodDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
