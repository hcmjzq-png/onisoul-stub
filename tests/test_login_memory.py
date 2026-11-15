import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from tools.login_memory import handler_for, ORIGIN


@unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
class LoginMemoryTest(unittest.TestCase):
    def test_encrypted_persistence_restart_origin_checks_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.dpapi"
            def start():
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(path))
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                return server, worker
            def stop(server, worker):
                server.shutdown(); server.server_close(); worker.join(5)
            def request(server, method, value=None, origin=ORIGIN):
                con = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    con.request(method, "/credentials", None if value is None else json.dumps(value),
                        {"Origin": origin, "X-Oni-Login": "1", "Content-Type": "application/json"})
                    r = con.getresponse(); return r.status, json.loads(r.read())
                finally:
                    con.close()
            server, worker = start()
            try:
                value = {"a": "模拟账号", "p": "only-synthetic-credentials"}
                self.assertEqual(request(server, "POST", value)[0], 200)
                before = path.read_bytes()
                self.assertNotIn(value["p"].encode(), before)
                self.assertEqual(request(server, "POST", {}, origin="http://untrusted.example")[0], 403)
                self.assertEqual(request(server, "GET", origin="http://untrusted.example")[0], 403)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(request(server, "POST", {"a": 123})[0], 400)
            finally:
                stop(server, worker)
            server, worker = start()
            try:
                self.assertEqual(request(server, "GET"), (200, value))
                self.assertEqual(request(server, "POST", {})[0], 200)
                self.assertFalse(path.exists())
                self.assertEqual(request(server, "GET"), (200, {}))
            finally:
                stop(server, worker)
