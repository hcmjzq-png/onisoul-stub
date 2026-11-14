#!/usr/bin/env python3
"""Exercise HTTP registration/login/create-player using an isolated temporary account.

Requires the target service's ONI_DB_* configuration for exact-account cleanup.
No existing player is modified; tokens/passwords are never printed.
"""
from __future__ import annotations

import argparse
import http.client
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db


def run(host: str, port: int) -> None:
    account = "audit_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(18)
    login_path = "/index.php/gwz/client/login/"

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(host, port, timeout=15)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def api(name, params, method="POST"):
        form = urlencode({"params": json.dumps(params)})
        status, _, body = request(method, "/api/" + name + ("?" + form if method == "GET" else ""),
                                 form if method == "POST" else None,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
        assert status == 200, (name, status)
        return json.loads(body)

    # Confirm DB access and uniqueness before creating anything through HTTP.
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("SELECT account_key FROM users WHERE account_key = %s", (account,))
            assert cur.fetchone() is None
    try:
        form = urlencode({"account": account, "password": password})
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        assert request("POST", login_path + "?page=register", form, headers)[0] == 200
        status, response_headers, _ = request("POST", login_path, form, headers)
        assert status == 302, "web login did not issue a redirect"
        token = parse_qs(urlsplit(response_headers["Location"]).query)["token"][0]
        initial = api("auth/gameLogin", {"token": token})
        assert initial.get("succeeded") is False and initial.get("playerId"), "fresh player detection"
        assert api("auth/registerName", {"token": token, "username": account})["succeeded"]
        assert api("auth/createPlayer", {"token": token, "username": account, "countryId": "country01",
                                        "navigatorId": "navi8000101", "colorIndex": "color1"})["succeeded"]
        assert api("auth/gameLogin", {"token": token})["succeeded"]
        params = api("common/getPlayerParams", {"token": token}, "GET")
        assert params["entity"]["username"] == account and params["characterCount"] > 0
        assert api("common/getPlayerParams", {}).get("error") == "UNAUTHORIZED"
        debug = api("debug/devLogin", {"username": account})
        assert debug.get("succeeded") is False and not debug.get("token")
        assert request("HEAD", "/client/app.html")[0] == 200
        status, _, body = request("GET", "/api/audit/absent")
        assert status == 404 and b"no stub response" in body
        status, _, body = request("GET", "/client/audit-absent.unity3d")
        assert status == 404 and b"stub has no assets" in body
        print("[http-smoke] web register/login -> name/create -> re-login -> GET params: OK; strict/debug guards: OK")
    finally:
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT player_id FROM accounts WHERE account_key = %s", (account,))
                row = cur.fetchone()
                if row:
                    cur.execute("DELETE FROM players WHERE player_id = %s", (row["player_id"],))
                cur.execute("DELETE FROM sessions WHERE account_key = %s", (account,))
                cur.execute("DELETE FROM accounts WHERE account_key = %s", (account,))
                cur.execute("DELETE FROM users WHERE account_key = %s", (account,))
        print("[http-smoke] temporary audit account cleaned up")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--create-test-account", action="store_true", required=True)
    args = parser.parse_args()
    run(args.host, args.port)
