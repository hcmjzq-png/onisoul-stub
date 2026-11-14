"""common/periodicInquiry：把「幸运用户展示（show off）」交给客户端。

客户端校验回包时读根表的 ``show_off`` 字段；字段不存在会抛异常，异常被 WebApiClient
捕获后弹「联机中断(1)」。证据：客户端 Unity WebPlayer 日志 log_debug.txt 同一轮内

    There's no "show_off" field in return payload
    ERROR: WebAPI api = common/periodicInquiry error = exception error : {"succeeded": true, "now": ...}

客户端侧对应实现是 ``ShowOffDataParser.ParseSingleData`` 与 ``ShowOffDataHandler``
（条目成员 UserName / CharacterId / SkillId，入队后由 ShowOffMsg 浮层播放）。本 Stub 没有
真实掉落数据，因此 ``show_off`` 固定回空列表：字段存在、没有记录，客户端跳过展示而不是
抛异常。接入真实活动数据时替换 ``_show_off_entries()`` 即可。
"""
from __future__ import annotations

from typing import Any

from app.business import response_shapes

API = "common/periodicInquiry"


def _show_off_entries() -> list[dict[str, Any]]:
    """幸运用户条目；Stub 阶段为空列表（不用 None，避免客户端判空时类型不符）。"""
    return []


def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    return response_shapes.success(API, {"show_off": _show_off_entries()})


def register(registry: Any) -> None:
    registry.register(API, handler)
