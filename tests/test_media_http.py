import hashlib
import io
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools.media_http import verify_url


class MediaHttpRetryTest(unittest.TestCase):
    def setUp(self):
        local_patch = patch('tools.media_http._thread_http', threading.local())
        local_patch.start()
        self.addCleanup(local_patch.stop)

    @patch('tools.media_http.build_opener')
    def test_successive_urls_reuse_one_opener_per_worker(self, make_opener):
        def response(*args, **kwargs):
            stream = io.BytesIO(b'ok'); stream.status = 200; stream.length = 0
            return stream
        make_opener.return_value.open.side_effect = response
        expected = hashlib.sha256(b'ok').hexdigest()
        verify_url('http://owned/a', expected)
        verify_url('http://owned/b', expected)
        self.assertEqual(make_opener.call_count, 1)
    @patch('tools.media_http.time.sleep')
    @patch('tools.media_http.build_opener')
    def test_temporary_gateway_error_retries_but_records_it(self, opener, sleep):
        response = io.BytesIO(b'verified'); response.status = 200; response.length = 0
        opener.return_value.open.side_effect = [HTTPError('url', 502, 'gateway', {}, None), response]
        self.assertEqual(verify_url('http://owned/asset', hashlib.sha256(b'verified').hexdigest()), 1)
        self.assertEqual(opener.return_value.open.call_count, 2)

    @patch('tools.media_http.time.sleep')
    @patch('tools.media_http.build_opener')
    def test_hash_mismatch_and_permanent_404_are_never_retried(self, opener, sleep):
        response = io.BytesIO(b'wrong'); response.status = 200; response.length = 0
        opener.return_value.open.return_value = response
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify_url('http://owned/asset', hashlib.sha256(b'correct').hexdigest())
        self.assertEqual(opener.return_value.open.call_count, 1)
        sleep.assert_not_called()
        opener.return_value.open.reset_mock()
        opener.return_value.open.side_effect = HTTPError('url', 404, 'missing', {}, None)
        with self.assertRaises(HTTPError):
            verify_url('http://owned/asset', 'unused')
        self.assertEqual(opener.return_value.open.call_count, 1)
