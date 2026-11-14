#!/usr/bin/env python3
"""Build a key/type table from IL ``ldstr + get_Item + unbox.any`` evidence.

Output columns:

    key  token  type_full_name  clr_type  table  owner  method  file_offset

``file_offset`` is the absolute offset of the ``ldstr`` instruction in the
PE image (or in the extracted DLL when a UnityWebData input is used).
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
        TABLE_NAMES,
        extract_container_entry,
        is_unity_web_data,
        read_unity_web_data,
    )
except ModuleNotFoundError:
    from oni_il import (  # type: ignore
        AssemblyModel,
        MethodDecodeError,
        OniAnalysisError,
        TABLE_NAMES,
        extract_container_entry,
        is_unity_web_data,
        read_unity_web_data,
    )


FIELDS = [
    "key",
    "token",
    "type_full_name",
    "clr_type",
    "table",
    "owner",
    "method",
    "file_offset",
]


def _instruction_value(insn: Any) -> Any:
    return getattr(insn.operand, "value", insn.operand)


def extract_key_types(model: AssemblyModel) -> tuple[list[dict[str, str]], Counter[str]]:
    rows: dict[tuple[str, int], dict[str, str]] = {}
    stats: Counter[str] = Counter()
    for body in model.iter_bodies():
        instructions = body.body.instructions
        for index, insn in enumerate(instructions):
            key = model.instruction_string(insn)
            if key is None:
                continue
            get_index: int | None = None
            for probe in range(index + 1, min(index + 7, len(instructions))):
                target = model.instruction_target(instructions[probe])
                if target is None:
                    continue
                if target.name == "ContainsKey":
                    stats["key_checks"] += 1
                    break
                if target.name == "get_Item":
                    get_index = probe
                    break
            if get_index is None:
                continue
            stats["typed_read_candidates"] += 1
            type_insn = None
            for probe in range(get_index + 1, min(get_index + 9, len(instructions))):
                candidate = instructions[probe]
                if candidate.opcode.name in (
                    "box",
                    "castclass",
                    "isinst",
                    "unbox.any",
                ):
                    type_insn = candidate
                    break
                if candidate.opcode.name.startswith(("stloc", "stfld", "stsfld")):
                    break
            if type_insn is None:
                stats["untyped_reads"] += 1
                continue
            sig = model.instruction_type(type_insn)
            if sig is None or sig.token is None:
                stats["unresolved_types"] += 1
                continue
            table = TABLE_NAMES.get((sig.token >> 24) & 0xFF, "?")
            token_text = f"0x{sig.token:08X}"
            row = {
                "key": key,
                "token": token_text,
                "type_full_name": sig.full_name,
                "clr_type": sig.clr_name,
                "table": table,
                "owner": body.owner,
                "method": body.name,
                "file_offset": f"0x{model.image_offset(insn.offset):X}",
            }
            rows.setdefault((key, sig.token), row)
            stats[f"type:{sig.clr_name}"] += 1

    # Keep a complete unbox.any token map even when the token is not associated
    # with a named get_Item key (notably DictionaryEntry in foreach loops).
    emitted_tokens = {token for _key, token in rows}
    for body in model.iter_bodies():
        for insn in body.body.instructions:
            if insn.opcode.name != "unbox.any":
                continue
            sig = model.instruction_type(insn)
            if sig is None or sig.token is None or sig.token in emitted_tokens:
                continue
            table = TABLE_NAMES.get((sig.token >> 24) & 0xFF, "?")
            rows.setdefault(
                ("", sig.token),
                {
                    "key": "",
                    "token": f"0x{sig.token:08X}",
                    "type_full_name": sig.full_name,
                    "clr_type": sig.clr_name,
                    "table": table,
                    "owner": body.owner,
                    "method": body.name,
                    "file_offset": f"0x{model.image_offset(insn.offset):X}",
                },
            )
            emitted_tokens.add(sig.token)
            stats[f"unbox-token:{sig.clr_name}"] += 1
    return list(rows.values()), stats


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
            temp = tempfile.TemporaryDirectory(prefix="onisoul-keytypes-")
            assembly = Path(temp.name) / args.entry
            extracted = extract_container_entry(source, args.entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        rows, stats = extract_key_types(model)
        write_rows(Path(args.out), rows)
        print(
            "[key-types] "
            f"rows={len(rows)} keys={len({row['key'] for row in rows if row['key']})} "
            f"typed_candidates={stats['typed_read_candidates']} "
            f"untyped={stats['untyped_reads']} "
            f"unresolved={stats['unresolved_types']}"
        )
        for name, count in sorted(stats.items()):
            if name.startswith("type:"):
                print(f"[key-types] {name[5:]}={count}")
    except (OSError, OniAnalysisError, MethodDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        if temp is not None:
            temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
