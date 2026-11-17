"""Environment markers must separate profiles without changing game protocols/layout."""
from __future__ import annotations

import json
import http.client
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import environment
from app.business.registry import Registry
from app.transport import http_server
from app.transport.static import StaticFiles


class EnvironmentIdentityTest(unittest.TestCase):
    def test_unconfigured_keeps_original_content_and_status(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(environment.identity(), {})
            self.assertEqual(environment.mark_html(b'<title>game</title>'), b'<title>game</title>')

    def test_invalid_or_incomplete_identity_is_rejected(self):
        for values in ({'ONI_ENVIRONMENT': 'typo'}, {'ONI_ENVIRONMENT': 'local-test'},
                       {'ONI_ENVIRONMENT': 'cloud', 'ONI_INSTANCE_ID': 'valid-instance', 'ONI_BUILD_ID': '<script>'}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError):
                environment.identity()

    def test_http_identity_and_visible_label_preserve_canvas_size(self):
        values = dict(ONI_ENVIRONMENT='local-test', ONI_INSTANCE_ID='local-unit-test', ONI_BUILD_ID='unit-build')
        with patch.dict(os.environ, values, clear=True), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'client').mkdir()
            original = '<title>game</title><p class="header"><span>game</span></p><embed width="1280" height="720">'
            path = root / 'client/app.html'
            path.write_text(original, encoding='utf-8')
            server = http_server.serve('127.0.0.1', 0, Registry(), static_files=StaticFiles(root, root, root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/client/status')
                response = connection.getresponse()
                status = json.loads(response.read())
                self.assertEqual(response.headers['X-OniSoul-Environment'], 'local-test')
                connection.close()
                self.assertEqual(status['instance_id'], 'local-unit-test')
                self.assertEqual(status['build_id'], 'unit-build')
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/client/app.html')
                response = connection.getresponse()
                body = response.read().decode('utf-8')
                connection.close()
                self.assertIn('本地测试服', body)
                self.assertIn('<embed width="1280" height="720">', body)
                self.assertEqual(path.read_text(encoding='utf-8'), original)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_local_login_memory_is_separate_from_cloud(self):
        source = b'<title>login</title>http://127.0.0.1:19765/credentials'
        base = dict(ONI_INSTANCE_ID='test-identity', ONI_BUILD_ID='unit-build')
        with patch.dict(os.environ, {**base, 'ONI_ENVIRONMENT': 'local-test'}, clear=True):
            self.assertIn(b':19766/credentials', environment.mark_html(source))
        with patch.dict(os.environ, {**base, 'ONI_ENVIRONMENT': 'cloud'}, clear=True):
            self.assertIn(b':19765/credentials', environment.mark_html(source))
