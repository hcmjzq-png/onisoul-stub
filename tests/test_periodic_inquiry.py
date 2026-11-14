"""common/periodicInquiry 的 show_off 形状。

客户端 PeriodicChecking：
    字段缺失 → "There's no "show_off" field in return payload"
    值是数组（isinst Hashtable 得 null）→ "There's no data in "show_off" field"
    空 map {} → 合法，只是这一轮没有广播条

两者报错都会抛异常，被 WebApiClient 捕获后弹「联机中断(1)」。形状与键名由客户端 IL
反汇编确定，见 docs/repro-launcher-login.md 第十二节。
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.business import periodic, show_off


class PeriodicInquiryTest(unittest.TestCase):
    def setUp(self) -> None:
        show_off.reset()
        self._bundle_dir = tempfile.TemporaryDirectory()
        self._original_bundle_dir = show_off.paths.PC_BUNDLE_DIR
        bundle_root = Path(self._bundle_dir.name)
        (bundle_root / "chara").mkdir()
        digest = hashlib.md5(
            "chara1_00726_01".encode("utf-16-le")
        ).hexdigest()
        (bundle_root / "chara" / f"{digest}.unity3d").write_bytes(b"")
        show_off.paths.PC_BUNDLE_DIR = bundle_root

    def tearDown(self) -> None:
        show_off.paths.PC_BUNDLE_DIR = self._original_bundle_dir
        self._bundle_dir.cleanup()
        show_off.reset()

    def test_handler_show_off_is_map(self) -> None:
        body = periodic.handler({}, None)
        self.assertTrue(body.get("succeeded"))
        self.assertIn("show_off", body)
        field = body["show_off"]
        self.assertIsInstance(field, dict)
        self.assertNotIsInstance(field, list)

    def test_handler_entry_keys(self) -> None:
        show_off.push("stream", "chara1_00726_01", "skill1_01002_01")
        body = periodic.handler({}, None)
        entry = body["show_off"]["0"]
        self.assertEqual(set(entry), {"username", "character_id", "skill_id"})

    def test_registry_dispatch_keeps_show_off(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("show_off", body)

    def test_handler_includes_gm_message(self) -> None:
        # ChatInfo.setOperationMessage 读 gmMessage 时没有 ContainsKey 守卫，
        # 缺键会在 Replace 上抛 NullReferenceException（联机中断(1) 的真因）。
        body = periodic.handler({}, None)
        self.assertIn("gmMessage", body)
        self.assertIsInstance(body["gmMessage"], str)

    def test_registry_dispatch_keeps_gm_message(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("gmMessage", body)


if __name__ == "__main__":
    unittest.main()
