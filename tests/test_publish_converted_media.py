import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.business.registry import Registry
from app.transport import http_server
from app.transport.static import StaticFiles
from tools.publish_converted_media import PREFIX, archive_relative, canonical_voice, install
from tools.probe_legacy_media import ENGINE_SHA256


class AdditivePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundles = self.root / 'bundles'
        self.cache = self.root / 'cache'
        self.bundles.mkdir(); self.cache.mkdir()
        self.rows = []
        self.blobs = {}
        for identity, kind, name in [('a', 'AudioClip', 'vse001_1_010101_01_01'),
                                     ('b', 'AudioClip', 'vse002_1_010101_01_01'),
                                     ('c', 'Texture2D', 'building00273')]:
            blob = ('converted-' + identity).encode()
            row = dict(id=identity * 64, family='PS3', source_platform=10, kind=kind, name=name,
                       bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(), member=f'blobs/{identity * 64}.unity3d')
            row.update(relative=archive_relative(row), canonical=canonical_voice(row))
            self.rows.append(row); self.blobs[row['member']] = blob
        self.original = self.cache / Path(self.rows[0]['canonical']).name
        self.original.write_bytes(b'original-PC-from-cache')
        self.building = self.bundles / 'building' / 'existing.unity3d'
        self.building.parent.mkdir(); self.building.write_bytes(b'original-PC-prefab')
        movie = b'movie'
        self.blobs['movie.mpg'] = movie
        self.plan = dict(schema=1, prefix=PREFIX, engine_sha256=ENGINE_SHA256, files=self.rows,
            movie=dict(relative=PREFIX + '/movie/movie.mpg', member='movie.mpg', bytes=len(movie),
                       sha256=hashlib.sha256(movie).hexdigest()))
        self.server = http_server.serve('127.0.0.1', 0, Registry(), StaticFiles(self.root / 'web', self.bundles, self.cache))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def args(self):
        archive = self.root / 'upload.tar'
        with tarfile.open(archive, 'w') as stream:
            data = json.dumps(self.plan).encode()
            info = tarfile.TarInfo('manifest.json'); info.size = len(data); stream.addfile(info, io.BytesIO(data))
            for name, data in self.blobs.items():
                info = tarfile.TarInfo(name); info.size = len(data); stream.addfile(info, io.BytesIO(data))
        return argparse.Namespace(archive=archive, bundle_root=self.bundles, cache_root=self.cache,
            backup_root=self.root / 'backup', result=self.root / 'result.json',
            http_host='127.0.0.1', http_port=self.server.server_address[1])

    def test_publish_preserves_cached_original_and_never_promotes_texture_as_prefab(self):
        install(self.args())
        result = json.loads((self.root / 'result.json').read_text())
        self.assertEqual(result['canonical_voice_added'], 1)
        self.assertEqual(result['canonical_existing_preserved'], 1)
        self.assertEqual(self.original.read_bytes(), b'original-PC-from-cache')
        self.assertFalse((self.bundles / self.rows[0]['canonical']).exists())
        self.assertEqual(self.building.read_bytes(), b'original-PC-prefab')
        self.assertEqual((self.bundles / self.rows[1]['canonical']).read_bytes(), b'converted-b')
        self.assertTrue((self.bundles / self.rows[2]['relative']).exists())
        self.assertIsNone(self.rows[2]['canonical'])

    def test_http_failure_rolls_back_only_this_publish_and_keeps_originals(self):
        with patch('tools.publish_converted_media.verify_url', side_effect=OSError('HTTP unavailable')):
            with self.assertRaises(OSError):
                install(self.args())
        self.assertEqual(self.original.read_bytes(), b'original-PC-from-cache')
        self.assertEqual(self.building.read_bytes(), b'original-PC-prefab')
        self.assertEqual([p for p in self.bundles.rglob('*') if p.is_file()], [self.building])

    def test_manifest_cannot_redirect_texture_to_original_building_path(self):
        self.rows[2]['canonical'] = 'building/existing.unity3d'
        with self.assertRaisesRegex(ValueError, 'resource type'):
            install(self.args())
        self.assertEqual(self.building.read_bytes(), b'original-PC-prefab')
