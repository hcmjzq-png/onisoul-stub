"""请求信封与统一响应。

骨架占位：请求 / 响应字段形状待从客户端 bundle 核对，未核对前一律视为待验证线索：
    - 请求：POST /api/<api>，表单字段 `params` 为 JSON 字符串；部分请求直接是 JSON body。
    - 响应：JSON 对象，顶层键线索 `succeeded`、`now`（epoch 秒）、`token`、`playerId`。
    - 响应编码可能为 JSON 或 msgpack/igbinary；本骨架先只实现 JSON，二进制编码留 TODO。
"""
from __future__ import annotations

import json
import time
from typing import Any, Mapping
from urllib.parse import parse_qs


# 错误码（占位；真实错误码需对照客户端 StatusCode / 返回枚举补齐）
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_UNAUTHORIZED = "UNAUTHORIZED"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_INTERNAL = "INTERNAL"


def _now() -> float:
    return float(int(time.time()))


def parse_params(body: bytes, content_type: str = "") -> dict[str, Any]:
    """从请求体解析出参数字典。

    兼容两种形态：
      1. 表单编码，字段 `params` 为 JSON 字符串（旧 Stub 协议）。
      2. 直接 JSON body。

    解析失败返回空 dict，由业务层按需报参数错误；不在这里抛异常打断 HTTP 流程。
    """
    if not body:
        return {}

    text = body.decode("utf-8", "replace").strip()
    if not text:
        return {}

    ctype = (content_type or "").lower()
    if "application/json" in ctype or text.startswith(("{", "[")):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {"value": data}
        except ValueError:
            return {}

    # 表单编码：a=1&b=2，其中 params 是 JSON 字符串。parse_qs 负责 URL 解码。
    parsed = parse_qs(text, keep_blank_values=True)
    form: dict[str, str] = {k: v[0] for k, v in parsed.items()}
    raw = form.get("params", "")
    if raw:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"value": data}
        except ValueError:
            return {}
    return form


def ok(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """成功响应：统一注入 now，业务字段并入顶层。"""
    body: dict[str, Any] = {"succeeded": True, "now": _now()}
    if payload:
        body.update(dict(payload))
    return body


def error(code: str, message: str = "", payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """失败响应。"""
    body: dict[str, Any] = {
        "succeeded": False,
        "now": _now(),
        "error": code,
        "message": message,
    }
    if payload:
        body.update(dict(payload))
    return body
