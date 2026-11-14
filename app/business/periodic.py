"""common/periodicInquiry：把「幸运用户展示（show off）」交给客户端。

客户端读回包根表的 ``show_off`` 数组；字段缺失抛 "There's no "show_off" field in return
payload"，数组为空抛 "There's no data in "show_off" field"，异常被 WebApiClient 捕获后
弹「联机中断(1)」。所以这里不能回空列表，取值逻辑见 ``app/business/show_off.py``。

客户端侧对应实现是 ``ShowOffDataParser.ParseSingleData`` 与 ``ShowOffDataHandler``
（条目成员 UserName / CharacterId / SkillId，入队后由 ShowOffMsg 浮层播放）。
"""
from __future__ import annotations

from typing import Any

from app.business import response_shapes, show_off

API = "common/periodicInquiry"


def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    return response_shapes.success(API, {"show_off": [show_off.next_entry()]})


def register(registry: Any) -> None:
    registry.register(API, handler)
