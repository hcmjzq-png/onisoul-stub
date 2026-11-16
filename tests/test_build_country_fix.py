import lzma
import struct
import unittest

from tools.build_country_fix import pack_app, replace_entry
from tools.oni_il import parse_unity_web_data
from tools.repair_unityweb_lzma import layout


class CountryAppContainerTest(unittest.TestCase):
    def test_replacing_assembly_preserves_scene_and_other_binary_entries(self):
        entries = [('Assembly-CSharp.dll', b'old'), ('mainData', bytes(range(256))),
                   ('Assembly-CSharp-firstpass.dll', b'unchanged\0dll')]
        offset = (4 + sum(len(n.encode()) + 9 for n, _ in entries) + 3) & ~3
        directory = bytearray(struct.pack('>I', len(entries)))
        bodies = bytearray()
        for name, body in entries:
            directory += name.encode() + b'\0' + struct.pack('>II', offset + len(bodies), len(body))
            bodies += body
        payload = bytes(directory).ljust(offset, b'\0') + bodies
        replacement = b'new dll larger than the original' * 7
        changed, first = replace_entry(payload, 'Assembly-CSharp.dll', replacement)
        prefix = b'UnityWeb\0' + struct.pack('>I', 3) + b'3.x.x\0' + b'3.5.6f4\0'
        app = pack_app(prefix, changed, first)
        header, compressed, size = layout(app)
        restored = lzma.decompress(app[header:header + compressed], format=lzma.FORMAT_ALONE)
        self.assertEqual(len(restored), size)
        result = {e.name: restored[e.offset:e.end] for e in parse_unity_web_data(restored).entries}
        self.assertEqual(result, dict(entries, **{'Assembly-CSharp.dll': replacement}))

    def test_missing_assembly_fails_instead_of_rebuilding_unrelated_entries(self):
        payload = struct.pack('>I', 1) + b'mainData\0' + struct.pack('>II', 24, 1) + b'\0' * 3 + b'x'
        with self.assertRaises(AssertionError):
            replace_entry(payload, 'Assembly-CSharp.dll', b'patch')
