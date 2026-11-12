"""HTTP 接入层：路由分发 + 会话解析。

路由：
    GET  /client/status      健康检查（不经过业务注册表）
    POST /api/<api>          业务接口：解析 params → 校验 token → registry.dispatch
    其余路径                 静态资源（TODO：接入 assets 目录映射）

只绑定 127.0.0.1；对外由 tools/proxy80.py 在 80 端口转发，本层不直接暴露公网。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import sessions
from app.business.registry import Registry
from app.protocol import envelope


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(payload)


def make_handler(registry: Registry) -> type[BaseHTTPRequestHandler]:
    class StubHandler(BaseHTTPRequestHandler):
        server_version = "OniSoulStub/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # 静默默认访问日志
            return

        def do_GET(self) -> None:
            if self.path.split("?")[0] == "/client/status":
                _json_response(self, 200, envelope.ok({"service": "onisoul-stub", "status": "up"}))
                return
            _json_response(self, 404, envelope.error(envelope.ERR_NOT_FOUND, "静态资源映射尚未实现"))

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
            session = sessions.resolve(token) if token else None

            status, body = registry.dispatch(api, params, session)
            _json_response(self, status, body)

    return StubHandler


def serve(host: str, port: int, registry: Registry) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(registry))
    httpd.daemon_threads = True
    return httpd
