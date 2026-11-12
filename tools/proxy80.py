#!/usr/bin/env python3
"""80 端口转发代理：客户端 ──▶ 本代理 ──▶ stub(127.0.0.1:18080)。

作用：
  - 对外只暴露 80；stub 绑定回环，不直接公网可达。
  - 原样转发请求/响应，并把报文记录到 logs/capture-YYYYMMDD.jsonl，供协议核对。
  - 二进制资源（.unity3d/.png/mp3 等）只记大小，不记内容。

用法：
    python3 tools/proxy80.py --listen 80 --upstream 18080
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
import time
from datetime import datetime

ROOT = os.environ.get("ONI_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
LOG_DIR = os.environ.get("ONI_LOG_DIR") or os.path.join(ROOT, "logs")
BINARY_EXT = (".unity3d", ".png", ".jpg", ".mp3", ".d", ".bin", ".ico", ".gif")
MAX_BODY_LOG = 64 * 1024


def log_path() -> str:
    return os.path.join(LOG_DIR, f"capture-{datetime.now():%Y%m%d}.jsonl")


def write_rec(rec: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Handler(socketserver.BaseRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 18080

    def _read_request(self) -> tuple[str, str, dict[str, str], bytes] | None:
        line = self.request.makefile("rb").readline()
        if not line:
            return None
        method, path, _ver = line.decode("latin1").split(" ", 2)
        headers: dict[str, str] = {}
        while True:
            h = self.request.makefile("rb").readline()
            if not h or h in (b"\r\n", b"\n"):
                break
            k, _, v = h.partition(b":")
            headers[k.decode("latin1").strip().lower()] = v.decode("latin1").strip()
        length = int(headers.get("content-length") or 0)
        body = self.request.makefile("rb").read(length) if length > 0 else b""
        return method, path, headers, body

    def handle(self) -> None:
        parsed = self._read_request()
        if parsed is None:
            return
        method, path, headers, body = parsed
        t0 = time.time()
        try:
            conn = http.client.HTTPConnection(
                self.upstream_host, self.upstream_port, timeout=10
            )
            forward_headers = {
                k: v for k, v in headers.items()
                if k not in ("connection", "proxy-connection", "host")
            }
            conn.request(method, path, body=body, headers=forward_headers)
            resp = conn.getresponse()
            resp_body = resp.read()
            resp_headers = {k: v for k, v in resp.getheaders()}
            status = resp.status
            conn.close()
        except OSError as exc:
            self._send(502, b'{"succeeded":false,"error":"UPSTREAM"}',
                       {"Content-Type": "application/json; charset=utf-8"})
            write_rec({"ts": datetime.now().isoformat(timespec="seconds"),
                       "method": method, "path": path, "status": 502,
                       "error": str(exc)})
            return

        self._send(status, resp_body, resp_headers)

        low = path.split("?")[0].lower()
        is_bin = low.endswith(BINARY_EXT)
        write_rec({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "method": method,
            "path": path.split("?")[0],
            "api": path.split("/api/", 1)[-1].strip("/") if "/api/" in path else "",
            "status": status,
            "ms": round((time.time() - t0) * 1000),
            "req_body": ("<binary %dB>" % len(body)) if is_bin
                        else body[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "resp_body": ("<binary %dB>" % len(resp_body)) if is_bin
                         else resp_body[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "resp_size": len(resp_body),
        })

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.request.sendall(f"HTTP/1.1 {status} OK\r\n".encode("latin1"))
        for k, v in headers.items():
            if k.lower() in ("connection", "transfer-encoding", "content-length"):
                continue
            self.request.sendall(f"{k}: {v}\r\n".encode("latin1"))
        self.request.sendall(f"Content-Length: {len(body)}\r\n".encode())
        self.request.sendall(b"Connection: close\r\n\r\n")
        self.request.sendall(body)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=80)
    ap.add_argument("--upstream", type=int, default=18080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    Handler.upstream_port = args.upstream
    srv = Server((args.host, args.listen), Handler)
    print(f"[proxy80] {args.host}:{args.listen} → 127.0.0.1:{args.upstream}")
    print(f"[proxy80] 记录 → {log_path()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[proxy80] 退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
