import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.audit_legacy_media import port_one, verified_output
from tools.port_legacy_media import digest


class BatchResumeTest(unittest.TestCase):
    def test_missing_output_is_retried_without_aborting_entire_resume(self):
        self.assertFalse(verified_output(dict(status='converted', output='no-such-oni69-output', output_sha256='x')))

    @patch('tools.audit_legacy_media.convert')
    def test_uncheckpointed_output_reuses_exact_bytes_and_refuses_different_bytes(self, mocked):
        with tempfile.TemporaryDirectory() as folder:
            item = dict(id='id', family='PS3', kind='AudioClip', platform=10, source='source',
                        name='vse', member=None, path_id=2, object_sha256='source-hash')
            options = dict(audio_template='template', ffmpeg='ffmpeg', output_root=folder)
            mocked.return_value = (b'converted', dict(kind='AudioClip', source_platform=10,
                output_sha256=digest(b'converted')))
            first = port_one(item, options)
            self.assertEqual(first['status'], 'converted')
            self.assertEqual(port_one(item, options)['status'], 'converted')
            Path(first['output']).write_bytes(b'different')
            self.assertIn('existing output differs', port_one(item, options)['error'])
            self.assertEqual(Path(first['output']).read_bytes(), b'different')
            self.assertEqual(mocked.call_args.kwargs['expected_object_sha256'], 'source-hash')
