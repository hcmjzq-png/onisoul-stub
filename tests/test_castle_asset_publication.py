"""Publication safety: originals, archive tampering, rollback, idempotency."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock
from unittest.mock import patch

from tools.publish_castle_assets import ENGINE_SHA256, expected_model, install_archive, read_archive, sha, verify_http


class CastleAssetPublicationTests(unittest.TestCase):
    def fixture(self, root: Path, *, corrupt=False):
        bundle_root = root / "bundles"
        (bundle_root / "building").mkdir(parents=True)
        files, blobs = [], {}
        counter = 1
        for tribe in ("human", "oni", "evil"):
            for grade in range(1, 6):
                logical = f"building{counter:05}"
                name = hashlib.md5(logical.encode("utf-16le")).hexdigest() + ".unity3d"
                blob = b"UnityWeb-test-payload-" + logical.encode()
                original = tribe == "human" and grade == 1
                record = {"tribe":tribe, "grade":grade, "model":expected_model(tribe, grade),
                          "logical":logical, "relative":"building/" + name, "bytes":len(blob),
                          "sha256":sha(blob), "action":"preserve" if original else "add",
                          "member":None if original else "blobs/" + name}
                files.append(record)
                if original:
                    (bundle_root / record["relative"]).write_bytes(blob)
                else:
                    blobs[record["member"]] = blob
                counter += 1
        unrelated = bundle_root / "building/unrelated.unity3d"
        unrelated.write_bytes(b"existing unrelated asset")
        if corrupt:
            first = next(iter(blobs))
            blobs[first] = b"X" + blobs[first][1:]
        archive = root / "release.tar"
        plan = {"schema":1, "engine_sha256":ENGINE_SHA256, "files":files}
        with tarfile.open(archive, "w") as target:
            for name, blob in {"manifest.json":json.dumps(plan).encode(), **blobs}.items():
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                target.addfile(info, io.BytesIO(blob))
        return archive, bundle_root, files

    def test_conflicting_existing_asset_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, bundles, files = self.fixture(root)
            conflict = bundles / files[1]["relative"]
            conflict.write_bytes(b"different existing original")
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                install_archive(archive, bundles, root / "backups", ["http://127.0.0.1"])
            self.assertEqual(conflict.read_bytes(), b"different existing original")
            self.assertFalse((root / "backups").exists())
            self.assertEqual(len(list((bundles / "building").iterdir())), 3)

    def test_tampered_archive_writes_no_assets_or_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, bundles, _ = self.fixture(root, corrupt=True)
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                install_archive(archive, bundles, root / "backups", ["http://127.0.0.1"])
            self.assertFalse((root / "backups").exists())
            self.assertEqual(len(list((bundles / "building").iterdir())), 2)

    def test_http_failure_removes_only_new_files_and_retains_original_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, bundles, files = self.fixture(root)
            original = (bundles / files[0]["relative"]).read_bytes()
            with patch("tools.publish_castle_assets.verify_http", side_effect=OSError("HTTP failure")):
                with self.assertRaisesRegex(OSError, "HTTP failure"):
                    install_archive(archive, bundles, root / "backups", ["http://127.0.0.1"])
            self.assertEqual(len(list((bundles / "building").iterdir())), 2)
            self.assertEqual((bundles / files[0]["relative"]).read_bytes(), original)
            backup = next((root / "backups").iterdir())
            self.assertEqual((backup / "originals" / files[0]["relative"]).read_bytes(), original)
            self.assertFalse(list(root.glob(".castle15-*")))

    def test_reinstall_is_idempotent_and_preserves_unrelated_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, bundles, _ = self.fixture(root)
            with patch("tools.publish_castle_assets.verify_http", return_value=[]):
                first = install_archive(archive, bundles, root / "backups", ["http://127.0.0.1"])
                second = install_archive(archive, bundles, root / "backups", ["http://127.0.0.1"])
            self.assertEqual(len(first["created"]), 14)
            self.assertEqual(second["created"], [])
            self.assertEqual(len(second["kept"]), 15)
            self.assertEqual((bundles / "building/unrelated.unity3d").read_bytes(), b"existing unrelated asset")
            self.assertFalse(list(root.glob(".castle15-*")))

    def test_connection_reset_retries_then_checks_all_castles_and_namespaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, _, _ = self.fixture(Path(temporary))
            plan, blobs = read_archive(archive)
            calls = []
            def request(req, timeout):
                calls.append(req.full_url)
                if len(calls) == 1:
                    raise ConnectionResetError("transient reset")
                row = next(r for r in plan["files"] if req.full_url.endswith(r["relative"]))
                data = b"UnityWeb-test-payload-" + row["logical"].encode()
                response = MagicMock()
                response.__enter__.return_value.status = 200
                response.__enter__.return_value.read.return_value = data
                return response
            with patch("tools.publish_castle_assets.urllib.request.urlopen", side_effect=request), patch("tools.publish_castle_assets.time.sleep") as sleep:
                checks = verify_http(plan, ["http://127.0.0.1"])
            self.assertEqual(len(checks), 30)
            self.assertEqual(len(calls), 31)
            sleep.assert_called_once()

    def test_missing_asset_http_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, _, _ = self.fixture(Path(temporary))
            plan, _ = read_archive(archive)
            error = urllib.error.HTTPError("http://127.0.0.1/missing", 404, "missing", {}, None)
            with patch("tools.publish_castle_assets.urllib.request.urlopen", side_effect=error) as request, patch("tools.publish_castle_assets.time.sleep") as sleep:
                with self.assertRaises(urllib.error.HTTPError):
                    verify_http(plan, ["http://127.0.0.1"])
            request.assert_called_once()
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
