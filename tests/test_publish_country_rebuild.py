import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.publish_country_rebuild import install, snapshot


class CountryRebuildPublishTest(unittest.TestCase):
    def fixture(self, root):
        release, assets, backups = root / 'release', root / 'assets', root / 'backups'
        rows = []
        for i in range(1, 48):
            image = f'chara1_{i:05d}_01'
            relative = 'bundles/chara/' + hashlib.md5(image.encode('utf-16le')).hexdigest() + '.unity3d'
            data = f'country {i}'.encode()
            rebuilt = i > 20
            path = (release if rebuilt else assets) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            rows.append(dict(country=f'country{i:02d}', image=image, relative=relative,
                             sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                             archive=f'CustomAssetBundle-{i:032x}', reconstructed=rebuilt))
        (assets / 'other-original').write_bytes(b'keep')
        (release / 'manifest.json').write_text(json.dumps(dict(files=rows)))
        return release, assets, backups, rows

    def test_additive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, rows = self.fixture(Path(temp))
            before = snapshot(assets)
            result = install(release, assets, backups)
            self.assertEqual(result['installed'], 27)
            self.assertEqual(result['pre_existing_files_preserved'], 21)
            self.assertTrue(all(snapshot(assets)[k] == v for k, v in before.items()))
            self.assertEqual(install(release, assets, backups)['installed'], 0)

    def test_unknown_existing_country_or_original_aborts_before_changes(self):
        for index in (0, 46):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temp:
                release, assets, backups, rows = self.fixture(Path(temp))
                (assets / rows[index]['relative']).write_bytes(b'existing PC bytes')
                before = snapshot(assets)
                with self.assertRaisesRegex(ValueError, 'refusing replacement'):
                    install(release, assets, backups)
                self.assertEqual(snapshot(assets), before)
                self.assertFalse(backups.exists())

    def test_interruption_rolls_back_only_new_files(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, rows = self.fixture(Path(temp))
            before, link, count = snapshot(assets), os.link, 0
            def interrupted(*args):
                nonlocal count
                count += 1
                if count == 5:
                    raise OSError('interrupted')
                return link(*args)
            with patch('tools.publish_country_rebuild.os.link', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    install(release, assets, backups)
            self.assertEqual(snapshot(assets), before)

    def test_concurrent_create_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, rows = self.fixture(Path(temp))
            link, count = os.link, 0
            def race(source, target):
                nonlocal count
                count += 1
                if count == 3:
                    target.write_bytes(b'concurrent PC bytes')
                return link(source, target)
            with patch('tools.publish_country_rebuild.os.link', side_effect=race):
                with self.assertRaisesRegex(ValueError, 'concurrent country change'):
                    install(release, assets, backups)
            self.assertEqual((assets / rows[22]['relative']).read_bytes(), b'concurrent PC bytes')
            self.assertFalse((assets / rows[20]['relative']).exists())

    def test_corrupt_upload_and_path_escape_refused(self):
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                release, assets, backups, rows = self.fixture(Path(temp))
                if corrupt:
                    (release / rows[-1]['relative']).write_bytes(b'truncated')
                else:
                    rows[-1]['relative'] = '../escape'
                    (release / 'manifest.json').write_text(json.dumps(dict(files=rows)))
                before = snapshot(assets)
                with self.assertRaises(ValueError):
                    install(release, assets, backups)
                self.assertEqual(snapshot(assets), before)


if __name__ == '__main__':
    unittest.main()
