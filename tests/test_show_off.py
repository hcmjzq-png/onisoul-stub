"""show_off 队列回归：客户端不接受空数组，任何时刻都必须给出一条。

用例自带一个临时 bundle 目录，不依赖部署资产（assets/pc/bundles）是否存在，
保证干净 clone 也能全绿。
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.business import periodic, show_off


class ShowOffQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        show_off.reset()
        self._bundle_dir = tempfile.TemporaryDirectory()
        self._original_bundle_dir = show_off.paths.PC_BUNDLE_DIR
        bundle_root = Path(self._bundle_dir.name)
        (bundle_root / "chara").mkdir()
        digest = hashlib.md5(
            show_off.DEFAULT_CHARACTER_ID.encode("utf-16-le")
        ).hexdigest()
        (bundle_root / "chara" / f"{digest}.unity3d").write_bytes(b"")
        show_off.paths.PC_BUNDLE_DIR = bundle_root

    def tearDown(self) -> None:
        show_off.paths.PC_BUNDLE_DIR = self._original_bundle_dir
        self._bundle_dir.cleanup()
        show_off.reset()

    def test_default_entry_is_valid_and_has_both_key_spellings(self) -> None:
        entry = show_off.default_entry()
        for key in ("UserName", "userName", "CharacterId", "characterId", "SkillId", "skillId"):
            self.assertIn(key, entry)
            self.assertTrue(entry[key])

    def test_next_entry_never_empty(self) -> None:
        self.assertEqual(show_off.next_entry()["characterId"], show_off.DEFAULT_CHARACTER_ID)

    def test_push_then_deliver_fifo(self) -> None:
        show_off.push("stream", "chara1_00726_01", "skill1_01002_01")
        show_off.push("stream2", "chara1_00726_01", "skill1_01002_01")
        self.assertEqual(show_off.pending_count(), 2)
        self.assertEqual(show_off.next_entry()["userName"], "stream")
        self.assertEqual(show_off.next_entry()["userName"], "stream2")

    def test_after_queue_drained_repeats_last_entry(self) -> None:
        show_off.push("stream", "chara1_00726_01", "skill1_01002_01")
        first = show_off.next_entry()
        second = show_off.next_entry()
        self.assertEqual(first, second)

    def test_push_rejects_missing_bundle(self) -> None:
        with self.assertRaises(ValueError):
            show_off.push("stream", "chara1_99999_01", "skill1_01002_01")

    def test_push_rejects_empty_field(self) -> None:
        with self.assertRaises(ValueError):
            show_off.push("", "chara1_00726_01", "skill1_01002_01")

    def test_handler_always_returns_one_entry(self) -> None:
        body = periodic.handler({}, None)
        self.assertTrue(body.get("succeeded"))
        self.assertIsInstance(body["show_off"], list)
        self.assertEqual(len(body["show_off"]), 1)
        self.assertIn("characterId", body["show_off"][0])

    def test_registry_dispatch_non_empty(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["show_off"]), 1)


if __name__ == "__main__":
    unittest.main()
