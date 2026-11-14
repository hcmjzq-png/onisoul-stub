"""PC assembly validation and decompile wrapper tests."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tools import check_pc_assembly, decompile_pc_assembly


def make_pe(
    *,
    mz: bytes = b"MZ",
    signature: bytes = b"PE\0\0",
    section_count: int = 1,
    raw_size: int = 0x200,
    cli_rva: int = 0x2000,
    cli_size: int = 0x48,
) -> bytes:
    data = bytearray(0x400)
    data[:2] = mz
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = signature

    machine_offset = 0x84
    optional_size = 0xE0
    struct.pack_into(
        "<HHIIIHH",
        data,
        machine_offset,
        0x14C,
        section_count,
        0,
        0,
        0,
        optional_size,
        0x2102,
    )

    optional_offset = 0x98
    struct.pack_into("<H", data, optional_offset, 0x10B)
    struct.pack_into("<I", data, optional_offset + 92, 16)
    cli_directory = optional_offset + 96 + 14 * 8
    struct.pack_into("<II", data, cli_directory, cli_rva, cli_size)

    section_offset = optional_offset + optional_size
    data[section_offset : section_offset + 8] = b".text\0\0\0"
    struct.pack_into(
        "<IIII", data, section_offset + 8, 0x200, 0x2000, raw_size, 0x200
    )

    struct.pack_into("<I", data, 0x200, 72)
    struct.pack_into("<II", data, 0x208, 0x2020, 0x40)
    data[0x220:0x224] = b"BSJB"
    struct.pack_into("<HHII", data, 0x224, 2, 5, 0, 11)
    data[0x230:0x230 + 11] = b"v2.0.50727\0"
    return bytes(data)


class CheckPcAssemblyTest(unittest.TestCase):
    def write_pe(self, payload: bytes) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "Assembly-CSharp.dll"
        path.write_bytes(payload)
        return temp, path

    def test_valid_pe_cli_reports_sections_and_metadata(self):
        temp, path = self.write_pe(make_pe())
        try:
            report = check_pc_assembly.inspect_assembly(path)
        finally:
            temp.cleanup()

        self.assertTrue(report["valid"])
        self.assertEqual(report["machine_name"], "I386")
        self.assertEqual(report["pe_kind"], "PE32")
        self.assertEqual(report["section_table"]["file_offset"], 0x178)
        self.assertEqual(report["sections"][0]["name"], ".text")
        self.assertEqual(report["cli"]["metadata_signature"], "BSJB")
        self.assertEqual(report["cli"]["runtime_version"], "v2.0.50727")
        self.assertEqual(len(report["sha256"]), 64)

    def test_json_cli_returns_zero(self):
        temp, path = self.write_pe(make_pe())
        stdout = StringIO()
        try:
            with redirect_stdout(stdout):
                code = check_pc_assembly.main(["--json", str(path)])
        finally:
            temp.cleanup()
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["valid"])

    def test_rejects_bad_mz_and_pe_signature(self):
        for payload in (make_pe(mz=b"XX"), make_pe(signature=b"PX\0\0")):
            with self.subTest(payload=payload[:2]):
                temp, path = self.write_pe(payload)
                try:
                    with self.assertRaises(check_pc_assembly.AssemblyFormatError):
                        check_pc_assembly.inspect_assembly(path)
                finally:
                    temp.cleanup()

    def test_rejects_truncated_section_table(self):
        temp, path = self.write_pe(make_pe(section_count=0xFFFF))
        try:
            with self.assertRaisesRegex(
                check_pc_assembly.AssemblyFormatError, "Section Table 不完整"
            ):
                check_pc_assembly.inspect_assembly(path)
        finally:
            temp.cleanup()

    def test_rejects_section_raw_data_past_eof(self):
        temp, path = self.write_pe(make_pe(raw_size=0xFFFF))
        try:
            with self.assertRaisesRegex(
                check_pc_assembly.AssemblyFormatError, "原始数据越界"
            ):
                check_pc_assembly.inspect_assembly(path)
        finally:
            temp.cleanup()

    def test_rejects_missing_cli_directory(self):
        temp, path = self.write_pe(make_pe(cli_rva=0, cli_size=0))
        try:
            with self.assertRaisesRegex(
                check_pc_assembly.AssemblyFormatError, "CLI Header 过短"
            ):
                check_pc_assembly.inspect_assembly(path)
        finally:
            temp.cleanup()

    def test_rejects_optional_header_without_full_cli_directory(self):
        payload = bytearray(make_pe())
        struct.pack_into("<H", payload, 0x94, 0x80)
        temp, path = self.write_pe(bytes(payload))
        try:
            with self.assertRaisesRegex(
                check_pc_assembly.AssemblyFormatError, "Optional Header 过短"
            ):
                check_pc_assembly.inspect_assembly(path)
        finally:
            temp.cleanup()

    def test_cli_error_returns_one(self):
        temp, path = self.write_pe(make_pe(mz=b"XX"))
        stderr = StringIO()
        try:
            with redirect_stderr(stderr):
                code = check_pc_assembly.main([str(path)])
        finally:
            temp.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("INVALID:", stderr.getvalue())


class DecompilePcAssemblyTest(unittest.TestCase):
    def test_rejects_output_inside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            with self.assertRaisesRegex(
                decompile_pc_assembly.DecompileError, "不能位于仓库内"
            ):
                decompile_pc_assembly.validate_output_dir(repo / "out", repo)

    def test_rejects_repository_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            traversal = repo / "work" / ".." / "decompiled"
            with self.assertRaisesRegex(
                decompile_pc_assembly.DecompileError, "不能位于仓库内"
            ):
                decompile_pc_assembly.validate_output_dir(traversal, repo)

    def test_rejects_nonempty_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            output = root / "out"
            repo.mkdir()
            output.mkdir()
            (output / "old.cs").write_text("class Old {}", encoding="utf-8")
            with self.assertRaisesRegex(
                decompile_pc_assembly.DecompileError, "输出目录必须为空"
            ):
                decompile_pc_assembly.validate_output_dir(output, repo)

    def test_build_command_supports_project_and_default_modes(self):
        tool = Path("C:/tools/ilspycmd.exe")
        assembly = Path("C:/input/Assembly-CSharp.dll")
        output = Path("C:/temp/out")
        default_command = decompile_pc_assembly.build_command(
            tool, assembly, output
        )
        project_command = decompile_pc_assembly.build_command(
            tool, assembly, output, project=True
        )
        self.assertNotIn("--project", default_command)
        self.assertIn("--project", project_command)
        self.assertIn("--referencepath", project_command)
        self.assertEqual(project_command[-1], str(assembly))


class AssemblyManifestTest(unittest.TestCase):
    def test_manifest_records_all_known_assemblies(self):
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "analysis"
            / "assembly_manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assemblies = manifest["assemblies"]
        self.assertEqual(len(assemblies), 12)
        self.assertEqual(len({item["name"] for item in assemblies}), 12)
        for item in assemblies:
            self.assertGreater(item["size_bytes"], 0)
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
        core = next(item for item in assemblies if item["name"] == "Assembly-CSharp.dll")
        self.assertEqual(core["size_bytes"], 4_584_448)
        self.assertEqual(
            core["sha256"],
            "b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e",
        )


if __name__ == "__main__":
    unittest.main()
