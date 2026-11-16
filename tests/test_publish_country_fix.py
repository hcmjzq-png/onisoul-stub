import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.publish_country_fix import install


class CountryPublishTest(unittest.TestCase):
    def fixture(self, folder):
        release, assets, backups = folder/'release', folder/'assets', folder/'backups'
        rows = []
        for i in range(20):
            rel = f'bundles/chara/{i:032x}.unity3d'
            before = f'original {i}'.encode()
            after = f'fixed {i}'.encode() if i < 18 else before
            for root, data in [(release, after), (assets, before)]:
                path = root/rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            rows.append(dict(relative=rel, before_sha256=hashlib.sha256(before).hexdigest(), sha256=hashlib.sha256(after).hexdigest()))
        rel = 'web/client/app.unity3d'
        for root, data in [(release, b'fixed app'), (assets, b'original app')]:
            (root/rel).parent.mkdir(parents=True)
            (root/rel).write_bytes(data)
        plan = dict(files=rows, app_relative=rel, original_app_sha256=hashlib.sha256(b'original app').hexdigest(), app_sha256=hashlib.sha256(b'fixed app').hexdigest())
        (release/'manifest.json').write_text(json.dumps(plan))
        return release, assets, backups, plan

    def test_exact_backups_and_unrelated_files_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, plan = self.fixture(Path(temp))
            (assets/'unrelated').write_bytes(b'keep me')
            result = install(release, assets, backups)
            self.assertEqual(result['installed'], 19)
            self.assertEqual((assets/'unrelated').read_bytes(), b'keep me')
            self.assertEqual((Path(result['backup'])/plan['app_relative']).read_bytes(), b'original app')
            self.assertEqual((assets/plan['app_relative']).read_bytes(), b'fixed app')

    def test_unknown_live_fingerprint_refuses_all_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, plan = self.fixture(Path(temp))
            (assets/plan['files'][-1]['relative']).write_bytes(b'changed elsewhere')
            with self.assertRaisesRegex(ValueError, 'fingerprint changed'):
                install(release, assets, backups)
            self.assertEqual((assets/plan['files'][0]['relative']).read_bytes(), b'original 0')
            self.assertFalse(backups.exists())

    def test_interrupted_replacement_rolls_back_installed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, plan = self.fixture(Path(temp))
            original_replace = os.replace
            count = 0
            def interrupted(*args):
                nonlocal count
                count += 1
                if count == 3:
                    raise OSError('simulated interrupted install')
                return original_replace(*args)
            with patch('tools.publish_country_fix.os.replace', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    install(release, assets, backups)
            for row in plan['files']:
                self.assertEqual(hashlib.sha256((assets/row['relative']).read_bytes()).hexdigest(), row['before_sha256'])
            self.assertEqual((assets/plan['app_relative']).read_bytes(), b'original app')
