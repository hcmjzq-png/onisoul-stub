"""接口注册表：api 路径 → 业务 handler。

Handler 签名：handler(params: dict, session: dict | None) -> dict（响应体）。

两类登记方式：
    register(api, handler)            真实业务实现，优先级最高
    register_contract_defaults()      按契约表把 402 个端点全部登记为占位响应，
                                      保证客户端请求任何已知接口都拿到结构合法的 200
未登记的路径一律 404。
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

    def register_contract_defaults(self) -> "Registry":
        """把契约表里的全部端点登记为占位响应；已注册的真实实现不覆盖。"""
        from app.business import contract, placeholders

        for api in contract.endpoints():
            if api in self._handlers:
                continue
            self.register(api, placeholders.make_handler(api))
        return self

    def known(self) -> set[str]:
        return set(self._handlers)

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
