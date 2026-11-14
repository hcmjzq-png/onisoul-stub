"""HTTP 接入层：路由分发 + 会话解析。

路由：
    GET  /client/status      健康检查（不经过业务注册表）
    POST /api/<api>          业务接口：解析 params → 校验 token → registry.dispatch
                             无会话时按 app/auth.py 的放行名单判定，非名单内一律拒绝
                             （strict；AUTH_MODE=observe 时只计数放行）
    GET  其余 PC 路径        WebPlayer / app.unity3d / AssetBundle / crossdomain

只绑定 127.0.0.1；对外由 tools/proxy80.py 在 80 端口转发，本层不直接暴露公网。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import auth, sessions
from app.business.registry import Registry
from app.protocol import envelope
from app.transport.static import StaticFiles, StaticPathError, StaticResource
from app.transport import login_page


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


def _html_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    *,
    head_only: bool = False,
    location: str | None = None,
) -> None:
    handler.send_response(status)
    if location:
        handler.send_header("Location", location)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Connection", "close")
    handler.end_headers()
    if not head_only and body:
        handler.wfile.write(body)


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
    if not value.lower().startswith("bytes="):
        raise ValueError("unsupported range")
    if "," in value:
        return None
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
            # 站点入口：客户端偶尔从根路径进入，根下只有原版 app.html，
            # 而它的 js/img 全在 /client/ 下，根下逐个 404，窗口就是一片白。
            # 这里直接 302 到重建的登录页，任何入口都落到同一个页面。
            if self.path.split("?")[0] == "/":
                _html_response(
                    self,
                    302,
                    b"",
                    head_only=head_only,
                    location="/index.php/gwz/client/login/",
                )
                return
            # 客户端部分子系统（社会信息、任务、商店轮询）走 GET 打业务接口，
            # 原先一路落到静态层，返回 404 "stub has no assets"。
            # 这里把 /api/ 的 GET 也接进注册表，参数从 query string 取。
            if self.path.split("?")[0].startswith("/api/"):
                import urllib.parse as _urlparse

                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(_urlparse.parse_qsl(query, keep_blank_values=True))
                self._serve_api(
                    self.path.split("?")[0], params, head_only=head_only
                )
                return
            if login_page.matches(self.path):
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                result = login_page.handle_get(query, head_only=head_only, user_agent=self.headers.get("User-Agent", ""))
                _html_response(
                    self, result.status, result.body, head_only=head_only,
                    location=result.location,
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

        def _serve_api(
            self, path: str, params: dict[str, Any], *, head_only: bool = False
        ) -> None:
            """业务接口统一入口：POST 与 GET 共用。"""
            api = path[len("/api/"):].strip("/")
            if api not in registry.known():
                _json_response(
                    self,
                    404,
                    envelope.error(envelope.ERR_NOT_FOUND, f"未知接口: {api}"),
                    head_only=head_only,
                )
                return

            token = str(params.get("token") or "").strip()
            try:
                session = sessions.resolve(token) if token else None
            except Exception as exc:
                print(
                    f"[stub][auth] 会话解析失败 {api}: {type(exc).__name__}",
                    file=sys.stderr,
                )
                session = None

            denial = auth.check(api, session, has_token=bool(token))
            if denial is not None:
                _json_response(self, 200, denial, head_only=head_only)
                return

            status, body = registry.dispatch(api, params, session)
            _json_response(self, status, body, head_only=head_only)

        def do_GET(self) -> None:
            self._serve_get(head_only=False)

        def do_HEAD(self) -> None:
            self._serve_get(head_only=True)

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if login_page.matches(path):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b""
                form = login_page.parse_form(raw, self.headers.get("Content-Type", ""))
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                result = login_page.handle_post(form, login_page.page_of(query))
                _html_response(
                    self, result.status, result.body, location=result.location
                )
                return
            if not path.startswith("/api/"):
                _json_response(self, 404, envelope.error(envelope.ERR_NOT_FOUND))
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            ctype = self.headers.get("Content-Type", "")
            params = envelope.parse_params(raw, ctype)
            self._serve_api(path, params, head_only=False)

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
