import unittest

from tools.probe_legacy_media import validate_results


class NativeResultTest(unittest.TestCase):
    def test_equal_names_in_different_versions_match_by_id_not_completion_order(self):
        rows = [dict(id='a', name='same', kind='Texture2D', width=32, height=64),
                dict(id='b', name='same', kind='Texture2D', width=64, height=32)]
        events = [dict(result=dict(rows[1], loaded=True)), dict(result=dict(rows[0], loaded=True))]
        self.assertEqual(len(validate_results(rows, events)), 2)
        events[1]['result']['id'] = 'b'
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            validate_results(rows, events)

    def test_decoder_granule_and_channels_must_match(self):
        row = dict(id='a', name='clip', kind='AudioClip', sample_rate=48000, channels=1,
                   source_samples=35712, ogg_granule_samples=35712)
        result = dict(id='a', name='clip', kind='AudioClip', frequency=48000, channels=1,
                      samples=35712, loaded=True)
        validate_results([row], [dict(result=result)])
        result['samples'] += 960
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            validate_results([row], [dict(result=result)])
        with self.assertRaisesRegex(RuntimeError, 'verification failed'):
            validate_results([row], [dict(error='native named asset missing')])
