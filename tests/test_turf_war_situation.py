"""turfWar 战况占位的回归测试（任务 #7 第二批）。

依据全部来自客户端反编译源码，行号写进断言旁边的注释。
"""
from __future__ import annotations

import unittest

from app.business import contract, turf_war
from app.main import build_registry


class TurfWarContractTest(unittest.TestCase):
    def test_contract_declares_the_nested_reads(self) -> None:
        fields = {(f["key"], f["type"]) for f in contract.response("turfWar/getWarSituation")}
        expected = [
            ("selfBelong", "Hashtable"),
            ("selfBelong.team", "string"),
            ("selfBelong.battlefield", "string"),
            ("isMovable", "bool"),
            ("bonus", "Hashtable"),
            ("bonus.team", "string"),
            ("bonus.endTime", "double"),
            ("bonus.battlefield", "string"),
            ("situation", "Hashtable"),
            ("situation.global", "Hashtable"),
            ("situation.global.advantage", "string"),
            ("situation.battlefields", "Hashtable"),
            ("battleRules", "Hashtable"),
        ]
        for key, typ in expected:
            self.assertIn((key, typ), fields, "%s:%s 未进契约" % (key, typ))


class TurfWarHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_registry()

    def test_self_belong_is_sentinel_not_empty(self) -> None:
        # TurfWarBriefCache.cs:362-370：result["selfBelong"]["team"] 无守卫
        status, body = self.registry.dispatch("turfWar/getWarSituation", {}, None)
        self.assertEqual(status, 200)
        selfIsNone = body["selfBelong"]
        self.assertEqual(selfIsNone["team"], "none")
        self.assertEqual(selfIsNone["battlefield"], "none")
        self.assertEqual(body["team"], "none")
        self.assertEqual(body["battlefield"], "none")

    def test_bonus_and_flags_are_typed(self) -> None:
        _, body = self.registry.dispatch("turfWar/getWarSituation", {}, None)
        # :325-338 getBonusRestTime 先比较 "none"，再 (long)(double)endTime
        self.assertEqual(body["bonus"]["team"], "none")
        self.assertEqual(body["bonus"]["battlefield"], "none")
        self.assertEqual(body["bonus"]["endTime"], 0.0)
        self.assertIsInstance(body["bonus"]["endTime"], float)
        # :235 (bool)warSituation["isMovable"]
        self.assertIs(body["isMovable"], False)

    def test_situation_chain_is_readable(self) -> None:
        _, body = self.registry.dispatch("turfWar/getWarSituation", {}, None)
        # :203-205 situation -> global -> advantage
        self.assertEqual(body["situation"]["global"]["advantage"], "even")
        # :94-104 situation -> battlefields；:310-312 battlefields[field]["advantage"]
        self.assertIsInstance(body["situation"]["battlefields"], dict)
        self.assertIsInstance(body["battleRules"], dict)
        entry = body["situation"]["battlefields"]["none"]
        for key in ("east", "west", "eastPoint", "westPoint"):
            self.assertEqual(entry[key], 0.0)
        self.assertEqual(entry["advantage"], "even")

    def test_body_is_rebuilt_each_call(self) -> None:
        first = turf_war.body()
        first["selfBelong"]["team"] = "mutated"
        second = turf_war.body()
        self.assertEqual(second["selfBelong"]["team"], "none")

    def test_handler_wins_over_placeholder(self) -> None:
        # build_registry 先登记真实实现，再 register_contract_defaults()，
        # 占位不得覆盖已登记的 handler。
        _, body = self.registry.dispatch("turfWar/getWarSituation", {}, None)
        self.assertEqual(body["selfBelong"]["team"], "none")
        self.assertFalse(hasattr(self.registry, "_handlers") and
                         self.registry._handlers["turfWar/getWarSituation"].__name__.startswith("placeholder_"))


if __name__ == "__main__":
    unittest.main()
