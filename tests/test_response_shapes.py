"""Endpoint response-shape regression tests."""
from __future__ import annotations

import unittest

from app.business import contract, response_shapes
from app.business.registry import Registry
from app.main import build_registry


class ResponseShapeTest(unittest.TestCase):
    def test_bare_map_rules_are_known_endpoints(self):
        unknown = sorted(set(response_shapes.BARE_MAP_ENDPOINTS) - set(contract.endpoints()))
        self.assertEqual(unknown, [])

    def test_bare_map_placeholder_has_no_envelope(self):
        registry = build_registry()
        for api in response_shapes.BARE_MAP_ENDPOINTS:
            with self.subTest(api=api):
                status, body = registry.dispatch(api, {}, None)
                self.assertEqual(status, 200)
                self.assertEqual(body, {})

    def test_scalar_root_endpoints_keep_typed_contract_keys(self):
        registry = build_registry()
        for api in ("siege/getBrief", "trophy/getTrophyProgress"):
            with self.subTest(api=api):
                status, body = registry.dispatch(api, {}, None)
                self.assertEqual(status, 200)
                self.assertIs(body["succeeded"], True)
                self.assertIsInstance(body["now"], float)
                fields = {
                    field["key"]: field["type"]
                    for field in contract.response(api)
                    if field["type"] and field["key"] not in {"succeeded", "now"}
                }
                self.assertTrue(fields)
                for key in fields:
                    self.assertIn(key, body)

    def test_envelope_placeholder_keeps_timestamp_and_success(self):
        status, body = build_registry().dispatch("common/getServerTime", {}, None)
        self.assertEqual(status, 200)
        self.assertIs(body["succeeded"], True)
        self.assertIsInstance(body["now"], float)

    def test_registry_does_not_rewrap_handler_response(self):
        registry = Registry()
        registry.register("test/raw", lambda params, session: {"id": {"value": 1}})
        status, body = registry.dispatch("test/raw", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"id": {"value": 1}})


if __name__ == "__main__":
    unittest.main()
