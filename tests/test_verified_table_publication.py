"""Publication validates all bytes before mutation and preserves other assets."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import publish_verified_tables as publication


class VerifiedPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name) / 'tables'
        self.dest.mkdir()
        self.payloads = {name + '.json': json.dumps({name: {'one': {'value': 7}}}).encode()
                         for name in ('alpha', 'beta')}
        container = bytearray()
        rows = []
        for name, raw in self.payloads.items():
            encoded = name.encode()
            container.extend(struct.pack('<I', len(encoded)) + encoded)
            container.extend(b'\0' * (-len(container) % 4))
            container.extend(struct.pack('<I', len(raw)))
            rows.append({'name': Path(name).stem, 'length': len(raw), 'rows': 1,
                         'sha256': hashlib.sha256(raw).hexdigest(), 'offset': len(container)})
            container.extend(raw)
            container.extend(b'\0' * (-len(container) % 4))
        self.container = bytes(container)
        self.proof = {'container_sha256': hashlib.sha256(self.container).hexdigest(), 'tables': rows}
        self.old = b'{"schema":1,"note":"preserve","tables":[{"file":"unrelated.json","sha256":"abc"}]}'
        (self.dest / 'import-manifest.json').write_bytes(self.old)
        (self.dest / 'unrelated.json').write_bytes(b'untouched')

    def test_container_name_offsets_hash_and_rows_are_verified(self):
        self.assertEqual(publication.from_container(self.container, self.proof), self.payloads)
        with self.assertRaisesRegex(ValueError, 'container hash'):
            publication.from_container(self.container + b'x', self.proof)
        self.proof['tables'][0]['offset'] += 1
        with self.assertRaisesRegex(ValueError, 'offset mismatch'):
            publication.from_container(self.container, self.proof)

    def test_install_preserves_other_records_and_is_idempotent(self):
        result = publication.install(self.payloads, self.dest, self.proof)
        self.assertEqual(result['created'], 2)
        manifest = (self.dest / 'import-manifest.json').read_bytes()
        self.assertEqual(json.loads(manifest)['note'], 'preserve')
        self.assertEqual(json.loads(manifest)['tables'][0], {'file': 'unrelated.json', 'sha256': 'abc'})
        self.assertEqual(publication.install(self.payloads, self.dest, self.proof)['created'], 0)
        self.assertEqual((self.dest / 'import-manifest.json').read_bytes(), manifest)
        self.assertEqual((self.dest / 'unrelated.json').read_bytes(), b'untouched')

    def test_corrupt_later_source_and_destination_do_not_partially_install(self):
        corrupted = {**self.payloads, 'beta.json': b'bad'}
        with self.assertRaisesRegex(ValueError, 'byte/hash mismatch'):
            publication.install(corrupted, self.dest, self.proof)
        self.assertFalse((self.dest / 'alpha.json').exists())
        (self.dest / 'beta.json').write_bytes(b'existing other version')
        with self.assertRaisesRegex(ValueError, 'conflicting destination'):
            publication.install(self.payloads, self.dest, self.proof)
        self.assertFalse((self.dest / 'alpha.json').exists())
        self.assertEqual((self.dest / 'import-manifest.json').read_bytes(), self.old)

    def test_manifest_write_failure_rolls_back_only_created_files(self):
        (self.dest / 'alpha.json').write_bytes(self.payloads['alpha.json'])
        write = publication.atomic_write
        def fail_manifest(path, raw):
            if path.name == 'import-manifest.json':
                raise OSError('disk full')
            write(path, raw)
        with patch.object(publication, 'atomic_write', side_effect=fail_manifest):
            with self.assertRaises(OSError):
                publication.install(self.payloads, self.dest, self.proof)
        self.assertEqual((self.dest / 'alpha.json').read_bytes(), self.payloads['alpha.json'])
        self.assertFalse((self.dest / 'beta.json').exists())
        self.assertEqual((self.dest / 'import-manifest.json').read_bytes(), self.old)

    def test_invalid_existing_manifest_is_not_discarded(self):
        bad = b'{"schema":1,"tables":[{},{}]}'
        (self.dest / 'import-manifest.json').write_bytes(bad)
        with self.assertRaisesRegex(ValueError, 'invalid existing import'):
            publication.install(self.payloads, self.dest, self.proof)
        self.assertEqual((self.dest / 'import-manifest.json').read_bytes(), bad)
        self.assertFalse((self.dest / 'alpha.json').exists())


if __name__ == '__main__':
    unittest.main()
