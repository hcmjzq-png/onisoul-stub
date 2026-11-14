"""鉴权闸门（app/auth.py）与 HTTP 接入层的回归测试。"""
from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from unittest import mock

from app import auth
from app.business import contract, response_shapes
from app.business.registry import Registry
from app.transport import http_server


class PolicyTest(unittest.TestCase):
    def setUp(self):
        auth.reset()
        self._env = mock.patch.dict(os.environ, {"AUTH_MODE": "strict"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        auth.reset()

    def test_pre_auth_set_all_exist_in_contract(self):
        unknown = sorted(auth.PRE_AUTH_APIS - set(contract.endpoints()))
        self.assertEqual(unknown, [], "放行名单里有契约中不存在的端点")

    def test_pre_auth_endpoints_pass_without_session(self):
        for api in sorted(auth.PRE_AUTH_APIS):
            self.assertIsNone(auth.check(api, None), api)

    def test_placeholder_endpoint_denied_in_strict_mode(self):
        body = auth.check("politic/shop/getShopItems", None)
        self.assertIsNotNone(body)
        self.assertFalse(body["succeeded"])
        self.assertEqual(body["error"], "UNAUTHORIZED")

    def test_denial_body_follows_endpoint_shape(self):
        bare = sorted(response_shapes.BARE_MAP_ENDPOINTS)[0]
        body = auth.check(bare, None)
        self.assertEqual(set(body), {"errorReason"})

    def test_invalid_token_reason_differs(self):
        self.assertEqual(
            auth.check("politic/shop/getShopItems", None, has_token=True)["message"],
            "invalid token",
        )

    def test_observe_mode_passes_but_counts(self):
        os.environ["AUTH_MODE"] = "observe"
        self.assertIsNone(auth.check("politic/shop/getShopItems", None))
        report = auth.report()
        self.assertEqual(report["observe_passed"].get("politic/shop/getShopItems"), 1)

    def test_session_always_passes(self):
        session = {"token": "t", "playerId": "1"}
        self.assertIsNone(auth.check("politic/shop/getShopItems", session))


class TransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = Registry().register_contract_defaults()
        cls.server = http_server.serve("127.0.0.1", 0, cls.registry)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, api, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8")
        conn.request(
            "POST",
            f"/api/{api}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        conn.close()
        return response.status, data

    def setUp(self):
        auth.reset()
        patcher = mock.patch.object(
            http_server.sessions, "resolve", lambda token, **kw: None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self._env = mock.patch.dict(os.environ, {"AUTH_MODE": "strict"})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_unauthenticated_business_call_is_denied(self):
        status, body = self._post("politic/shop/getShopItems", {"token": ""})
        self.assertEqual(status, 200)
        self.assertFalse(body["succeeded"])
        self.assertEqual(body["error"], "UNAUTHORIZED")

    def test_token_in_params_is_read(self):
        # 客户端把 token 塞进 params（WebApiClient.cs:260-263），不是 header。
        status, body = self._post("politic/shop/getShopItems", {"token": "deadbeef"})
        self.assertEqual(status, 200)
        self.assertEqual(body["message"], "invalid token")

    def test_pre_auth_endpoint_still_answers(self):
        status, body = self._post("common/getRevisions", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["succeeded"])

    def test_unknown_api_stays_404(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/no/such/api", body=b"{}")
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        conn.close()

    def test_static_health_check_unaffected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/client/status")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        conn.close()


if __name__ == "__main__":
    unittest.main()
