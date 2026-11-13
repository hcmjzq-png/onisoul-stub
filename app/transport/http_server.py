"""HTTP 接入层：路由分发 + 会话解析。

路由：
    GET  /client/status      健康检查（不经过业务注册表）
    POST /api/<api>          业务接口：解析 params → 校验 token → registry.dispatch
    GET  其余 PC 路径        WebPlayer / app.unity3d / AssetBundle / crossdomain

只绑定 127.0.0.1；对外由 tools/proxy80.py 在 80 端口转发，本层不直接暴露公网。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import sessions
from app.business.registry import Registry
from app.protocol import envelope
from app.transport.static import StaticFiles, StaticPathError, StaticResource


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(payload)


def _static_response(handler: BaseHTTPRequestHandler, resource: StaticResource) -> None:
    size = resource.size
    handler.send_response(200)
    handler.send_header("Content-Type", resource.content_type)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Cache-Control", resource.cache_control)
    if resource.cache_control.startswith("no-store"):
        handler.send_header("Pragma", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        if resource.body is not None:
            handler.wfile.write(resource.body)
            return
        with open(resource.path, "rb") as source:
            while chunk := source.read(64 * 1024):
                handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError):
        return


def make_handler(
    registry: Registry, static_files: StaticFiles | None = None
) -> type[BaseHTTPRequestHandler]:
    static = static_files or StaticFiles()

    class StubHandler(BaseHTTPRequestHandler):
        server_version = "OniSoulStub/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # 静默默认访问日志
            return

        def do_GET(self) -> None:
            if self.path.split("?")[0] == "/client/status":
                _json_response(self, 200, envelope.ok({"service": "onisoul-stub", "status": "up"}))
                return
            try:
                resource = static.resolve(self.path)
            except StaticPathError as exc:
                _json_response(
                    self,
                    400,
                    envelope.error(envelope.ERR_BAD_REQUEST, str(exc)),
                )
                return
            if resource is not None:
                _static_response(self, resource)
                return
            _json_response(
                self,
                404,
                envelope.error(envelope.ERR_NOT_FOUND, "stub has no assets"),
            )

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if not path.startswith("/api/"):
                _json_response(self, 404, envelope.error(envelope.ERR_NOT_FOUND))
                return

            api = path[len("/api/"):].strip("/")
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            ctype = self.headers.get("Content-Type", "")
            params = envelope.parse_params(raw, ctype)

            token = str(params.get("token") or "").strip()
            try:
                session = sessions.resolve(token) if token else None
            except Exception:
                # 会话库不可用时按匿名继续：占位阶段响应不依赖会话，
                # 至少保证「不因 DB 掉了就没响应」，否则客户端只能看到连接被掐断。
                session = None

            status, body = registry.dispatch(api, params, session)
            _json_response(self, status, body)

    return StubHandler


def serve(
    host: str,
    port: int,
    registry: Registry,
    static_files: StaticFiles | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(registry, static_files))
    httpd.daemon_threads = True
    return httpd
