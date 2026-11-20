"""Consistency checks for the checked-in IL analysis artifacts."""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "docs" / "analysis"
CONTAINER_SIZE = 19_463_656
ASSEMBLY_ENTRY_OFFSET = 1_474_648


def rows(name: str) -> list[dict[str, str]]:
    with (ANALYSIS / name).open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


class IlArtifactTest(unittest.TestCase):
    def test_http_methods_cover_the_contract(self):
        contract = {row["endpoint"] for row in rows("api_contract.tsv")}
        method_rows = rows("http_method.tsv")
        self.assertEqual({row["endpoint"] for row in method_rows}, contract)
        self.assertEqual(len(contract), 402)
        self.assertEqual(sum(row["http_method"] == "GET" for row in method_rows), 1)
        revision = [
            row for row in method_rows if row["endpoint"] == "common/getRevisions"
        ]
        self.assertEqual(revision[0]["http_method"], "GET")
        self.assertEqual(revision[0]["parameter_form"], "null")

    def test_callback_fanout_covers_every_api_and_periodic_subscribers(self):
        contract = {row["endpoint"] for row in rows("api_contract.tsv")}
        fanout = rows("api_callback_fanout.tsv")
        self.assertEqual({row["endpoint"] for row in fanout}, contract)
        periodic = [
            row
            for row in fanout
            if row["endpoint"] == "common/periodicInquiry" and row["callback_hub"]
        ]
        self.assertEqual(len(periodic), 1)
        self.assertEqual(periodic[0]["callback_hub"], "PeriodicRounder")
        self.assertEqual(periodic[0]["subscriber_count"], "4")

        subscribers = rows("callback_subscribers.tsv")
        names = {row["subscriber"] for row in subscribers}
        self.assertEqual(
            names,
            {
                "ChatInfo::setOperationMessage",
                "SessionKeeper::updatePeriodic",
                "ShowOffManager::ShowOffDataHandler",
                "UserStatus/SocialInformation::update",
            },
        )
        chat = next(
            row
            for row in subscribers
            if row["subscriber"] == "ChatInfo::setOperationMessage"
        )
        self.assertEqual(chat["unguarded_reads"], "gmMessage")
        self.assertEqual(chat["key_types"], "gmMessage:string")

    def test_key_types_preserve_scalar_tokens(self):
        key_rows = rows("key_types.tsv")
        indexed = {
            (row["key"], row["token"]): row["type_full_name"] for row in key_rows
        }
        self.assertEqual(
            indexed[("now", "0x01000046")],
            "System.Double",
        )
        self.assertEqual(
            indexed[("gmMessage", "0x0100000C")],
            "System.String",
        )
        self.assertEqual(
            indexed[("PoliticPoint", "0x0100000B")],
            "System.Int32",
        )
        self.assertEqual(
            indexed[("politicPoint", "0x01000046")],
            "System.Double",
        )
        self.assertIn(
            "System.Collections.Hashtable",
            {row["type_full_name"] for row in key_rows},
        )
        self.assertEqual(
            indexed[("", "0x01000051")],
            "System.Collections.DictionaryEntry",
        )
        for row in key_rows:
            offset = int(row["file_offset"], 16)
            self.assertGreaterEqual(offset, ASSEMBLY_ENTRY_OFFSET)
            self.assertLess(offset, CONTAINER_SIZE)

    def test_unguarded_reads_include_known_client_crashes(self):
        read_rows = rows("il_unguarded_reads.tsv")
        chat = [
            row
            for row in read_rows
            if row["owner"] == "ChatInfo"
            and row["method"] == "setOperationMessage"
            and row["key"] == "gmMessage"
        ]
        self.assertEqual(len(chat), 1)
        self.assertEqual(chat[0]["type"], "string")
        for key in ("politicPoint", "nextTriggerPoliticPoint"):
            typed = [
                row
                for row in read_rows
                if row["key"] == key and row["type"] == "double"
            ]
            self.assertTrue(typed, key)

    def test_response_shapes_cover_every_endpoint(self):
        contract = {row["endpoint"] for row in rows("api_contract.tsv")}
        shape_rows = rows("response_shapes.tsv")
        self.assertEqual({row["endpoint"] for row in shape_rows}, contract)
        self.assertEqual(sum(row["shape"] == "bare_map" for row in shape_rows), 22)
        self.assertEqual(sum(row["shape"] == "envelope" for row in shape_rows), 380)
        periodic = next(
            row for row in shape_rows if row["endpoint"] == "common/periodicInquiry"
        )
        self.assertEqual(periodic["shape"], "envelope")
        mapped = next(
            row for row in shape_rows if row["endpoint"] == "politic/map/setMapName2"
        )
        self.assertEqual(mapped["shape"], "bare_map")
        self.assertIn("@0x", mapped["evidence"])


if __name__ == "__main__":
    unittest.main()
