"""common/periodicInquiry 必须带回 show_off 字段（缺字段 → 客户端「联机中断(1)」）。

回归点：占位响应只按契约表填键，而 common/periodicInquiry 在契约表里没有键，
于是回包只剩 {succeeded, now}，客户端抛 "There's no \"show_off\" field in return payload"。
"""
from __future__ import annotations

import unittest

from app.business import periodic


class PeriodicInquiryTest(unittest.TestCase):
    def test_handler_returns_show_off_list(self) -> None:
        body = periodic.handler({}, None)
        self.assertTrue(body.get("succeeded"))
        self.assertIn("show_off", body)
        self.assertIsInstance(body["show_off"], list)

    def test_registry_dispatch_keeps_show_off(self) -> None:
        from app.main import build_registry

        status, body = build_registry().dispatch("common/periodicInquiry", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("show_off", body)


if __name__ == "__main__":
    unittest.main()
