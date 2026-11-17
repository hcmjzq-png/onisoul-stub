import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import publish_country_backgrounds as publish


class BackgroundPublicationTest(unittest.TestCase):
    def update_fixture(self, root):
        release, assets, backups, plan, golden = self.fixture(root)
        baseline = root / 'baseline.json'
        baseline.write_text(json.dumps(plan))
        row = plan['files'][0]
        original = (release / row['relative']).read_bytes()
        (assets / row['relative']).write_bytes(original)
        replacement = original + b'-v2'
        (release / row['relative']).write_bytes(replacement)
        row.update(bytes=len(replacement), sha256=hashlib.sha256(replacement).hexdigest())
        row['proof']['archive'] = 'CustomAssetBundle-' + hashlib.md5(replacement).hexdigest()
        (release / 'manifest.json').write_text(json.dumps(plan))
        return release, assets, backups, plan, golden, baseline, original

    def fixture(self, root):
        release, assets, backups = (root / name for name in ('release', 'assets', 'backups'))
        files = []
        original_hash = ''
        for i in range(1, 48):
            country, name = f'country{i:02d}', f'pbm{i:02d}_01'
            blob = ('fixture-' + country).encode()
            digest = hashlib.sha256(blob).hexdigest()
            relative = 'bundles/pbm/' + hashlib.md5(name.encode('utf-16le')).hexdigest() + '.unity3d'
            path = release / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            original = i == 37
            proof = dict(original_preserved=True) if original else dict(
                non_texture_objects_preserved=True, archive='CustomAssetBundle-' + hashlib.md5(blob).hexdigest(), source_sha256=digest)
            files.append(dict(country=country, logical_name=name, relative=relative,
                url='/client/pc/jp/assets/' + relative.removeprefix('bundles/'), sha256=digest, bytes=len(blob),
                provenance='original_pc_preserved' if original else 'synthetic_imagegen_shared_original_model', proof=proof))
            if original:
                original_hash = digest
                target = assets / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(blob)
        (assets / 'unrelated.bin').write_bytes(b'keep')
        plan = dict(original_template_sha256=original_hash, generated_art_is_not_original_recovery=True, files=files)
        (release / 'manifest.json').write_text(json.dumps(plan))
        return release, assets, backups, plan, original_hash

    def test_incomplete_release_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden = self.fixture(Path(folder))
            plan['files'].pop()
            (release / 'manifest.json').write_text(json.dumps(plan))
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaises(ValueError):
                publish.install(release, assets, backups)
            self.assertFalse(backups.exists())
            self.assertEqual(len(list(assets.rglob('*.unity3d'))), 1)

    def test_tampered_input_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden = self.fixture(Path(folder))
            (release / plan['files'][-1]['relative']).write_bytes(b'changed')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaises(ValueError):
                publish.install(release, assets, backups)
            self.assertFalse(backups.exists())

    def test_complete_release_preserves_original_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden = self.fixture(Path(folder))
            checked = []
            with patch.object(publish, 'TEMPLATE_SHA256', golden):
                result = publish.install(release, assets, backups, verify_http=lambda r: checked.append(r['country']))
                repeated = publish.install(release, assets, backups)
            self.assertEqual(result['installed'], 46)
            self.assertEqual(result['http_verified'], 47)
            self.assertEqual(len(checked), 47)
            self.assertEqual(repeated['installed'], 0)
            self.assertEqual((assets / 'unrelated.bin').read_bytes(), b'keep')
            self.assertEqual(publish.sha(assets / plan['files'][36]['relative']), golden)

    def test_existing_different_background_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden = self.fixture(Path(folder))
            target = assets / plan['files'][0]['relative']
            target.write_bytes(b'existing-different')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaisesRegex(ValueError, 'refusing replacement'):
                publish.install(release, assets, backups)
            self.assertEqual(target.read_bytes(), b'existing-different')
            self.assertFalse(backups.exists())

    def test_failed_http_check_rolls_back_only_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden = self.fixture(Path(folder))
            def fail(row):
                raise ValueError('HTTP failure')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaisesRegex(ValueError, 'HTTP failure'):
                publish.install(release, assets, backups, verify_http=fail)
            self.assertEqual(len(list(assets.rglob('*.unity3d'))), 1)
            self.assertEqual((assets / 'unrelated.bin').read_bytes(), b'keep')
            self.assertEqual(publish.sha(assets / plan['files'][36]['relative']), golden)

    def test_explicit_baseline_updates_only_matching_synthetic_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden, baseline, original = self.update_fixture(Path(folder))
            with patch.object(publish, 'TEMPLATE_SHA256', golden):
                result = publish.install(release, assets, backups, baseline=baseline)
            self.assertEqual(result['updated'], 1)
            self.assertEqual(result['installed'], 45)
            self.assertEqual(publish.sha(assets / plan['files'][0]['relative']), plan['files'][0]['sha256'])
            self.assertEqual((Path(result['backup']) / 'previous' / plan['files'][0]['relative']).read_bytes(), original)
            self.assertEqual((assets / 'unrelated.bin').read_bytes(), b'keep')

    def test_failed_update_restores_old_synthetic_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden, baseline, original = self.update_fixture(Path(folder))
            def fail(row):
                raise ValueError('HTTP failure')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaisesRegex(ValueError, 'HTTP failure'):
                publish.install(release, assets, backups, baseline=baseline, verify_http=fail)
            self.assertEqual(len(list(assets.rglob('*.unity3d'))), 2)
            self.assertEqual((assets / plan['files'][0]['relative']).read_bytes(), original)
            self.assertEqual((assets / 'unrelated.bin').read_bytes(), b'keep')

    def test_baseline_does_not_allow_unknown_existing_content(self):
        with tempfile.TemporaryDirectory() as folder:
            release, assets, backups, plan, golden, baseline, original = self.update_fixture(Path(folder))
            target = assets / plan['files'][0]['relative']
            target.write_bytes(b'unknown concurrent content')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaisesRegex(ValueError, 'refusing replacement'):
                publish.install(release, assets, backups, baseline=baseline)
            self.assertFalse(backups.exists())
            self.assertEqual(target.read_bytes(), b'unknown concurrent content')
            with patch.object(publish, 'TEMPLATE_SHA256', golden), self.assertRaises(ValueError):
                publish.install(release, assets, None, baseline=baseline, retain_backup=False)
            self.assertFalse(list(Path(folder).glob('.background47-*')))

    def test_ephemeral_recovery_is_removed_after_success_and_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                release, assets, backups, plan, golden, baseline, original = self.update_fixture(root)
                def verify(row):
                    if fail:
                        raise ValueError('HTTP failure')
                with patch.object(publish, 'TEMPLATE_SHA256', golden):
                    if fail:
                        with self.assertRaisesRegex(ValueError, 'HTTP failure'):
                            publish.install(release, assets, None, baseline=baseline, verify_http=verify, retain_backup=False)
                        self.assertEqual((assets / plan['files'][0]['relative']).read_bytes(), original)
                        self.assertEqual(len(list(assets.rglob('*.unity3d'))), 2)
                    else:
                        result = publish.install(release, assets, None, baseline=baseline, verify_http=verify, retain_backup=False)
                        self.assertIsNone(result['backup'])
                        self.assertFalse(result['persistent_backup'])
                self.assertFalse(backups.exists())
                self.assertFalse(list(root.glob('.background47-*')))
