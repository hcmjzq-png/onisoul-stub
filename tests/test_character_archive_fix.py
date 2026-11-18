"""Different character files must coexist without changing serialized textures."""
import struct
import unittest

from tools.build_character_archive_fix import rebuild
from tools.port_legacy_media import pack_pc, unpack_pc
from tools.repair_unityweb_lzma import repair


class CharacterArchiveFixTest(unittest.TestCase):
    def test_shared_template_archive_becomes_distinct_and_preserves_each_payload(self):
        header = (b'UnityWeb\0' + struct.pack('>I', 3)
                  + b'3.x.x\0' + b'3.5.6f4\0' + bytes(33))
        archive = 'CustomAssetBundle-' + 'a' * 32
        names = set()
        for index in range(6):
            node = bytes(range(256)) * (index + 1)
            blob = pack_pc(header, archive, node)
            logical = f'chara1_{index:05d}_01'
            fixed, proof = rebuild(blob, logical)
            _, name, restored = unpack_pc(fixed)
            self.assertEqual(restored, node)
            self.assertNotEqual(name, archive)
            self.assertNotIn(name, names)
            names.add(name)
            self.assertTrue(proof['serialized_unchanged'])
            self.assertFalse(repair(fixed)[1]['changed'])
            self.assertEqual(rebuild(blob, logical)[0], fixed)
        self.assertEqual(len(names), 6)
