"""Table import tool tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools import import_tables


class ImportTablesTest(unittest.TestCase):
    def test_imports_only_manifest_tables_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            dest = root / "dest"
            source.mkdir()
            manifest = root / "table_list.tsv"
            manifest.write_text(
                "table_file\troot_key\taccessor_classes\n"
                "building.json\tbuilding\tBuildingTableAccessor\n"
                "assetbundle.json\tassetbundle\tFileDataBase\n"
                "character.json\tcharacter\tCharacterTableAccessor\n",
                encoding="utf-8",
            )
            (source / "0123456789abcdef.unity3d__building.json").write_text(
                json.dumps({"building": {"castle": {}}}), encoding="utf-8"
            )
            (source / "app.unity3d__assetbundle.json").write_text(
                json.dumps({"assetbundle": {"scene": {}}}), encoding="utf-8"
            )
            (source / "not-declared.json").write_text("{}", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = import_tables.main(
                    [
                        "--source",
                        str(source),
                        "--dest",
                        str(dest),
                        "--manifest",
                        str(manifest),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue((dest / "building.json").is_file())
            self.assertTrue((dest / "assetbundle.json").is_file())
            self.assertFalse((dest / "not-declared.json").exists())
            report = json.loads((dest / "import-manifest.json").read_text(encoding="utf-8"))
            statuses = {item["file"]: item["status"] for item in report["tables"]}
            self.assertEqual(
                statuses,
                {
                    "building.json": "copied",
                    "assetbundle.json": "copied",
                    "character.json": "missing",
                },
            )
            self.assertIn("ready=2 missing=1 invalid=0", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
