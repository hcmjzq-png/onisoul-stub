"""Byte-exact extraction, including the Unicode corruption found in production."""
import struct
import unittest

from app.minijson import parse_json_document
from tools.extract_tables_from_bundle import extract_assets


def asset(name: str, script: bytes) -> bytes:
    name_bytes = name.encode("ascii")
    header = struct.pack("<I", len(name_bytes)) + name_bytes
    header += b"\0" * (-len(header) % 4)
    result = header + struct.pack("<I", len(script)) + script
    return result + b"\0" * (-len(result) % 4)


class TableExtractionTest(unittest.TestCase):
    def test_preserves_unicode_and_comma_sequences_inside_strings(self):
        raw = '{"country_setting":{"country37":{"defaultMapName":"城", "note":"原文,}",},},}'.encode()
        found = extract_assets(asset("country_setting.json", raw), {"country_setting.json": "country_setting"})
        result = found["country_setting.json"]
        self.assertEqual(result.raw, raw)
        row = parse_json_document(result.raw)["country_setting"]["country37"]
        self.assertEqual(row, {"defaultMapName": "城", "note": "原文,}"})
        self.assertEqual(result.rows, 1)

    def test_root_markers_alone_do_not_count_as_textassets(self):
        data = b'{"quest_1_0000":{"id":{}}}'
        self.assertEqual(extract_assets(data, {"quest_1_0000.json": "quest_1_0000"}), {})

    def test_wrong_root_truncated_script_and_invalid_utf8_are_rejected(self):
        name = "quest_1_0000.json"
        declared = {name: "quest_1_0000"}
        samples = [asset(name, b'{"wrong":{}}'), asset(name, b'{"quest_1_0000":{"x":"\xff"}}'),
                   asset(name, b'{"quest_1_0000":{}}')[:-8]]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(extract_assets(sample, declared), {})

    def test_empty_tables_are_valid_and_undeclared_names_are_ignored(self):
        name = "quest_1_0000.json"
        data = asset(name, b'{"quest_1_0000":{}}') + asset("other.json", b'{"other":{}}')
        found = extract_assets(data, {name: "quest_1_0000"})
        self.assertEqual(list(found), [name])
        self.assertEqual(found[name].rows, 0)

    def test_duplicate_named_assets_are_ambiguous(self):
        name = "quest_1_0000.json"
        data = asset(name, b'{"quest_1_0000":{}}')
        with self.assertRaisesRegex(ValueError, "duplicate TextAsset"):
            extract_assets(data + data, {name: "quest_1_0000"})
