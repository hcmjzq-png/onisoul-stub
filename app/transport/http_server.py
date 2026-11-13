"""HTTP 接入层：路由分发 + 会话解析。

路由：
    GET  /client/status      健康检查（不经过业务注册表）
    POST /api/<api>          业务接口：解析 params → 校验 token → registry.dispatch
    GET  其余 PC 路径        WebPlayer / app.unity3d / AssetBundle / crossdomain

只绑定 127.0.0.1；对外由 tools/proxy80.py 在 80 端口转发，本层不直接暴露公网。
"""
from __future__ import annotations

import json
import os
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import sessions
from app.business.registry import Registry
from app.protocol import envelope
from app.transport.static import StaticFiles, StaticPathError, StaticResource


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: dict[str, Any],
    *,
    head_only: bool = False,
) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    if not head_only:
        handler.wfile.write(payload)


def _not_modified(value: str, last_modified: float | None) -> bool:
    if not value or last_modified is None:
        return False
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(last_modified) <= int(parsed.timestamp())


def _byte_range(value: str, length: int) -> tuple[int, int] | None:
    if not value:
        return None
    if not value.lower().startswith("bytes=") or "," in value:
        raise ValueError("unsupported range")
    spec = value[6:].strip()
    start_text, separator, end_text = spec.partition("-")
    if not separator:
        raise ValueError("invalid range")
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError("invalid suffix range")
            start = max(0, length - suffix)
            end = length - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else length - 1
    except ValueError as exc:
        raise ValueError("invalid range") from exc
    if start < 0 or start >= length or end < start:
        raise ValueError("range not satisfiable")
    return start, min(end, length - 1)


def _static_response(
    handler: BaseHTTPRequestHandler,
    resource: StaticResource,
    *,
    head_only: bool = False,
) -> bool:
    source = None
    length = resource.length
    last_modified = resource.last_modified
    if resource.path is not None:
        try:
            source = open(resource.path, "rb")
            stat = os.fstat(source.fileno())
        except OSError:
            if source is not None:
                source.close()
            return False
        length = stat.st_size
        last_modified = stat.st_mtime

    try:
        if _not_modified(handler.headers.get("If-Modified-Since", ""), last_modified):
            handler.send_response(304)
            handler.send_header("Cache-Control", resource.cache_control)
            if last_modified is not None:
                handler.send_header("Last-Modified", formatdate(last_modified, usegmt=True))
            handler.send_header("Connection", "close")
            handler.end_headers()
            return True

        start, end = 0, length - 1
        status = 200
        try:
            requested = _byte_range(handler.headers.get("Range", ""), length)
        except ValueError:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{length}")
            handler.send_header("Connection", "close")
            handler.end_headers()
            return True
        if requested is not None:
            start, end = requested
            status = 206

        response_length = end - start + 1 if length else 0
        handler.send_response(status)
        handler.send_header("Content-Type", resource.content_type)
        handler.send_header("Content-Length", str(response_length))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", resource.cache_control)
        if last_modified is not None:
            handler.send_header("Last-Modified", formatdate(last_modified, usegmt=True))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{length}")
        if resource.cache_control.startswith("no-store"):
            handler.send_header("Pragma", "no-cache")
        handler.send_header("Connection", "close")
        handler.end_headers()
        if head_only or response_length == 0:
            return True

        if source is not None:
            source.seek(start)
            remaining = response_length
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
        else:
            handler.wfile.write((resource.body or b"")[start : start + response_length])
    except (BrokenPipeError, ConnectionResetError):
        return True
    finally:
        if source is not None:
            source.close()
    return True


def _static_not_found(handler: BaseHTTPRequestHandler, *, head_only: bool) -> None:
    _json_response(
        handler,
        404,
        envelope.error(envelope.ERR_NOT_FOUND, "stub has no assets"),
        head_only=head_only,
    )


def make_handler(
    registry: Registry, static_files: StaticFiles | None = None
) -> type[BaseHTTPRequestHandler]:
    static = static_files or StaticFiles()

    class StubHandler(BaseHTTPRequestHandler):
        server_version = "OniSoulStub/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # 静默默认访问日志
            return

        def _serve_get(self, *, head_only: bool) -> None:
            if self.path.split("?")[0] == "/client/status":
                _json_response(
                    self,
                    200,
                    envelope.ok({"service": "onisoul-stub", "status": "up"}),
                    head_only=head_only,
                )
                return
            try:
                resource = static.resolve(self.path)
            except StaticPathError as exc:
                _json_response(
                    self,
                    400,
                    envelope.error(envelope.ERR_BAD_REQUEST, str(exc)),
                    head_only=head_only,
                )
                return
            if resource is not None and _static_response(
                self, resource, head_only=head_only
            ):
                return
            _static_not_found(self, head_only=head_only)

        def do_GET(self) -> None:
            self._serve_get(head_only=False)

        def do_HEAD(self) -> None:
            self._serve_get(head_only=True)

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
