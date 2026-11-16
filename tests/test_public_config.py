import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import check_public_config as check


class PublicConfigTest(unittest.TestCase):
    def stage(self, folder, name, content):
        path = folder / name
        path.write_text(content, encoding='utf-8')
        subprocess.run(['git', 'add', '--', name], cwd=folder, check=True, capture_output=True)

    def run_check(self, folder):
        out = io.StringIO()
        with mock.patch.object(check, 'ROOT', folder), mock.patch('sys.argv', ['check', '--staged']), contextlib.redirect_stdout(out):
            code = check.main()
        return code, out.getvalue()

    def test_staged_address_cannot_be_hidden_by_working_copy(self):
        address = '.'.join(['8'] * 4)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
            self.stage(folder, 'config.txt', 'host=' + address)
            (folder / 'config.txt').write_text('host=<server>', encoding='utf-8')
            code, output = self.run_check(folder)
            self.assertEqual(code, 1)
            self.assertIn('public IPv4 literal', output)
            self.assertNotIn(address, output)

    def test_private_artifact_and_credential_are_rejected_without_values(self):
        credential = 'ghp_' + 'synthetic' * 5
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
            self.stage(folder, 'connection.local.json', '{}')
            self.stage(folder, 'notes.txt', credential)
            code, output = self.run_check(folder)
            self.assertEqual(code, 1)
            self.assertIn('private configuration', output)
            self.assertIn('credential material', output)
            self.assertNotIn(credential, output)

    def test_protocol_examples_and_versions_remain_allowed(self):
        content = b'loopback=127.0.0.1 lan=192.168.1.2 example=192.0.2.1 version=9.1.0.7988'
        self.assertEqual(check.inspect('.env.example', content), [])
        self.assertEqual(check.inspect('asset.png', b'\xff\xfe\x00'), [])


if __name__ == '__main__':
    unittest.main()
