"""Manifest-backed table loading and hot-reload tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.tables import InvalidTableError, MissingTableError, TableCatalog, UnknownTableError


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
            "character.json\tcharacter\tCharacterTableAccessor\n",
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
        self.assertEqual(catalog.missing(), ["building.json", "character.json"])

    def test_wrong_root_key_is_invalid(self):
        path = self.tables / "building.json"
        self._write(path, "character", {})
        catalog = TableCatalog(self.tables, self.manifest)
        with self.assertRaises(InvalidTableError):
            catalog.load("building")


if __name__ == "__main__":
    unittest.main()
