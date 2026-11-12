"""接口注册表：api 路径 → 业务 handler。

Handler 签名：handler(params: dict, session: dict | None) -> dict（响应体）。
骨架阶段不登记具体游戏接口；待客户端 dump / 抓包核对字段后，在此逐个注册。

已知接口线索（来自早期反汇编，路径与参数待复核，见 docs/api_spec.md）：
    auth/gameLogin、debug/devLogin、auth/createPlayer、auth/registerName、
    common/getPlayerParams、common/getActionPoints、politic/map/getMapData …
"""
from __future__ import annotations

from typing import Any, Callable

from app.protocol import envelope

Handler = Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]


class Registry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, api: str, handler: Handler) -> None:
        self._handlers[api] = handler

    def dispatch(
        self, api: str, params: dict[str, Any], session: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        handler = self._handlers.get(api)
        if handler is None:
            return 404, envelope.error(envelope.ERR_NOT_FOUND, f"未知接口: {api}")
        try:
            body = handler(params, session)
            return 200, body
        except NotImplementedError as exc:
            return 501, envelope.error(envelope.ERR_INTERNAL, str(exc) or "未实现")
        except Exception as exc:  # 业务异常不带崩 HTTP 服务
            return 500, envelope.error(envelope.ERR_INTERNAL, type(exc).__name__)
