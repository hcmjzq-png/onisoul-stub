"""Regression cases found by comparing the deployed service with the PC client."""
import http.client
import json
import socket
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from app.business.registry import Registry
from app.business.gameplay import GameplayService
from app.sessions import sessions
from app.state import player
from app.transport import login_page
from app.transport.http_server import serve
from app.transport.static import StaticFiles
from tools import proxy80


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class TransportAuditTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.handler = MagicMock(side_effect=lambda params, session: params)
        self.registry.register("common/getRevisions", self.handler)

    def test_get_unwraps_same_params_as_post_and_head_does_not_dispatch(self):
        with running(serve("127.0.0.1", 0, self.registry)) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            params = {"someKey": 42, "array": [1, 2]}
            conn.request("GET", "/api/common/getRevisions?" + urlencode({"params": json.dumps(params)}))
            self.assertEqual(json.loads(conn.getresponse().read()), params)
            conn.close()
            self.handler.assert_called_once()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("HEAD", "/api/common/getRevisions")
            self.assertEqual(conn.getresponse().status, 405)
            self.handler.assert_called_once()
            conn.close()

    def test_missing_asset_and_api_are_distinct(self):
        with running(serve("127.0.0.1", 0, self.registry)) as port:
            for path, message in [("/absent.unity3d", "stub has no assets"), ("/api/absent", "no stub response")]:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", path)
                resp = conn.getresponse()
                self.assertEqual(resp.status, 404)
                self.assertIn(message, json.loads(resp.read())["message"])
                conn.close()

    def test_proxy_handles_malformed_input_head_ranges_and_secret_capture(self):
        records = []
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "client").mkdir()
            Path(tmp, "client", "app.html").write_bytes(b"abcdefghij")
            stub = serve("127.0.0.1", 0, self.registry, StaticFiles(web_dir=tmp))
            with running(stub) as upstream, patch.object(proxy80.Handler, "upstream_port", upstream), patch.object(proxy80, "write_rec", side_effect=records.append):
                with running(proxy80.Server(("127.0.0.1", 0), proxy80.Handler)) as port:
                    for raw, code in [
                        (b"nonsense\r\n\r\n", b"400"),
                        (b"POST /api/x HTTP/1.1\r\nHost: test\r\nContent-Length: -1\r\n\r\n", b"400"),
                        (b"POST /api/x HTTP/1.1\r\nHost: test\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n", b"400"),
                        (b"POST /api/x HTTP/1.1\r\nHost: test\r\nContent-Length: 9999999\r\n\r\n", b"413"),
                        (b"POST /api/x HTTP/1.1\r\nHost: test\r\nTransfer-Encoding: chunked\r\n\r\n", b"501"),
                    ]:
                        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                            sock.sendall(raw)
                            data = b""
                            while chunk := sock.recv(4096):
                                data += chunk
                            self.assertIn(code, data)
                    for method, headers, status, length, body in [
                        ("HEAD", {}, 200, "10", b""),
                        ("GET", {"Range": "bytes=2-4"}, 206, "3", b"cde"),
                    ]:
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                        conn.request(method, "/client/app.html", headers=headers)
                        resp = conn.getresponse()
                        self.assertEqual((resp.status, resp.getheader("Content-Length"), resp.read()), (status, length, body))
                        conn.close()
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                    payload = {"password": "hidden-password", "nested": {"token": "hidden-token"}, "a": 5}
                    conn.request("POST", "/api/common/getRevisions", json.dumps(payload), {"Content-Type": "application/json"})
                    self.assertEqual(json.loads(conn.getresponse().read()), payload)
                    conn.close()
            serialized = json.dumps(records)
            self.assertNotIn("hidden-password", serialized)
            self.assertNotIn("hidden-token", serialized)
            self.assertIn("redacted", serialized)


class LoginStateAuditTest(unittest.TestCase):
    def test_debug_login_is_disabled_without_explicit_key(self):
        store = MagicMock()
        service = GameplayService(session_store=store)
        with patch.dict("os.environ", {"STUB_DEBUG_LOGIN_KEY": ""}):
            result = service.dev_login({"username": "existing-player"}, None)
        self.assertFalse(result["succeeded"])
        store.issue.assert_not_called()

    def test_failed_session_creation_never_redirects_or_exposes_password(self):
        with patch.object(login_page, "verify_user", return_value="ok"), patch("app.sessions.issue", side_effect=RuntimeError("db down")):
            result = login_page.submit({"account": "audit", "password": "not-in-html"})
        self.assertEqual(result.status, 503)
        self.assertFalse(result.location)
        self.assertNotIn(b"not-in-html", result.body)

    def test_registration_dialog_escapes_script_closing_tag(self):
        with patch.object(login_page, "register_user", return_value=("ok", "")):
            result = login_page.register_submit({"account": "</script><script>alert(1)", "password": "test"})
        self.assertNotIn(b"</script><script>alert(1)", result.body)

    def test_account_mapping_uses_persisted_player_id(self):
        cur = MagicMock()
        cur.fetchone.return_value = {"player_id": "persisted"}
        self.assertEqual(sessions._ensure_account(cur, "DIFFERENT-CASE"), "persisted")
        self.assertEqual(len({sessions._player_id(k) for k in ("default", "player1", "pyddev1")}), 3)

    def test_corrupt_save_fails_instead_of_resetting_player(self):
        con = MagicMock()
        cur = con.cursor.return_value.__enter__.return_value
        with patch.object(player.db, "connection") as db:
            db.return_value.__enter__.return_value = con
            for payload in ["broken-json", "[]", '{"entity":null}']:
                cur.fetchone.return_value = {"state_json": payload}
                with self.assertRaisesRegex(ValueError, "invalid persisted"):
                    player.load("audit")


if __name__ == "__main__":
    unittest.main()
