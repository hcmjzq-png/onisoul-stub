#!/usr/bin/env python3
"""Recompute unguarded IL key reads on the corrected container mapping.

The strict pattern is:

    ldstr "K" ... call[virt] Hashtable.get_Item

with no earlier ``ldstr "K" ... call[virt] ContainsKey`` in the same method.
Offsets are absolute offsets in the UnityWebData source container.
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


FIELDS = ["owner", "method", "key", "type", "file_offset", "body_offset"]


def _previous_key(model: AssemblyModel, instructions: list[Any], index: int) -> str | None:
    for probe in range(index - 1, max(-1, index - 6), -1):
        text = model.instruction_string(instructions[probe])
        if text is not None:
            return text
        if instructions[probe].opcode.name.startswith(("stloc", "stfld", "call", "callvirt")):
            break
    return None


def scan(model: AssemblyModel) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for body in model.iter_bodies():
        instructions = body.body.instructions
        checked: set[str] = set()
        for index, insn in enumerate(instructions):
            target = model.instruction_target(insn)
            if target is not None and target.name in ("ContainsKey", "get_Item"):
                key = _previous_key(model, instructions, index)
                if key is None:
                    continue
                if target.name == "ContainsKey":
                    checked.add(key)
                    continue
                if key in checked:
                    continue
                type_name = ""
                for probe in range(index + 1, min(index + 9, len(instructions))):
                    candidate = instructions[probe]
                    if candidate.opcode.name in ("box", "castclass", "isinst", "unbox.any"):
                        sig = model.instruction_type(candidate)
                        if sig is not None:
                            type_name = sig.clr_name
                        break
                    if candidate.opcode.name.startswith(("stloc", "stfld", "stsfld")):
                        break
                rows.append(
                    {
                        "owner": body.owner,
                        "method": body.name,
                        "key": key,
                        "type": type_name,
                        "file_offset": f"0x{model.image_offset(insn.offset):X}",
                        "body_offset": f"0x{model.image_offset(body.file_offset):X}",
                    }
                )
    return sorted(
        rows,
        key=lambda row: (int(row["file_offset"], 16), row["owner"], row["method"]),
    )


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, str]], stats: Counter[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# IL 无守卫键读取清单\n\n")
        stream.write(
            "本文件由 `tools/il_unguarded_reads.py` 从 "
            "`app_unity3d.bin -> Assembly-CSharp.dll` 的 IL 重算。唯一偏移口径是：\n\n"
            "```text\n"
            "UnityWebData entry offset + extracted DLL file offset\n"
            "```\n\n"
            "判定模式：\n\n"
            "```text\n"
            "ldstr K; ...; call/callvirt get_Item\n"
            "```\n\n"
            "仅当同一方法内该 `get_Item` 之前没有 `ldstr K; ...; ContainsKey` 时列入。"
            "未知 opcode、截断操作数或 method body 未精确落在 `code_end` 时，扫描器直接失败。\n\n"
        )
        stream.write(f"- 无守卫读取点：{stats['rows']}\n")
        stream.write(f"- 涉及方法：{stats['methods']}\n")
        stream.write(f"- 涉及键：{stats['keys']}\n\n")
        stream.write("## 全量清单\n\n")
        stream.write("| 文件偏移 | 方法 | 键 | 类型 |\n")
        stream.write("|---:|---|---|---|\n")
        for row in rows:
            type_name = row["type"] or "?"
            stream.write(
                f"| `{row['file_offset']}` | `{row['owner']}::{row['method']}` "
                f"| `{row['key']}` | `{type_name}` |\n"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="assembly DLL or UnityWebData container")
    parser.add_argument(
        "--entry", default="Assembly-CSharp.dll", help="UnityWebData entry name"
    )
    parser.add_argument("--out-tsv", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args(argv)

    temp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source = Path(args.input).expanduser().resolve()
        if is_unity_web_data(source):
            temp = tempfile.TemporaryDirectory(prefix="onisoul-unguarded-")
            assembly = Path(temp.name) / args.entry
            extracted = extract_container_entry(source, args.entry, assembly)
            image_offset_base = int(extracted["offset"])
        else:
            assembly = source
            image_offset_base = 0
        model = AssemblyModel(assembly, image_offset_base=image_offset_base)
        rows = scan(model)
        stats = Counter(
            rows=len(rows),
            methods=len({(row["owner"], row["method"]) for row in rows}),
            keys=len({row["key"] for row in rows}),
        )
        write_tsv(Path(args.out_tsv), rows)
        write_markdown(Path(args.out_md), rows, stats)
        print(
            "[il-unguarded] "
            f"reads={stats['rows']} methods={stats['methods']} keys={stats['keys']}"
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
