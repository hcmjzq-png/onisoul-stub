"""Real HTTP policy checks; every I endpoint stays closed, even in observe mode."""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from unittest.mock import Mock, patch

from app import auth
from app.business import contract
from app.business.admin_debug_services import DISABLED_ENDPOINTS, denial
from app.business.registry import Registry
from app.transport import http_server


class ClosedAdminTest(unittest.TestCase):
    def test_inventory_and_bootstrap_login_scope(self):
        self.assertEqual(len(DISABLED_ENDPOINTS), 32)
        self.assertFalse(DISABLED_ENDPOINTS - set(contract.endpoints()))
        self.assertNotIn("debug/debugLoginCog", auth.PRE_AUTH_APIS)
        for api in ("debug/devLogin", "debug/debugLogin", "auth/gameLogin"):
            self.assertIsNone(denial(api))  # outside this group's 32 entries

    def test_all_routes_denied_before_auth_or_observe_allowance(self):
        for mode in ("strict", "observe"):
            for session in (None, {"playerId": "p"},
                            {"playerId": "1", "role": "admin", "isAdmin": True}):
                with patch.dict(os.environ, {"AUTH_MODE": mode}):
                    for api in DISABLED_ENDPOINTS:
                        body = auth.check(api, session)
                        self.assertFalse(body["succeeded"], api)
                        self.assertIn("no stub response", body["errorReason"])

    def test_http_get_and_post_never_reach_grant_or_login_handler(self):
        handler = Mock(side_effect=AssertionError("privileged handler invoked"))
        registry = Registry()
        for api in DISABLED_ENDPOINTS:
            registry.register(api, handler)
        server = http_server.serve("127.0.0.1", 0, registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"AUTH_MODE": "observe"}), patch.object(
                http_server.sessions, "resolve", return_value={"playerId": "p"}
            ):
                for method in ("GET", "POST"):
                    for api in DISABLED_ENDPOINTS:
                        conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                        payload = json.dumps({"token": "player-token", "role": "admin",
                                              "rewards": {"item11_0000101": 999999},
                                              "playerIds": ["other"]})
                        path = f"/api/{api}" + ("?token=player-token&isAdmin=true" if method == "GET" else "")
                        conn.request(method, path, body=payload if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
                        response = conn.getresponse()
                        body = json.loads(response.read())
                        conn.close()
                        self.assertEqual(response.status, 200)
                        self.assertFalse(body["succeeded"], api)
                        self.assertIn("disabled", body["errorReason"])
            handler.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
