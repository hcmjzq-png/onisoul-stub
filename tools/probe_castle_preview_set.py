"""Render all staged castles in one isolated, original-engine QA process."""
from __future__ import annotations

import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from tools.probe_building_sample import ENGINE_SHA256


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main() -> None:
    import frida
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--qa-executable", type=Path, required=True)
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--port", type=int, default=19926)
    args = ap.parse_args()
    qa = args.qa_executable.resolve()
    if qa.parent.name != "qa-client":
        ap.error("isolated qa-client required")
    release = args.release.resolve()
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest["files"]) != 15:
        ap.error("exactly fifteen castles are required")
    if (release / "native-results.json").exists():
        ap.error("native result already exists; preserve the completed preview")
    expected_url = f"http://127.0.0.1:{args.port}/index.html"
    for config in (qa.parent / "config.ini", qa.parent / "Cantainer/config.ini"):
        text = config.read_text(encoding="utf-8-sig")
        if f"StartUrl={expected_url}" not in text or f"FinalUrl={expected_url}" not in text:
            raise ValueError("QA configuration does not point at the isolated static site")
    handler = partial(QuietHandler, directory=str(args.site.resolve()))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    pid, results = None, []
    try:
        pid = frida.spawn([str(qa)], cwd=str(qa.parent))
        frida.resume(pid)
        deadline = time.monotonic() + 40
        ready = False
        while time.monotonic() < deadline:
            session = frida.attach(pid)
            gate = session.create_script("""rpc.exports.paths=()=>{const engine=Process.findModuleByName('webplayer_win.dll'),mono=Process.findModuleByName('mono-1-vc.dll');let ready=false;if(mono){const loaded=new NativeFunction(mono.getExportByName('mono_image_loaded'),'pointer',['pointer']);ready=!loaded(Memory.allocUtf8String('UnityEngine')).isNull();}return {exe:Process.enumerateModules()[0].path,engine:engine?engine.path:null,ready};};""")
            gate.load()
            paths = gate.exports_sync.paths()
            gate.unload()
            session.detach()
            if Path(paths["exe"]).resolve() != qa:
                raise ValueError("spawned process is not the isolated QA executable")
            if paths["ready"] and paths["engine"]:
                if hashlib.sha256(Path(paths["engine"]).read_bytes()).hexdigest() != ENGINE_SHA256:
                    raise ValueError("unverified engine fingerprint")
                ready = True
                break
            time.sleep(0.3)
        if not ready:
            raise RuntimeError("isolated QA Unity engine did not become ready")
        for row in manifest["files"]:
            name = f"{row['tribe']}-grade{row['grade']}"
            target = release / "native" / name
            command = [sys.executable, "-m", "tools.probe_building_sample", "--pid", str(pid),
                       "--qa-executable", str(qa), "--bundle", row["bundle"],
                       "--name", row["building_id"], "--ortho-size", "430", "--center-y", "64",
                       "--image-name", name + ".png", "--out", str(target)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if completed.returncode:
                raise RuntimeError(name + ": " + completed.stderr[-2500:])
            proof = json.loads((target / "native-proof.json").read_text(encoding="utf-8"))
            if proof["bundle_sha256"] != row["sha256"] or len(proof["events"]) != 1:
                raise ValueError("native proof is not bound to the expected bundle")
            result = proof["events"][0]["result"]
            if not result["instantiated"] or result["name"] != row["building_id"]:
                raise ValueError("required castle was not instantiated")
            if result["components"] != {"Animation": 1, "MeshRenderer": 1, "MeshCollider": 1}:
                raise ValueError("unexpected native castle components")
            preview = release / row["preview"]
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_bytes((target / (name + ".png")).read_bytes())
            row.update(native_verified=True, native_proof=str(target / "native-proof.json"),
                       preview_sha256=hashlib.sha256(preview.read_bytes()).hexdigest())
            if not row["pc_existing"]:
                conversion_path = Path(row["bundle"]).with_suffix(".json")
                conversion = json.loads(conversion_path.read_text(encoding="utf-8"))
                conversion.update(native_verified=True, native_proof=row["native_proof"])
                conversion_path.write_text(json.dumps(conversion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"tribe": row["tribe"], "grade": row["grade"], **result})
            print(name + ": native load, instantiate, components, render passed", flush=True)
        before = manifest["installed_building_files_before"]
        if any(not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest
               for p, digest in before.items()):
            raise RuntimeError("existing PC building resources changed")
        manifest["native_verified_count"] = len(results)
        manifest["preview_camera"] = {"orthographic_size": 430, "center_y": 64,
                                      "width": 680, "height": 510, "same_scale_for_all": True}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (release / "native-results.json").write_text(json.dumps({"engine_sha256": ENGINE_SHA256,
            "passed": len(results), "expected": 15, "results": results,
            "scope": "isolated original-engine renders, no normal gameplay or installation"},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed":len(results), "existing_resources_preserved":True}))
    finally:
        if pid is not None:
            try:
                frida.kill(pid)
            except frida.ProcessNotFoundError:
                pass
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
