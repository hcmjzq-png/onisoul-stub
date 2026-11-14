"""common/periodicInquiry：把「幸运用户展示（show off）」交给客户端。

回包根表的 ``show_off`` 必须是 map（键序号 → 条目），条目键 username / character_id /
skill_id；字段缺失、值是数组、map 为空三种情况客户端都会有自己的处理分支，异常被
WebApiClient 捕获后弹「联机中断(1)」。

除 ``show_off`` 外，客户端的 periodicInquiry 回调还会从回包根表读两个标量并直接
拆箱（IL：``ldstr "politicPoint"`` / ``get_Item`` / ``unbox.any Double``，随后
``ldstr "nextTriggerPoliticPoint"`` 同样拆箱，再调 ``wakeupEdictMissions``）。
少这两个键时 ``get_Item`` 返回 null，``unbox.any`` 抛 InvalidCastException，WebApiClient
的 catch 分支打印 ``exception error : <回包原文>``，随后 errorNotifier 弹窗、
GameRestarter 停服务——这就是「进主城后联机中断(1)」的真正原因。证据见
docs/repro-launcher-login.md 第十三节。
"""
from __future__ import annotations

from typing import Any

from app import state
from app.business import response_shapes, show_off

API = "common/periodicInquiry"

# 客户端要求这两个值是 double（IL 里 unbox.any System.Double），必须是 JSON 小数。
DEFAULT_NEXT_TRIGGER = 10.0


def _points(session: dict[str, Any] | None) -> dict[str, float]:
    """取玩家的政治点状态；缺档时退回 0 / 阈值默认值，绝不下发 null。"""
    player_id = str((session or {}).get("playerId") or state.DEFAULT_PLAYER_ID)
    player: dict[str, Any] = {}
    try:
        player = state.load(player_id) or {}
    except Exception:
        player = {}
    box = ((player.get("actionPoints") or {}).get("politicPoint") or {})
    point = float(box.get("point") or 0)
    next_trigger = float(box.get("maxPoint") or 0) or DEFAULT_NEXT_TRIGGER
    return {"politicPoint": point, "nextTriggerPoliticPoint": next_trigger}


def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"show_off": show_off.next_payload()}
    payload.update(_points(session))
    return response_shapes.success(API, payload)


def register(registry: Any) -> None:
    registry.register(API, handler)
