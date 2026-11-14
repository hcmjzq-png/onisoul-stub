#!/usr/bin/env python3
"""Validate the PE/CLI structure of an extracted PC assembly.

The validator is intentionally read-only and uses only the Python standard
library. It checks the headers needed before handing a DLL to dnfile, dncil,
or ilspycmd; it does not execute the assembly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

CLI_HEADER_DIRECTORY_INDEX = 14
CLI_HEADER_MIN_SIZE = 72
METADATA_SIGNATURE = b"BSJB"

MACHINE_NAMES = {
    0x014C: "I386",
    0x8664: "AMD64",
    0x01C0: "ARM",
    0xAA64: "ARM64",
}

# Machine 与 PE 种类必须自洽：32 位机器只能配 PE32，64 位机器只能配 PE32+
EXPECTED_PE_KIND = {
    0x014C: "PE32",
    0x01C0: "PE32",
    0x8664: "PE32+",
    0xAA64: "PE32+",
}


class AssemblyFormatError(ValueError):
    """Raised when a file is not a supported PE/CLI assembly."""


def _unpack_u16(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise AssemblyFormatError(f"{label} 越过文件末尾")
    return struct.unpack_from("<H", data, offset)[0]


def _unpack_u32(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise AssemblyFormatError(f"{label} 越过文件末尾")
    return struct.unpack_from("<I", data, offset)[0]


def _rva_to_file_offset(
    sections: list[dict[str, Any]], rva: int, size: int, label: str
) -> int:
    if rva <= 0 or size <= 0:
        raise AssemblyFormatError(f"{label} 的 RVA/大小必须大于 0")

    for section in sections:
        virtual_address = section["virtual_address"]
        virtual_size = max(section["virtual_size"], section["raw_data_size"])
        if virtual_address <= rva and rva + size <= virtual_address + virtual_size:
            delta = rva - virtual_address
            if delta + size > section["raw_data_size"]:
                raise AssemblyFormatError(f"{label} 位于节区的非文件映射部分")
            return section["raw_data_offset"] + delta
    raise AssemblyFormatError(f"{label} 的 RVA 0x{rva:x} 不属于任何节区")


def inspect_assembly(path: str | Path) -> dict[str, Any]:
    """Parse one PE/CLI assembly and return its stable structural facts."""
    assembly_path = Path(path).expanduser()
    data = assembly_path.read_bytes()
    size = len(data)

    if size < 64:
        raise AssemblyFormatError(f"文件过短：{size} B")
    if data[:2] != b"MZ":
        raise AssemblyFormatError("缺少 MZ 头")

    pe_offset = _unpack_u32(data, 0x3C, "e_lfanew")
    if pe_offset + 24 > size:
        raise AssemblyFormatError(f"e_lfanew=0x{pe_offset:x} 指向的 PE 头不完整")
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise AssemblyFormatError("缺少 PE 签名")

    coff_offset = pe_offset + 4
    machine = _unpack_u16(data, coff_offset, "Machine")
    section_count = _unpack_u16(data, coff_offset + 2, "NumberOfSections")
    optional_size = _unpack_u16(data, coff_offset + 16, "SizeOfOptionalHeader")
    optional_offset = coff_offset + 20
    if section_count == 0:
        raise AssemblyFormatError("节区数量为 0")
    if optional_offset + optional_size > size:
        raise AssemblyFormatError("Optional Header 越过文件末尾")

    magic = _unpack_u16(data, optional_offset, "Optional Header Magic")
    if magic == 0x10B:
        pe_kind = "PE32"
        directory_count_offset = 92
        directory_offset = 96
    elif magic == 0x20B:
        pe_kind = "PE32+"
        directory_count_offset = 108
        directory_offset = 112
    else:
        raise AssemblyFormatError(f"不支持的 Optional Header Magic：0x{magic:04x}")

    expected_kind = EXPECTED_PE_KIND.get(machine)
    if expected_kind and expected_kind != pe_kind:
        raise AssemblyFormatError(
            f"Machine 与 PE 种类不自洽：0x{machine:04x} "
            f"({MACHINE_NAMES[machine]}) 应为 {expected_kind}，实际 {pe_kind}"
        )
    required_optional_size = directory_offset + (CLI_HEADER_DIRECTORY_INDEX + 1) * 8
    if required_optional_size > optional_size:
        raise AssemblyFormatError(
            f"Optional Header 过短：需要至少 {required_optional_size} B，"
            f"实际 {optional_size} B"
        )

    section_table_offset = optional_offset + optional_size
    section_table_size = section_count * 40
    section_table_end = section_table_offset + section_table_size
    if section_table_end > size:
        raise AssemblyFormatError(
            f"Section Table 不完整：需要到 0x{section_table_end:x}，文件为 0x{size:x}"
        )

    sections: list[dict[str, Any]] = []
    for index in range(section_count):
        offset = section_table_offset + index * 40
        raw_name = data[offset : offset + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", "replace")
        virtual_size = _unpack_u32(data, offset + 8, f"{name}.VirtualSize")
        virtual_address = _unpack_u32(data, offset + 12, f"{name}.VirtualAddress")
        raw_data_size = _unpack_u32(data, offset + 16, f"{name}.SizeOfRawData")
        raw_data_offset = _unpack_u32(data, offset + 20, f"{name}.PointerToRawData")
        if raw_data_size:
            raw_end = raw_data_offset + raw_data_size
            if raw_data_offset > size or raw_end > size:
                raise AssemblyFormatError(
                    f"节区 {name} 的原始数据越界：0x{raw_data_offset:x}+"
                    f"0x{raw_data_size:x} > 0x{size:x}"
                )
        sections.append(
            {
                "name": name,
                "virtual_address": virtual_address,
                "virtual_size": virtual_size,
                "raw_data_offset": raw_data_offset,
                "raw_data_size": raw_data_size,
            }
        )

    directory_count_absolute = optional_offset + directory_count_offset
    directory_absolute = optional_offset + directory_offset
    directory_count = _unpack_u32(
        data, directory_count_absolute, "NumberOfRvaAndSizes"
    )
    if directory_count <= CLI_HEADER_DIRECTORY_INDEX:
        raise AssemblyFormatError("PE Data Directory 中没有 CLI Header")
    cli_directory_offset = directory_absolute + CLI_HEADER_DIRECTORY_INDEX * 8
    if cli_directory_offset + 8 > optional_offset + optional_size:
        raise AssemblyFormatError("CLI Data Directory 越过 Optional Header")

    cli_rva = _unpack_u32(data, cli_directory_offset, "CLI Header RVA")
    cli_size = _unpack_u32(data, cli_directory_offset + 4, "CLI Header Size")
    if cli_size < CLI_HEADER_MIN_SIZE:
        raise AssemblyFormatError(f"CLI Header 过短：{cli_size} B")
    cli_offset = _rva_to_file_offset(sections, cli_rva, cli_size, "CLI Header")
    cli_header_size = _unpack_u32(data, cli_offset, "CLI Header cb")
    if cli_header_size < CLI_HEADER_MIN_SIZE:
        raise AssemblyFormatError(f"CLI Header.cb 过短：{cli_header_size} B")
    if cli_header_size > cli_size:
        raise AssemblyFormatError(
            f"CLI Header.cb 超出 Data Directory：{cli_header_size} > {cli_size}"
        )

    metadata_rva = _unpack_u32(data, cli_offset + 8, "Metadata RVA")
    metadata_size = _unpack_u32(data, cli_offset + 12, "Metadata Size")
    if metadata_size < 16:
        raise AssemblyFormatError(f"CLI Metadata 过短：{metadata_size} B")
    metadata_offset = _rva_to_file_offset(
        sections, metadata_rva, metadata_size, "CLI Metadata"
    )
    if data[metadata_offset : metadata_offset + 4] != METADATA_SIGNATURE:
        raise AssemblyFormatError("CLI Metadata 缺少 BSJB 签名")

    version_length = _unpack_u32(data, metadata_offset + 12, "Metadata VersionLength")
    if version_length == 0 or 16 + version_length > metadata_size:
        raise AssemblyFormatError(f"CLI Metadata 版本串长度非法：{version_length}")
    runtime_version = (
        data[metadata_offset + 16 : metadata_offset + 16 + version_length]
        .split(b"\0", 1)[0]
        .decode("ascii", "replace")
    )

    return {
        "valid": True,
        "path": str(assembly_path.resolve()),
        "size": size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "pe_offset": pe_offset,
        "machine": machine,
        "machine_name": MACHINE_NAMES.get(machine, f"0x{machine:04x}"),
        "pe_kind": pe_kind,
        "optional_header_magic": magic,
        "section_table": {
            "file_offset": section_table_offset,
            "entry_size": 40,
            "size": section_table_size,
        },
        "sections": sections,
        "cli": {
            "header_rva": cli_rva,
            "header_size": cli_size,
            "metadata_rva": metadata_rva,
            "metadata_size": metadata_size,
            "metadata_signature": METADATA_SIGNATURE.decode("ascii"),
            "runtime_version": runtime_version,
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"VALID {report['path']}")
    print(f"  size={report['size']} sha256={report['sha256']}")
    print(
        f"  machine={report['machine_name']} (0x{report['machine']:04x}) "
        f"format={report['pe_kind']} e_lfanew=0x{report['pe_offset']:x}"
    )
    table = report["section_table"]
    print(
        f"  Section Table offset=0x{table['file_offset']:x} "
        f"size={table['size']} entries={len(report['sections'])}"
    )
    for section in report["sections"]:
        print(
            "    {name:<8} RVA=0x{va:08x} VS=0x{vs:08x} "
            "RAW=0x{raw:08x}+0x{size:08x}".format(
                name=section["name"],
                va=section["virtual_address"],
                vs=section["virtual_size"],
                raw=section["raw_data_offset"],
                size=section["raw_data_size"],
            )
        )
    cli = report["cli"]
    print(
        f"  CLI Header RVA=0x{cli['header_rva']:x}+0x{cli['header_size']:x}; "
        f"Metadata RVA=0x{cli['metadata_rva']:x}+0x{cli['metadata_size']:x}; "
        f"runtime={cli['runtime_version']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", help="提取出的 .NET 程序集，如 Assembly-CSharp.dll")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    try:
        report = inspect_assembly(args.assembly)
    except (AssemblyFormatError, OSError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
