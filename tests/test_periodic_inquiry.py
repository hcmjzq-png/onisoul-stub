"""common/periodicInquiry 必须带回 show_off，且形状是 map。

客户端 PeriodicChecking：
    字段缺失 → "There's no "show_off" field in return payload"
    值是数组或空 map（isinst Hashtable 失败）→ "There's no data in "show_off" field"
两者都会抛异常，被 WebApiClient 捕获后弹「联机中断(1)」。形状与键名由客户端 IL 反汇编
确定，见 docs/repro-launcher-login.md 第十二节。
"""
from __future__ import annotations

import unittest

from app.business import periodic


class PeriodicInquiryTest(unittest.TestCase):
    def test_handler_returns_show_off_map(self) -> None:
        body = periodic.handler({}, None)
        self.assertTrue(body.get("succeeded"))
        self.assertIn("show_off", body)
        field = body["show_off"]
        self.assertIsInstance(field, dict)
        self.assertNotIsInstance(field, list)
        self.assertTrue(field)  # 空 map 同样会被客户端当异常
        entry = field["0"]
        self.assertEqual(set(entry), {"username", "character_id", "skill_id"})

    def test_registry_dispatch_keeps_show_off(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("show_off", body)


if __name__ == "__main__":
    unittest.main()
