"""Instantiate and render one building in an explicitly isolated legacy QA client."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

ENGINE_SHA256 = "0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5"


def main() -> None:
    import frida
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--qa-executable", type=Path, required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--ortho-size", type=float, default=250)
    ap.add_argument("--center-y", type=float, default=64)
    ap.add_argument("--image-name", default="original-oni-castle.png")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.qa_executable.parent.name != "qa-client":
        ap.error("isolated qa-client required")
    if not 100 <= args.ortho_size <= 1000 or not -1000 <= args.center_y <= 1000:
        ap.error("invalid preview camera bounds")
    if Path(args.image_name).name != args.image_name or not args.image_name.endswith(".png"):
        ap.error("a plain PNG output filename is required")
    args.out.mkdir(parents=True, exist_ok=True)
    session = frida.attach(args.pid)
    script = None
    events = []
    try:
        gate = session.create_script("""rpc.exports.paths=()=>{const m=Process.findModuleByName('webplayer_win.dll');return {exe:Process.enumerateModules()[0].path, engine:m?m.path:null};};""")
        gate.load()
        paths = gate.exports_sync.paths()
        gate.unload()
        if Path(paths["exe"]).resolve() != args.qa_executable.resolve():
            raise ValueError("PID is not the specified QA client")
        if not paths["engine"] or hashlib.sha256(Path(paths["engine"]).read_bytes()).hexdigest() != ENGINE_SHA256:
            raise ValueError("QA engine is not the verified Unity WebPlayer")
        blob = args.bundle.read_bytes()
        fingerprint = hashlib.sha256(blob).hexdigest()
        script = session.create_script(Path(__file__).with_suffix(".js").read_text(encoding="utf-8"))
        def receive(message, data):
            payload = message.get("payload", message)
            if "result" in payload and data:
                (args.out / args.image_name).write_bytes(data)
            events.append(payload)
        script.on("message", receive)
        script.load()
        script.exports_sync.enqueue({"name": args.name, "sha256": fingerprint,
                                     "orthoSize": args.ortho_size, "centerY": args.center_y}, blob)
        deadline = time.monotonic() + 45
        while not events and time.monotonic() < deadline:
            time.sleep(0.15)
        proof = {"bundle_sha256": fingerprint, "engine_sha256": ENGINE_SHA256,
                 "scope": "isolated original-engine asset render; no game API or save writes", "events": events}
        (args.out / "native-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not events or any("error" in row or row.get("type") == "error" for row in events):
            raise RuntimeError("native sample failed: " + json.dumps(events))
        print(json.dumps(events))
    finally:
        if script is not None:
            script.unload()
        session.detach()


if __name__ == "__main__":
    main()
