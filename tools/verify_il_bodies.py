#!/usr/bin/env python3
"""Verify every MethodDef IL body in a OniSoul PC assembly.

Input may be an extracted ``Assembly-CSharp.dll`` or the 25-entry
UnityWebData container.  The tool fails closed: an unknown opcode, truncated
operand, instruction stream that does not land exactly on ``code_end``, or a
last instruction outside the permitted terminator set is reported as failure.

Examples:

    python tools/verify_il_bodies.py /path/to/Assembly-CSharp.dll --json
    python tools/verify_il_bodies.py /path/to/app_unity3d.bin \
        --entry Assembly-CSharp.dll
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from tools.oni_il import (
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
        read_unity_web_data,
    )
except ModuleNotFoundError:
    from oni_il import (  # type: ignore
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
        read_unity_web_data,
    )


def verify_assembly(
    path: str | Path, strict_terminators: bool = False
) -> dict[str, Any]:
    model = AssemblyModel(path)
    failures: list[dict[str, Any]] = []
    decoded = 0
    no_body = 0
    non_returning = 0
    instructions = 0
    for rid, owner, row in model.iter_method_rows():
        if row.Rva == 0:
            no_body += 1
            continue
        try:
            body = model.body_for_rid(
                rid, allow_nonreturning_br=not strict_terminators
            )
        except MethodDecodeError as error:
            failures.append(
                {
                    "token": f"0x{model.method_token(rid):08X}",
                    "owner": owner,
                    "method": str(row.Name),
                    "rva": f"0x{row.Rva:X}",
                    "error": str(error),
                }
            )
            continue
        decoded += 1
        instructions += len(body.body.instructions)
        non_returning += int(body.non_returning)
    return {
        "valid": not failures,
        "assembly": str(model.path),
        "sha256": hashlib.sha256(model.data).hexdigest(),
        "methoddef_total": len(model.method_rows),
        "with_body": decoded + len(failures),
        "without_body": no_body,
        "decoded": decoded,
        "instruction_count": instructions,
        "non_returning_br": non_returning,
        "failure_count": len(failures),
        "failures": failures,
    }


def resolve_input(path: str | Path, entry: str) -> tuple[Path, dict[str, Any] | None, tempfile.TemporaryDirectory[str] | None]:
    source = Path(path).expanduser().resolve()
    if not is_unity_web_data(source):
        return source, None, None
    container = read_unity_web_data(source)
    temp = tempfile.TemporaryDirectory(prefix="onisoul-il-")
    destination = Path(temp.name) / entry
    extracted = extract_container_entry(source, entry, destination)
    metadata = {
        "container": str(source),
        "container_entry_count": container.count,
        "container_data_offset": container.data_offset,
        **extracted,
    }
    return destination, metadata, temp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Assembly-CSharp.dll or UnityWebData container")
    parser.add_argument(
        "--entry",
        default="Assembly-CSharp.dll",
        help="entry to extract from UnityWebData (default: Assembly-CSharp.dll)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--strict-terminators",
        action="store_true",
        help="reject the three valid compiler-generated methods ending in an infinite br",
    )
    args = parser.parse_args(argv)

    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        assembly, container, temp = resolve_input(args.input, args.entry)
        report = verify_assembly(assembly, args.strict_terminators)
        if container:
            report["container"] = container
    except (OSError, OniAnalysisError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.cleanup()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "[verify-il] "
            f"methoddef={report['methoddef_total']} "
            f"with_body={report['with_body']} "
            f"decoded={report['decoded']} "
            f"no_body={report['without_body']} "
            f"instructions={report['instruction_count']} "
            f"non_returning_br={report['non_returning_br']} "
            f"failed={report['failure_count']}"
        )
        for failure in report["failures"]:
            print(
                "[verify-il] "
                f"{failure['token']} {failure['owner']}::{failure['method']} "
                f"{failure['rva']}: {failure['error']}"
            )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
