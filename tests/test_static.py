"""PC Web and AssetBundle static-routing tests."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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
        (self.bundles / "globalAssets.unity3d").write_bytes(b"global")
        (self.bundles / "scene" / "deep").mkdir(parents=True)
        (self.bundles / "scene" / "deep" / "deep.unity3d").write_bytes(b"deep")
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
        assets2 = self.static.resolve("/client/pc/jp/assets2/building/abc.unity3d")
        deep = self.static.resolve("/client/pc/jp/assets/scene/deep/deep.unity3d")
        global_asset = self.static.resolve("/client/pc/jp/assets/globalAssets.unity3d")
        root_global_asset = self.static.resolve("/client/pc/jp/globalAssets.unity3d")
        self.assertEqual(direct.path.name, "abc.unity3d")
        self.assertEqual(cached.path.name, "mission__def.unity3d")
        self.assertEqual(assets2.path.name, "abc.unity3d")
        self.assertEqual(deep.path.name, "deep.unity3d")
        self.assertEqual(global_asset.path.name, "globalAssets.unity3d")
        self.assertEqual(root_global_asset.path.name, "globalAssets.unity3d")

    def test_webplayer_homepage_is_served_from_root(self):
        for target in ("/", "/app.html", "/client/app.html"):
            with self.subTest(target=target):
                resource = self.static.resolve(target)
                self.assertEqual(resource.path.name, "app.html")

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

    def test_size_does_not_require_a_second_stat(self):
        resource = self.static.resolve("/client/app.html")
        (self.web / "client" / "app.html").unlink()
        self.assertEqual(resource.size, len("<html>ok</html>"))


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
                    last_modified = response.headers["Last-Modified"]

                with urlopen(Request(f"{base}/client/app.html", method="HEAD"), timeout=5) as response:
                    self.assertEqual(response.read(), b"")
                    self.assertEqual(response.headers["Content-Length"], "6")

                with urlopen(
                    Request(
                        f"{base}/client/app.html",
                        headers={"Range": "bytes=1-3"},
                    ),
                    timeout=5,
                ) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), b"erv")

                with self.assertRaises(HTTPError) as caught:
                    urlopen(
                        Request(
                            f"{base}/client/app.html",
                            headers={"If-Modified-Since": last_modified},
                        ),
                        timeout=5,
                    )
                try:
                    self.assertEqual(caught.exception.code, 304)
                    self.assertEqual(caught.exception.read(), b"")
                finally:
                    caught.exception.close()

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
