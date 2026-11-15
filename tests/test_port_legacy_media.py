import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.port_legacy_media import ogg_frames, pack_pc, repack_serialized, transcode, unpack_pc
from tools.repair_unityweb_lzma import layout, repair


class LegacyMediaContainerTest(unittest.TestCase):
    def test_rebuilt_bundle_has_exact_length_and_distinct_archive_name(self):
        header = (b'UnityWeb\0' + struct.pack('>I', 3)
                  + b'3.x.x\0' + b'3.5.6f4\0' + bytes(33))
        node = bytes(range(256)) * 5
        blob = pack_pc(header, 'CustomAssetBundle-unique', node)
        _header, name, restored = unpack_pc(blob)
        self.assertEqual(name, 'CustomAssetBundle-unique')
        self.assertEqual(restored, node)
        self.assertFalse(repair(blob)[1]['changed'])
        offset, _, size = layout(blob)
        wrong = bytearray(blob)
        struct.pack_into('<Q', wrong, offset + 5, size + 1)
        with self.assertRaisesRegex(ValueError, 'known LZMA length'):
            unpack_pc(wrong)
        with self.assertRaisesRegex(ValueError, 'bounds'):
            unpack_pc(blob[:-1])

    def template(self):
        raw = bytearray(280)
        struct.pack_into('>IIII', raw, 0, 100, len(raw), 9, 256)
        struct.pack_into('<IIII', raw, 40, 0, 8, 8, 16)
        raw[256:] = b'old-head' + b'original-payload'
        objects = {1: SimpleNamespace(path_id=1, byte_start=256, byte_size=8,
            byte_start_offset=(168, 4), byte_size_offset=(172, 4), byte_base_offset=128),
            2: SimpleNamespace(path_id=2, byte_start=264, byte_size=16,
            byte_start_offset=(176, 4), byte_size_offset=(180, 4), byte_base_offset=128)}
        sf = SimpleNamespace(header=SimpleNamespace(version=9, endian='<',
            data_offset=256, file_size=280), target_platform=7, objects=objects)
        return bytes(raw), sf

    def test_variable_size_objects_keep_ids_metadata_and_alignment(self):
        raw, sf = self.template()
        result = repack_serialized(raw, sf, {1: b'new-name-and-container'})
        first, first_size, second, second_size = struct.unpack_from('<IIII', result, 40)
        self.assertEqual((first, first_size, second, second_size), (0, 22, 24, 16))
        self.assertEqual(result[256 + second:], b'original-payload')
        self.assertEqual(struct.unpack_from('>I', result, 4)[0], len(result))
        self.assertEqual(result[8:40], raw[8:40])
        self.assertEqual(result[56:256], raw[56:256])

    def test_metadata_mismatch_or_wrong_platform_is_rejected(self):
        raw, sf = self.template()
        sf.objects[2].byte_size_offset = (184, 4)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            repack_serialized(raw, sf, {2: b'converted'})
        raw, sf = self.template()
        sf.target_platform = 10
        with self.assertRaisesRegex(ValueError, 'PC template required'):
            repack_serialized(raw, sf, {2: b'converted'})


class VorbisGranuleTest(unittest.TestCase):
    @staticmethod
    def page(granule, flags=4, serial=7, payload=b'vorbis'):
        return (b'OggS\0' + bytes([flags]) + struct.pack('<qIII', granule, serial, 0, 0)
                + bytes([1, len(payload)]) + payload)

    def test_eos_count_is_read_from_page_boundaries_not_payload(self):
        data = self.page(0, flags=2, payload=b'OggS\0not-a-page') + self.page(35712)
        self.assertEqual(ogg_frames(data), 35712)
        for invalid in (data[:-1], data + b'garbage', self.page(3, flags=0),
                        self.page(3) + self.page(4), self.page(0, flags=2) + self.page(4, serial=8),
                        self.page(4, flags=0) + self.page(3)):
            with self.assertRaises(ValueError):
                ogg_frames(invalid)

    @patch('tools.port_legacy_media.ffmpeg')
    @patch('tools.port_legacy_media.pcm')
    def test_short_clip_padding_is_excluded_but_signal_changes_fail(self, mocked_pcm, mocked_ffmpeg):
        samples = struct.pack('<' + 'h' * 100, *range(100))
        mocked_ffmpeg.return_value = self.page(100)
        mocked_pcm.side_effect = [(samples, 48000, 1), (samples + bytes(1920), 48000, 1)]
        _, proof = transcode(Path('ffmpeg'), b'source')
        self.assertEqual(proof['output_samples'], 100)
        self.assertEqual(proof['ffmpeg_padding_samples'], 960)
        mocked_pcm.side_effect = [(samples, 48000, 1), (bytes(len(samples)) + bytes(1920), 48000, 1)]
        with self.assertRaisesRegex(ValueError, 'SNR'):
            transcode(Path('ffmpeg'), b'source')

    @patch('tools.port_legacy_media.ffmpeg')
    @patch('tools.port_legacy_media.pcm')
    def test_real_silent_placeholder_requires_explicit_opt_in(self, mocked_pcm, mocked_ffmpeg):
        mocked_ffmpeg.return_value = self.page(100)
        mocked_pcm.side_effect = [(bytes(200), 48000, 1)] * 6
        with self.assertRaisesRegex(ValueError, 'source is silent'):
            transcode(Path('ffmpeg'), b'source')
        _, proof = transcode(Path('ffmpeg'), b'source', allow_silent=True)
        self.assertTrue(proof['source_silent'])
        self.assertIsNone(proof['decoded_snr_db'])
        self.assertEqual(proof['output_samples'], 100)
