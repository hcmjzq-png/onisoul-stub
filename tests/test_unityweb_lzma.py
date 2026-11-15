import lzma
import struct
import unittest

from tools.repair_unityweb_lzma import layout, repair


def bundle(payload):
    compressed = lzma.compress(payload, format=lzma.FORMAT_ALONE)
    prefix = b'UnityWeb\0' + struct.pack('>I', 3) + b'3.x.x\0' + b'3.5.6f4\0'
    header_size = len(prefix) + 32
    header = prefix + struct.pack('>IIIIIIII', header_size + len(compressed), header_size, 1, 1,
                                 len(compressed), len(payload), header_size + len(compressed), 0)
    return header + compressed


class UnityWebLengthTest(unittest.TestCase):
    def test_only_unknown_length_bytes_change_and_payload_is_identical(self):
        source = bundle(b'original-serialized-assets' * 1000)
        fixed, proof = repair(source)
        offset, compressed, size = layout(source)
        self.assertTrue(proof['changed'])
        self.assertEqual(source[:offset + 5], fixed[:offset + 5])
        self.assertEqual(source[offset + 13:], fixed[offset + 13:])
        self.assertEqual(struct.unpack_from('<Q', fixed, offset + 5)[0], size)
        filters = [{'id': lzma.FILTER_LZMA1, 'dict_size': 1 << 23, 'lc': 3, 'lp': 0, 'pb': 2}]
        self.assertEqual(lzma.decompress(fixed[offset + 13:], format=lzma.FORMAT_RAW, filters=filters),
                         lzma.decompress(source[offset:], format=lzma.FORMAT_ALONE))
        again, second = repair(fixed)
        self.assertEqual(again, fixed)
        self.assertFalse(second['changed'])

    def test_disagreeing_corrupt_and_oversized_payloads_are_rejected(self):
        original = bytearray(bundle(b'bounded-payload' * 100))
        offset, compressed, size = layout(original)
        wrong = original[:];struct.pack_into('<Q', wrong, offset + 5, size + 1)
        with self.assertRaisesRegex(ValueError, 'disagree'):
            repair(wrong)
        wrong = original[:-1]
        with self.assertRaisesRegex(ValueError, 'bounds'):
            repair(wrong)
        wrong = original[:];prefix_end = 13
        for _ in range(2):prefix_end = wrong.index(0, prefix_end) + 1
        struct.pack_into('>I', wrong, prefix_end + 20, 0xffffffff)
        with self.assertRaisesRegex(ValueError, 'limit'):
            repair(wrong)
