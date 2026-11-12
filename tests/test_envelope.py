"""协议层纯函数测试：不依赖数据库与外部依赖。"""
import unittest

from app.protocol import envelope


class ParseParamsTest(unittest.TestCase):
    def test_empty_body(self):
        self.assertEqual(envelope.parse_params(b""), {})
        self.assertEqual(envelope.parse_params(b"   "), {})

    def test_json_body(self):
        body = b'{"token": "abc", "level": 3}'
        data = envelope.parse_params(body, "application/json")
        self.assertEqual(data, {"token": "abc", "level": 3})

    def test_form_params_field(self):
        body = b'params=%7B%22token%22%3A%22x%22%7D'
        data = envelope.parse_params(body, "application/x-www-form-urlencoded")
        self.assertEqual(data, {"token": "x"})

    def test_malformed_json_returns_empty(self):
        self.assertEqual(envelope.parse_params(b"{oops", "application/json"), {})


class ResponseTest(unittest.TestCase):
    def test_ok_injects_fields(self):
        body = envelope.ok({"playerId": "1"})
        self.assertTrue(body["succeeded"])
        self.assertIn("now", body)
        self.assertEqual(body["playerId"], "1")

    def test_error_fields(self):
        body = envelope.error(envelope.ERR_NOT_FOUND, "missing")
        self.assertFalse(body["succeeded"])
        self.assertEqual(body["error"], envelope.ERR_NOT_FOUND)
        self.assertEqual(body["message"], "missing")
        self.assertIn("now", body)


if __name__ == "__main__":
    unittest.main()
