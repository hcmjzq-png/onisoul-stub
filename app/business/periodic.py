"""common/periodicInquiry：周期性推送（幸运用户展示 + 服务器公告）。

客户端把 periodicInquiry 的回包交给 ``PeriodicRounder.callCallbacks``，由注册在
``PeriodicRounder`` 上的四个回调逐个处理：

1. ``SessionKeeper.updatePeriodic`` —— 读 ``token`` / ``now``，两者都有 ``ContainsKey`` 守卫；
2. ``ChatInfo.setOperationMessage`` —— 读 ``gmMessage``，**没有守卫**：
   ``ldarg.1 ldstr "gmMessage" get_Item castclass string`` 之后直接
   ``ldstr "\r" ... callvirt Replace``；键不存在时 ``get_Item`` 返回 null，
   ``Replace`` 抛 NullReferenceException；
3. ``ShowOffManager.ShowOffDataHandler`` —— ``show_off`` 有守卫，非 Hashtable 或缺失只是 warning；
4. ``SocialInformation.update`` —— ``inboxParcel`` / ``friendOffer`` / ``unreadMail`` 全部有守卫。

因此最小合法回包是 ``{"succeeded":true,"now":<double>,"show_off":{},"gmMessage":""}``：
``gmMessage`` 为空串时 ``setOperationMessage`` 在 ``s == ""`` 处直接 return，
``show_off`` 为空 map 时循环零次。任何一项缺失都会让 WebApiClient 的 catch 打印
``exception error : <回包原文>``，errorNotifier 弹「联机中断(1)」，GameRestarter 停服务。

证据（IL 反汇编，Assembly-CSharp.dll 容器偏移 1,474,648，RVA→文件偏移 =
rva + 1,466,?；见 docs/repro-launcher-login.md 第十三节）：
- ``PeriodicRounder.regist`` 的四个调用点：``SessionKeeper.updateToken`` /
  ``ChatInfo.Start`` / ``ShowOffManager.Init`` / ``SocialInformation..ctor``；
- ``ChatInfo.setOperationMessage`` 位于文件偏移 1,915,936，无 ``ContainsKey("gmMessage")``。
"""
from __future__ import annotations

from functools import partial
from typing import Any, Callable

from app import state

from app.business import response_shapes, show_off

API = "common/periodicInquiry"


def handler(params: dict[str, Any], session: dict[str, Any] | None, *,
            notification_provider: Callable | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "show_off": show_off.next_payload(),
        # ChatInfo.setOperationMessage 无守卫，缺这个键 → NullReferenceException
        "gmMessage": "",
    }
    if notification_provider is not None:
        try:
            payload.update(notification_provider(session))
        except (ValueError, state.StateConflictError) as exc:
            payload.update(succeeded=False, errorReason=str(exc))
    return response_shapes.success(API, payload)


def register(registry: Any, *, notification_provider: Callable | None = None) -> None:
    registry.register(API, partial(handler, notification_provider=notification_provider))
