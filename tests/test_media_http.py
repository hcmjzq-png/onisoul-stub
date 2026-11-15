import hashlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools.media_http import verify_url


class MediaHttpRetryTest(unittest.TestCase):
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
