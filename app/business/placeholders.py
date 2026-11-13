"""占位响应：按契约里的类型给出「形状正确、语义为空」的响应体。

目的只有一个：客户端拿到 200 + 结构合法的 JSON，而不是 404，从而能继续走流程去
请求下一批接口；等某个端点被真正实现时，用业务 handler 覆盖同名注册项即可。

只填**源码里取到类型**的键（549 个 / 1035 键中的一部分；点号表示嵌套路径，客户端按 `hash["a"]["b"]` 分两层读的情形也靠它还原）；没有类型的键不猜，避免给错类型
让客户端 `(int)hash["x"]` 直接抛异常。根响应形态由 response_shapes 决定：普通接口
使用 envelope，已验证会遍历根表的接口返回裸映射。
"""
from __future__ import annotations

from typing import Any, Callable

from app.business import contract
from app.business import response_shapes

RESERVED = {"succeeded", "now"}

_DEFAULT: dict[str, Any] = {
    "int": 0,
    "long": 0,
    "double": 0.0,
    "bool": False,
    "string": "",
}


def _default_for(typ: str) -> Any:
    """每个键单独造默认值：Hashtable 不能共用同一个 dict 对象，否则嵌套写会串。"""
    if typ == "Hashtable":
        return {}
    return _DEFAULT.get(typ, {})


def _assign(body: dict[str, Any], dotted: str, value: Any) -> None:
    """把 `a.b.c` 写进嵌套字典；中间层若已存在标量则替换成字典。"""
    parts = dotted.split(".")
    box = body
    for part in parts[:-1]:
        child = box.get(part)
        if not isinstance(child, dict):
            child = {}
            box[part] = child
        box = child
    box[parts[-1]] = value


def payload(api: str) -> dict[str, Any]:
    if response_shapes.shape_for(api) is response_shapes.ResponseShape.BARE_MAP:
        # 这些契约键实际是“每条记录内部”的字段，不能平铺成根表上的标量。
        return {}
    body: dict[str, Any] = {}
    for field in contract.response(api):
        key, typ = field["key"], field["type"]
        if not typ or key in RESERVED:
            continue
        if "<" in key or ">" in key:  # 动态键（<id>.field 之类），无法静态展开
            continue
        # 带点号的键表示嵌套路径（`schedule.open` 之类），契约表用点号还原层级。
        _assign(body, key, _default_for(typ))
    return body


def make_handler(api: str) -> Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]:
    def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
        return response_shapes.success(api, payload(api))

    handler.__name__ = f"placeholder_{api.replace('/', '_')}"
    return handler
