"""show_off 回归：形状必须是 map、键是 snake_case，且不依赖部署资产。

用例自带一个临时 bundle 目录，不依赖 assets/pc/bundles 是否存在，干净 clone 也能全绿。
形状来自客户端 IL（ShowOffDataParser.ParseSingleData 的 switch 表 +
PeriodicChecking 的 isinst Hashtable），见 docs/repro-launcher-login.md 第十二节。
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

    def test_default_entry_uses_snake_case_keys(self) -> None:
        entry = show_off.default_entry()
        self.assertEqual(set(entry), {"username", "character_id", "skill_id"})
        for value in entry.values():
            self.assertTrue(value)

    def test_payload_is_map_not_list(self) -> None:
        payload = show_off.next_payload()
        self.assertIsInstance(payload, dict)
        self.assertEqual(len(payload), 1)
        self.assertIsInstance(payload["0"], dict)

    def test_next_entry_never_empty(self) -> None:
        self.assertEqual(show_off.next_entry()["character_id"], show_off.DEFAULT_CHARACTER_ID)

    def test_push_then_deliver_fifo(self) -> None:
        show_off.push("stream", "chara1_00726_01", "skill1_01002_01")
        show_off.push("stream2", "chara1_00726_01", "skill1_01002_01")
        self.assertEqual(show_off.pending_count(), 2)
        self.assertEqual(show_off.next_entry()["username"], "stream")
        self.assertEqual(show_off.next_entry()["username"], "stream2")

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

    def test_handler_returns_map_with_one_entry(self) -> None:
        body = periodic.handler({}, None)
        self.assertTrue(body.get("succeeded"))
        field = body["show_off"]
        self.assertIsInstance(field, dict)
        self.assertNotIsInstance(field, list)
        self.assertEqual(len(field), 1)
        entry = field["0"]
        self.assertEqual(set(entry), {"username", "character_id", "skill_id"})

    def test_registry_dispatch_shape(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertIsInstance(body["show_off"], dict)
        self.assertIn("0", body["show_off"])


if __name__ == "__main__":
    unittest.main()
