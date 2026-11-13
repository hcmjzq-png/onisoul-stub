"""Manifest-backed table loading and hot-reload tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.tables import InvalidTableError, MissingTableError, TableCatalog, UnknownTableError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tables"


class TableCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.tables = root / "tables"
        self.tables.mkdir()
        self.manifest = root / "table_list.tsv"
        self.manifest.write_text(
            "table_file\troot_key\taccessor_classes\n"
            "building.json\tbuilding\tBuildingTableAccessor\n"
            "character.json\tcharacter\tCharacterTableAccessor\n"
            "cannon_shot.json\tcannon_shot\tCannonShotTableAccessor\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, path: Path, root_key: str, value: dict) -> None:
        path.write_text(json.dumps({root_key: value}), encoding="utf-8")

    def test_load_by_filename_or_root_key(self):
        path = self.tables / "building.json"
        self._write(path, "building", {"castle": {"level": 1}})
        catalog = TableCatalog(self.tables, self.manifest)

        self.assertEqual(catalog.load("building.json"), {"castle": {"level": 1}})
        self.assertEqual(catalog.load("building"), {"castle": {"level": 1}})

    def test_hot_reload_when_mtime_changes(self):
        path = self.tables / "building.json"
        base_ns = 1_700_000_000_000_000_000
        self._write(path, "building", {"castle": {"level": 1}})
        os.utime(path, ns=(base_ns, base_ns))
        catalog = TableCatalog(self.tables, self.manifest)
        self.assertEqual(catalog.load("building")["castle"]["level"], 1)

        self._write(path, "building", {"castle": {"level": 2}})
        os.utime(path, ns=(base_ns + 1_000_000, base_ns + 1_000_000))
        self.assertEqual(catalog.load("building")["castle"]["level"], 2)

    def test_missing_and_unknown_tables_are_distinct(self):
        catalog = TableCatalog(self.tables, self.manifest)
        with self.assertRaises(UnknownTableError):
            catalog.load("not_declared")
        with self.assertRaises(MissingTableError):
            catalog.load("building")
        self.assertEqual(
            catalog.missing(),
            ["building.json", "cannon_shot.json", "character.json"],
        )

    def test_wrong_root_key_is_invalid(self):
        path = self.tables / "building.json"
        self._write(path, "character", {})
        catalog = TableCatalog(self.tables, self.manifest)
        with self.assertRaises(InvalidTableError):
            catalog.load("building")

    def test_minijson_trailing_commas_are_accepted(self):
        (self.tables / "cannon_shot.json").write_bytes(
            (FIXTURES / "cannon_shot_trailing_commas.json").read_bytes()
        )
        catalog = TableCatalog(self.tables, self.manifest)
        records = catalog.load("cannon_shot")
        self.assertEqual(records["cannonShot00002"]["value"], 49)

    def test_first_document_is_used_when_json_is_concatenated(self):
        (self.tables / "building.json").write_bytes(
            (FIXTURES / "multi_document.json").read_bytes()
        )
        catalog = TableCatalog(self.tables, self.manifest)
        with self.assertLogs("app.minijson", level="DEBUG") as captured:
            self.assertEqual(
                catalog.load("building"),
                {"b1": {"id": "b1", "flags": [True, False]}},
            )
        self.assertIn("trailing bytes", "\n".join(captured.output))

    def test_import_manifest_checksum_drift_is_reported(self):
        path = self.tables / "building.json"
        self._write(path, "building", {"castle": {}})
        (self.tables / "import-manifest.json").write_text(
            json.dumps(
                {
                    "tables": [
                        {
                            "file": "building.json",
                            "sha256": "0" * 64,
                            "status": "copied",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        catalog = TableCatalog(self.tables, self.manifest)
        issues = catalog.check()
        self.assertTrue(any(issue.startswith("checksum drift: building.json") for issue in issues))


if __name__ == "__main__":
    unittest.main()
