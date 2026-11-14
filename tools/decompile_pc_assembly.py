#!/usr/bin/env python3
"""Validate and decompile an extracted PC assembly with ilspycmd.

The output directory is mandatory, must be outside this repository, and must
be absent or empty. This keeps generated source and client binaries out of git.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from tools.check_pc_assembly import AssemblyFormatError, inspect_assembly
except ModuleNotFoundError:  # Direct execution: python tools/decompile_pc_assembly.py
    from check_pc_assembly import AssemblyFormatError, inspect_assembly

REPO_ROOT = Path(__file__).resolve().parents[1]


class DecompileError(RuntimeError):
    """Raised for unsafe output paths or a missing decompiler."""


def find_ilspycmd(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get("ILSPYCMD")
    if configured:
        candidates.append(Path(configured).expanduser())
    from_path = shutil.which("ilspycmd")
    if from_path:
        candidates.append(Path(from_path))
    candidates.extend(
        [
            Path.home() / ".cache" / "onisoul" / "tools" / "ilspycmd.exe",
            Path.home() / ".cache" / "onisoul" / "tools" / "ilspycmd",
        ]
    )
    if os.environ.get("ONISOUL_ALLOW_REPO_TOOL") == "1":
        candidates.extend(
            [
                REPO_ROOT / "work" / "tools" / "ilspycmd.exe",
                REPO_ROOT / "work" / "tools" / "ilspycmd",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise DecompileError(
        "找不到 ilspycmd；用 --ilspycmd 指定可执行文件，或设置 ILSPYCMD"
    )


def validate_output_dir(path: str | Path, repo_root: Path = REPO_ROOT) -> Path:
    output = Path(path).expanduser().resolve()
    repository = repo_root.resolve()
    try:
        output.relative_to(repository)
    except ValueError:
        pass
    else:
        raise DecompileError("反编译输出目录不能位于仓库内")

    if output.exists():
        if not output.is_dir():
            raise DecompileError(f"输出路径不是目录：{output}")
        if any(output.iterdir()):
            raise DecompileError(f"输出目录必须为空：{output}")
    return output


def build_command(
    ilspycmd: Path,
    assembly: Path,
    output: Path,
    project: bool = False,
) -> list[str]:
    command = [str(ilspycmd)]
    if project:
        command.append("--project")
    command.extend(["--outputdir", str(output), "--disable-updatecheck", str(assembly)])
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", help="提取出的 .NET 程序集")
    parser.add_argument("--out", required=True, help="仓库外的空输出目录")
    parser.add_argument(
        "--project",
        action="store_true",
        help="生成工程和逐类型源码；默认输出单个 C# 文件",
    )
    parser.add_argument("--ilspycmd", help="ilspycmd 可执行文件路径")
    args = parser.parse_args(argv)

    try:
        assembly = Path(args.assembly).expanduser().resolve()
        report = inspect_assembly(assembly)
        output = validate_output_dir(args.out)
        ilspycmd = find_ilspycmd(args.ilspycmd)
        output.mkdir(parents=True, exist_ok=True)
    except (AssemblyFormatError, DecompileError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"validated {assembly} sha256={report['sha256']}")
    command = build_command(ilspycmd, assembly, output, args.project)
    environment = os.environ.copy()
    environment["DOTNET_ROLL_FORWARD"] = "Major"
    try:
        completed = subprocess.run(
            command,
            cwd=assembly.parent,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f"ERROR: 无法启动 ilspycmd：{error}", file=sys.stderr)
        return 1
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.returncode != 0:
        print(f"ERROR: ilspycmd 退出码 {completed.returncode}", file=sys.stderr)
        if completed.stderr.strip():
            print(completed.stderr.strip(), file=sys.stderr)
        return completed.returncode

    source_files = list(output.rglob("*.cs"))
    if not source_files:
        print("ERROR: ilspycmd 返回成功，但没有生成 .cs 文件", file=sys.stderr)
        return 1
    print(f"decompiled {len(source_files)} .cs files to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
