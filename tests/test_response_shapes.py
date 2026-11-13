"""Endpoint response-shape regression tests."""
from __future__ import annotations

import unittest

from app.business import contract, response_shapes
from app.business.registry import Registry
from app.main import build_registry


class ResponseShapeTest(unittest.TestCase):
    def test_shape_rules_are_known_disjoint_endpoints(self):
        unknown = sorted(set(response_shapes.BARE_MAP_ENDPOINTS) - set(contract.endpoints()))
        self.assertEqual(unknown, [])
        unknown_scalar = sorted(
            set(response_shapes.SCALAR_ROOT_EVIDENCE) - set(contract.endpoints())
        )
        self.assertEqual(unknown_scalar, [])
        self.assertFalse(
            response_shapes.BARE_MAP_ENDPOINTS
            & set(response_shapes.SCALAR_ROOT_EVIDENCE)
        )
        unknown_exact = sorted(
            set(response_shapes.EXACT_BODY_ENDPOINTS) - set(contract.endpoints())
        )
        self.assertEqual(unknown_exact, [])
        self.assertFalse(
            response_shapes.EXACT_BODY_ENDPOINTS
            & (response_shapes.BARE_MAP_ENDPOINTS
               | set(response_shapes.SCALAR_ROOT_EVIDENCE))
        )
        for evidence in {
            **response_shapes.BARE_MAP_EVIDENCE,
            **response_shapes.SCALAR_ROOT_EVIDENCE,
        }.values():
            self.assertIn(":", evidence)

    def test_bare_map_placeholder_has_no_envelope(self):
        registry = Registry().register_contract_defaults()
        for api in response_shapes.BARE_MAP_ENDPOINTS:
            with self.subTest(api=api):
                status, body = registry.dispatch(api, {}, None)
                self.assertEqual(status, 200)
                self.assertEqual(body, {})

    def test_scalar_root_endpoints_keep_typed_contract_keys(self):
        registry = Registry().register_contract_defaults()
        for api in response_shapes.SCALAR_ROOT_EVIDENCE:
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
                    ok, _ = contract.lookup(body, key)
                    self.assertTrue(ok, key)

    def test_every_envelope_endpoint_keeps_envelope_and_typed_keys(self):
        registry = Registry().register_contract_defaults()
        for api in contract.endpoints():
            if response_shapes.shape_for(api) is not response_shapes.ResponseShape.ENVELOPE:
                continue
            with self.subTest(api=api):
                status, body = registry.dispatch(api, {}, None)
                self.assertEqual(status, 200)
                self.assertIs(body["succeeded"], True)
                self.assertIsInstance(body["now"], float)
                for field in contract.response(api):
                    key, typ = field["key"], field["type"]
                    if (
                        not typ
                        or key in {"succeeded", "now"}
                        or "<" in key
                        or ">" in key
                    ):
                        continue
                    ok, _ = contract.lookup(body, key)
                    self.assertTrue(ok, key)

    def test_envelope_placeholder_keeps_timestamp_and_success(self):
        registry = Registry().register_contract_defaults()
        status, body = registry.dispatch("common/getServerTime", {}, None)
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
