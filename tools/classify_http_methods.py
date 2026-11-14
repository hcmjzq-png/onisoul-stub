#!/usr/bin/env python3
"""Classify WebApiClient endpoints as HTTP GET or POST from IL.

``WebApiClient._httpCall`` creates a ``WWWForm`` only when the request
parameter object is non-null. ``sendRequest`` then uses ``WWW(url)`` for the
null-form path and ``WWW(url, form.data, headers)`` for the non-null path.
This tool follows every literal endpoint passed to ``httpCall`` and classifies
the immediately preceding parameter producer.
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools.oni_il import (
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
    )
except ModuleNotFoundError:
    from oni_il import (  # type: ignore
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        extract_container_entry,
        is_unity_web_data,
    )


FIELDS = [
    "endpoint",
    "webapi_method",
    "http_method",
    "parameter_form",
    "evidence",
]


def _value(insn: Any) -> Any:
    return getattr(insn.operand, "value", insn.operand)


def classify_http_methods(model: AssemblyModel) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for body in model.iter_bodies():
        instructions = body.body.instructions
        for index, insn in enumerate(instructions):
            target = model.instruction_target(insn)
            if target is None or target.display_name != "WebApiClient::httpCall":
                continue
            endpoint = None
            endpoint_index = None
            parameter = None
            for probe in range(index - 1, max(-1, index - 14), -1):
                text = model.instruction_string(instructions[probe])
                if text is not None and "/" in text:
                    endpoint = text
                    endpoint_index = probe
                    if probe + 1 < index:
                        parameter = instructions[probe + 1]
                    break
            if endpoint is None or endpoint_index is None or parameter is None:
                raise OniAnalysisError(
                    f"cannot classify httpCall in {body.display_name} "
                    f"at IL_{insn.offset:04X}"
                )
            if parameter.opcode.name == "ldnull":
                http_method = "GET"
                parameter_form = "null"
            elif parameter.opcode.name == "newobj":
                parameter_form = "new-object"
                http_method = "POST"
            elif parameter.opcode.name.startswith("ldloc"):
                parameter_form = "local"
                http_method = "POST"
            elif parameter.opcode.name.startswith("ldarg"):
                parameter_form = "argument"
                http_method = "POST"
            else:
                parameter_form = parameter.opcode.name
                http_method = "POST"
            rows.append(
                {
                    "endpoint": endpoint,
                    "webapi_method": body.name,
                    "http_method": http_method,
                    "parameter_form": parameter_form,
                    "evidence": (
                        f"{body.owner}::{body.name}@"
                        f"0x{model.image_offset(instructions[endpoint_index].offset):X}"
                    ),
                }
            )
    return sorted(rows, key=lambda row: (row["endpoint"], row["webapi_method"], row["evidence"]))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
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
    parser.add_argument("--out", required=True, help="output TSV")
    args = parser.parse_args(argv)

    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source = Path(args.input).expanduser().resolve()
        if is_unity_web_data(source):
            temp = tempfile.TemporaryDirectory(prefix="onisoul-http-")
            assembly = Path(temp.name) / args.entry
            extracted = extract_container_entry(source, args.entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        rows = classify_http_methods(model)
        write_rows(Path(args.out), rows)
        methods = Counter(row["http_method"] for row in rows)
        endpoints = {row["endpoint"] for row in rows}
        print(
            "[http-method] "
            f"callsites={len(rows)} endpoints={len(endpoints)} "
            f"GET={methods['GET']} POST={methods['POST']}"
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
