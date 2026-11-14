"""Tests for strict container and IL decoding primitives."""
from __future__ import annotations

import struct
import unittest

try:
    from dncil.cil.body import CilMethodBody

    from tools.oni_il import (
        BytesBodyReader,
        MethodDecodeError,
        ensure_supported_opcodes,
        parse_unity_web_data,
    )

    HAS_IL_DEPS = True
except ModuleNotFoundError:
    HAS_IL_DEPS = False


@unittest.skipUnless(HAS_IL_DEPS, "install requirements-analysis.txt")
class IlLibraryTest(unittest.TestCase):
    def test_parses_unity_web_data_big_endian_entry_table(self):
        payload = b"MZpayload"
        name = b"Assembly-CSharp.dll\0"
        raw = (
            struct.pack(">I", 1)
            + name
            + struct.pack(">II", 4 + len(name) + 8, len(payload))
            + payload
        )
        parsed = parse_unity_web_data(raw)
        self.assertEqual(parsed.count, 1)
        self.assertEqual(parsed.entries[0].name, "Assembly-CSharp.dll")
        self.assertEqual(parsed.entries[0].size, len(payload))
        self.assertEqual(raw[parsed.entries[0].offset :], payload)

    def test_unknown_opcode_never_falls_back_to_one_byte_skips(self):
        # Tiny header, two bytes of IL. 0xfe 0xff is decoded by dncil to its
        # UNKNOWN2 placeholder; the verifier must reject placeholders.
        raw = bytes([(2 << 2) | 0x02, 0xFE, 0xFF])
        body = CilMethodBody(BytesBodyReader(raw, 0))
        self.assertEqual(body.instructions[0].opcode.name, "UNKNOWN2")
        with self.assertRaises(MethodDecodeError):
            ensure_supported_opcodes(body)

    def test_complete_tiny_ret_body_decodes(self):
        raw = bytes([(1 << 2) | 0x02, 0x2A])
        body = CilMethodBody(BytesBodyReader(raw, 0))
        self.assertEqual(body.code_size, 1)
        self.assertEqual(body.instructions[-1].opcode.name, "ret")


if __name__ == "__main__":
    unittest.main()
