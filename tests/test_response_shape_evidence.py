"""Response-shape evidence verification tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.verify_response_shape_evidence import source_index, validate_evidence


class EvidenceVerificationTest(unittest.TestCase):
    def test_requires_a_real_method_declaration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Sample.cs"
            source.write_text(
                "public class Sample {\n"
                "  private void onQuestChapterData(object result) {}\n"
                "  public static Hashtable convertRewardByUsePotionsAPIResult(Hashtable res) { return res; }\n"
                "  private void caller() { helper(); }\n"
                "}\n",
                encoding="utf-8",
            )
            index = source_index(root)

            valid = validate_evidence(
                {
                    "test/chapter": "Sample.cs:onQuestChapterData",
                    "test/potion": "Sample.cs:convertRewardByUsePotionsAPIResult",
                },
                "scalar_root",
                index,
            )
            self.assertTrue(all(result.ok for result in valid))

            invalid = validate_evidence(
                {"test/call-only": "Sample.cs:helper"}, "scalar_root", index
            )
            self.assertEqual(invalid[0].error, "method declaration not found")

    def test_rejects_missing_file_and_bad_syntax(self):
        with tempfile.TemporaryDirectory() as temp:
            index = source_index(Path(temp))
            results = validate_evidence(
                {
                    "test/missing": "Missing.cs:method",
                    "test/syntax": "not-a-shape-rule",
                },
                "bare_map",
                index,
            )
            errors = {result.api: result.error for result in results}
            self.assertEqual(errors["test/missing"], "source file not found")
            self.assertEqual(errors["test/syntax"], "invalid file:method syntax")


if __name__ == "__main__":
    unittest.main()
