"""common/periodicInquiry：把「幸运用户展示（show off）」交给客户端。

回包根表的 ``show_off`` 必须是 map（键序号 → 条目），条目键 username / character_id /
skill_id；字段缺失、值是数组、map 为空三种情况客户端都会抛异常，异常被 WebApiClient
捕获后弹「联机中断(1)」。形状与键名由客户端 IL 反汇编确定，详见
``app/business/show_off.py`` 与 docs/repro-launcher-login.md 第十二节。
"""
from __future__ import annotations

from typing import Any

from app.business import response_shapes, show_off

API = "common/periodicInquiry"


def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    return response_shapes.success(API, {"show_off": show_off.next_payload()})


def register(registry: Any) -> None:
    registry.register(API, handler)
