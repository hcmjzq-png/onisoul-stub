#!/usr/bin/env python3
"""Loopback-only login memory for the original memory-only Qt cookie jar.

Windows DPAPI binds the encrypted file to the current Windows user. Neither the
game server nor HTTP cookies receive the saved password. Start explicitly via
start_login_memory.ps1 or start_cloud_client.ps1; no OS startup entry is created.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

ORIGIN = "http://passport.86joy.com"
PORT = 19765
LOCK = threading.Lock()


def protect(raw: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI required")
    class Blob(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        func = crypt.CryptUnprotectData
    else:
        func = crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(dest.data, dest.length)
    finally:
        kernel.LocalFree(dest.data)


def handler_for(store: Path):
    class Handler(BaseHTTPRequestHandler):
        timeout = 3

        def log_message(self, *_args):
            pass  # Never log credentials, request bodies or browser origins.

        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            if self.headers.get("Origin") == ORIGIN:
                self.send_header("Access-Control-Allow-Origin", ORIGIN)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            return (self.client_address[0] == "127.0.0.1"
                    and self.headers.get("Host") == "127.0.0.1:" + str(self.server.server_port)
                    and self.headers.get("Origin") == ORIGIN
                    and self.path == "/credentials")

        def do_OPTIONS(self):
            if not self.allowed():
                self.reply(403, {"error": "origin rejected"}); return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Oni-Login")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if self.path == "/health" and not self.headers.get("Origin"):
                self.reply(200, {"service": "onisoul-login-memory", "version": 1}); return
            if not self.allowed() or self.headers.get("X-Oni-Login") != "1":
                self.reply(403, {"error": "origin rejected"}); return
            try:
                with LOCK:
                    value = json.loads(protect(store.read_bytes(), decrypt=True)) if store.exists() else {}
                self.reply(200, value)
            except (OSError, ValueError):
                self.reply(500, {"error": "saved login cannot be read"})

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Oni-Login") != "1":
                self.reply(403, {"error": "origin rejected"}); return
            try:
                if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                    raise ValueError("invalid request length")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("invalid login record")
                value = json.loads(self.rfile.read(size))
                if (not isinstance(value, dict) or not set(value) <= {"a", "p"}
                        or any(not isinstance(v, str) or len(v) > 128 for v in value.values())
                        or (value and set(value) != {"a", "p"})):
                    raise ValueError("invalid login record")
                with LOCK:
                    if value:
                        payload = protect(json.dumps(value).encode())
                        store.parent.mkdir(parents=True, exist_ok=True)
                        temp = store.with_suffix(".tmp")
                        temp.write_bytes(payload)
                        os.replace(temp, store)
                    else:
                        store.unlink(missing_ok=True)
                self.reply(200, {"saved": bool(value)})
            except (OSError, ValueError):
                self.reply(400, {"error": "login record rejected"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--store", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) / "OniSoul" / "login.dpapi")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows DPAPI required")
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.store)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
