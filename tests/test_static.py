"""PC Web and AssetBundle static-routing tests."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from app.business.registry import Registry
from app.transport import http_server
from app.transport.static import NO_STORE, StaticFiles, StaticPathError


class StaticFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.web = root / "web"
        self.bundles = root / "bundles"
        self.cache = root / "cache"
        for directory in (self.web / "client", self.bundles, self.cache):
            directory.mkdir(parents=True)
        (self.web / "client" / "app.html").write_text("<html>ok</html>", encoding="utf-8")
        (self.bundles / "building").mkdir()
        (self.bundles / "building" / "abc.unity3d").write_bytes(b"unity")
        (self.cache / "mission__def.unity3d").write_bytes(b"cache")
        self.static = StaticFiles(self.web, self.bundles, self.cache)

    def tearDown(self):
        self.temp.cleanup()

    def test_pc_web_asset_is_no_store(self):
        resource = self.static.resolve("/client/app.html?cache=1")
        self.assertIsNotNone(resource)
        self.assertEqual(resource.path.read_text(encoding="utf-8"), "<html>ok</html>")
        self.assertEqual(resource.content_type, "text/html")
        self.assertEqual(resource.cache_control, NO_STORE)

    def test_bundle_and_cache_fallbacks(self):
        direct = self.static.resolve("/client/pc/jp/assets/building/abc.unity3d?r=1")
        cached = self.static.resolve("/client/pc/jp/assets/mission/def.unity3d")
        self.assertEqual(direct.path.name, "abc.unity3d")
        self.assertEqual(cached.path.name, "mission__def.unity3d")

    def test_crossdomain_is_generated_when_absent(self):
        resource = self.static.resolve("/crossdomain.xml")
        self.assertIn(b"<cross-domain-policy>", resource.body)
        self.assertEqual(resource.cache_control, NO_STORE)

    def test_path_traversal_is_rejected(self):
        for target in (
            "/client/../secret.txt",
            "/client/%2e%2e/secret.txt",
            "/client/%2e%2e%5csecret.txt",
        ):
            with self.subTest(target=target):
                with self.assertRaises(StaticPathError):
                    self.static.resolve(target)

    def test_missing_asset_is_not_a_path_error(self):
        self.assertIsNone(
            self.static.resolve("/client/pc/jp/assets/building/not-found.unity3d")
        )


class StaticHttpTest(unittest.TestCase):
    def test_http_get_serves_static_file_and_404_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = root / "web"
            (web / "client").mkdir(parents=True)
            (web / "client" / "app.html").write_text("served", encoding="utf-8")
            static = StaticFiles(web, root / "bundles", root / "cache")
            server = http_server.serve("127.0.0.1", 0, Registry(), static)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/client/app.html", timeout=5) as response:
                    self.assertEqual(response.read(), b"served")
                    self.assertEqual(response.headers["Cache-Control"], NO_STORE)

                with self.assertRaises(HTTPError) as caught:
                    urlopen(f"{base}/client/pc/jp/assets/scene/missing.unity3d", timeout=5)
                try:
                    self.assertEqual(caught.exception.code, 404)
                    body = json.loads(caught.exception.read())
                    self.assertEqual(body["message"], "stub has no assets")
                finally:
                    caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
