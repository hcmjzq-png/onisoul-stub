#!/usr/bin/env python3
"""Bounded HTTP gateway and credential-redacted capture for the PC client."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.protocol import envelope

ROOT = os.environ.get("ONI_ROOT") or str(Path(__file__).resolve().parents[1])
LOG_DIR = os.environ.get("ONI_LOG_DIR") or os.path.join(ROOT, "logs")
BINARY_EXT = (".unity3d", ".png", ".jpg", ".mp3", ".d", ".bin", ".ico", ".gif")
MAX_BODY_LOG = 64 * 1024
MAX_REQUEST_BODY = 2 * 1024 * 1024
HOP_HEADERS = {"connection", "proxy-connection", "keep-alive", "te", "trailer",
               "transfer-encoding", "upgrade", "proxy-authorization", "proxy-authenticate"}
SECRET_FIELDS = {"password", "passwd", "token", "sessionkey", "loginhash", "key",
                 "authorization", "cookie", "salt", "password_hash"}
_log_lock = threading.Lock()


def log_path() -> str:
    return os.path.join(LOG_DIR, f"capture-{datetime.now():%Y%m%d}.jsonl")


def write_rec(rec: dict) -> None:
    try:
        with _log_lock:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(log_path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[proxy80] capture write failed: {type(exc).__name__}", file=sys.stderr)


def redact(value):
    if isinstance(value, dict):
        return {k: "<redacted>" if k.lower() in SECRET_FIELDS else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def capture_body(body: bytes, ctype: str, *, request: bool = False) -> str:
    # Parse before truncating: truncated JSON must never fall back to raw secrets.
    if request:
        value = envelope.parse_params(body, ctype)
    elif "json" in ctype.lower():
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError):
            return "<unparsed response>"
    else:
        return f"<body {len(body)}B>"
    return json.dumps(redact(value), ensure_ascii=False)[:MAX_BODY_LOG]


class Handler(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 18080
    protocol_version = "HTTP/1.1"
    timeout = 15
    disable_nagle_algorithm = True

    def log_message(self, fmt, *args):
        return

    def _forward(self) -> None:
        self.close_connection = True
        if self.headers.get("Transfer-Encoding"):
            self.send_error(501, "Transfer-Encoding is unsupported")
            return
        lengths = self.headers.get_all("Content-Length", [])
        try:
            raw_length = lengths[0] if lengths else "0"
            if len(lengths) > 1 or not raw_length.isascii() or not raw_length.isdecimal():
                raise ValueError
            length = int(raw_length)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if length > MAX_REQUEST_BODY:
            self.send_error(413, "Request body too large")
            return
        try:
            body = self.rfile.read(length) if length else b""
        except TimeoutError:
            self.send_error(408)
            return
        if len(body) != length:
            self.send_error(400, "Incomplete request body")
            return
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.send_error(400, "Invalid request target")
            return
        path = target.path or "/"
        upstream_path = path + ("?" + target.query if target.query else "")
        blocked = HOP_HEADERS | {v.strip().lower() for v in self.headers.get("Connection", "").split(",")}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in blocked | {"content-length"}}
        headers["Connection"] = "close"
        headers["Content-Length"] = str(length)
        started = time.monotonic()
        conn = http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=15)
        status, size, captured, ctype = 502, 0, bytearray(), ""
        sent_headers = False
        binary = path.lower().endswith(BINARY_EXT)
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            ctype = resp.getheader("Content-Type", "")
            self.send_response_only(status, resp.reason)
            response_blocked = HOP_HEADERS | {v.strip().lower() for v in resp.getheader("Connection", "").split(",")}
            for k, v in resp.getheaders():
                if k.lower() not in response_blocked:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            sent_headers = True
            if self.command != "HEAD" and status not in (204, 304):
                while chunk := resp.read(64 * 1024):
                    size += len(chunk)
                    if not binary and len(captured) <= MAX_BODY_LOG:
                        captured.extend(chunk)
                    self.wfile.write(chunk)
        except (OSError, http.client.HTTPException):
            if not sent_headers:
                self.send_error(502, "Upstream unavailable")
        finally:
            conn.close()
            login = path.startswith("/index.php/gwz/client/login")
            write_rec({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "method": self.command, "path": path,
                "api": path[5:].strip("/") if path.startswith("/api/") else "",
                "status": status, "ms": round((time.monotonic() - started) * 1000),
                "req_query": "<redacted login>" if login or path == "/client/app.html" else capture_body(target.query.encode(), "application/x-www-form-urlencoded", request=True),
                "req_body": "<redacted login>" if login else capture_body(body, self.headers.get("Content-Type", ""), request=True),
                "resp_body": f"<binary {size}B>" if binary else "<omitted response>" if login or len(captured) > MAX_BODY_LOG else capture_body(bytes(captured), ctype),
                "resp_size": size,
            })

    do_GET = _forward
    do_POST = _forward
    do_HEAD = _forward


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=80)
    ap.add_argument("--upstream", type=int, default=18080)
    ap.add_argument("--upstream-host", default="127.0.0.1")
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    Handler.upstream_host, Handler.upstream_port = args.upstream_host, args.upstream
    with Server((args.host, args.listen), Handler) as srv:
        print(f"[proxy80] {args.host}:{args.listen} -> {args.upstream_host}:{args.upstream}")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
