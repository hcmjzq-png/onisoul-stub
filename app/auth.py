"""鉴权闸门：决定「哪些端点允许在无有效会话时调用」。

放行名单不是拍脑袋定的，全部有客户端调用点作依据（反编译树 WebApiClient.cs）：

    common/getRevisions        WebApiClient.cs:363  `httpCall("common/getRevisions", null, responder)`
                               —— 唯一一个显式传 null 参数（连 token 都没有）的调用，
                               客户端在 TableLoad.cs:45 版本表加载阶段就发，此时还没登录。
    debug/devLogin             WebApiClient.cs:372 / :2118，BootUp.cs:129、SceneResources.cs:125
                               —— 启动期自动登录，登录本身就是拿 token。
    debug/debugLogin           WebApiClient.cs:444，SceneResources.cs:132
    debug/debugLoginCog        WebApiClient.cs:462 —— 账号密码登录，同样在拿 token 之前。
    auth/login                 WebApiClient.cs:405
    auth/gameLogin             WebApiClient.cs:417
    auth/guestLogin            WebApiClient.cs:480
    auth/refreshToken          WebApiClient.cs:383 —— 换票/续期，入参是旧 token。

其余端点（含 `auth/createPlayer`、`auth/registerName`、`auth/keepAliveContainer`）客户端
都在 `Add("token", token_)` 之后才调用，因此必须有会话。

运行模式由环境变量 `AUTH_MODE` 决定：
    strict （默认）无会话 → 直接拒绝，不执行 handler。
    observe        无会话 → 照旧执行 handler，只累计计数并打印告警，用于排查
                   「客户端到底哪些接口在没登录时会打」。
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Any

from app.protocol import envelope

# 无会话即可调用的端点（见模块 docstring 的逐条依据）
PRE_AUTH_APIS = frozenset(
    {
        "common/getRevisions",
        "debug/devLogin",
        "debug/debugLogin",
        "debug/debugLoginCog",
        "auth/login",
        "auth/gameLogin",
        "auth/guestLogin",
        "auth/refreshToken",
    }
)

AUTH_MODE_STRICT = "strict"
AUTH_MODE_OBSERVE = "observe"

_lock = threading.Lock()
_unauthenticated: dict[str, int] = {}
_denied: dict[str, int] = {}


def mode() -> str:
    raw = str(os.environ.get("AUTH_MODE", AUTH_MODE_STRICT)).strip().lower()
    return AUTH_MODE_OBSERVE if raw == AUTH_MODE_OBSERVE else AUTH_MODE_STRICT


def is_pre_auth(api: str) -> bool:
    return api in PRE_AUTH_APIS


def _count(table: dict[str, int], api: str) -> int:
    with _lock:
        table[api] = table.get(api, 0) + 1
        return table[api]


def denial_body(api: str, message: str = "authentication required") -> dict[str, Any]:
    """按端点根形态给拒绝响应：裸映射端点只认 errorReason，其余走 envelope。"""
    from app.business import response_shapes

    if response_shapes.shape_for(api) is response_shapes.ResponseShape.BARE_MAP:
        return {"errorReason": message}
    body = envelope.error(envelope.ERR_UNAUTHORIZED, message)
    return body


def check(api: str, session: dict[str, Any] | None, *, has_token: bool = False) -> dict[str, Any] | None:
    """None 表示放行；返回 dict 表示这次请求应直接拿这个响应体拒绝。

    `has_token=True` 但 session 为 None，说明 token 无效/过期/会话库不可用，
    与「压根没带 token」区分开，便于排查。
    """
    if session is not None:
        return None
    if is_pre_auth(api):
        return None
    if mode() == AUTH_MODE_OBSERVE:
        count = _count(_unauthenticated, api)
        if count == 1:
            print(
                f"[stub][auth] 未认证调用（observe 模式放行）: {api}",
                file=sys.stderr,
            )
        return None
    _count(_denied, api)
    return denial_body(api, "invalid token" if has_token else "authentication required")


def report() -> dict[str, dict[str, int]]:
    """给诊断用的计数快照。"""
    with _lock:
        return {
            "observe_passed": dict(_unauthenticated),
            "strict_denied": dict(_denied),
        }


def reset() -> None:
    with _lock:
        _unauthenticated.clear()
        _denied.clear()
