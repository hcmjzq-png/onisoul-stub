"""Repack the known country76 PC app with the failed-startup compatibility fix.

Offline only. No placeholder script is produced and no source file is overwritten.
All 24 other UnityWebData entries must remain byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_country_fix import pack_app, replace_entry
from tools.oni_il import AssemblyModel, parse_unity_web_data
from tools.repair_unityweb_lzma import layout
from tools.verify_il_bodies import verify_assembly

APP_SHA = "980438293373658772bf29aac1d87dbc545992cec3e7ff1db9d0d25d68342656"
DLL_SHA = "05f8e6963aeee70bde0aa25b56457c0e800d1d655d160db0c4512f6d1a54bb39"


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def build(app_path: Path, assembly_path: Path, out: Path) -> dict:
    source = app_path.read_bytes()
    if sha(source) != APP_SHA:
        raise ValueError("unknown source app fingerprint")
    if out.exists():
        raise FileExistsError("refusing to overwrite output directory")
    header, _compressed, size = layout(source)
    payload = lzma.decompress(source[header:], format=lzma.FORMAT_ALONE)
    if len(payload) != size:
        raise ValueError("source app length mismatch")
    parsed = parse_unity_web_data(payload)
    original = next(entry for entry in parsed.entries if entry.name == "Assembly-CSharp.dll")
    if sha(payload[original.offset:original.end]) != DLL_SHA:
        raise ValueError("source DLL fingerprint mismatch")
    il = verify_assembly(assembly_path)
    if not il["valid"]:
        raise ValueError("patched DLL has invalid method bodies")
    model = AssemblyModel(assembly_path)
    recovery = [(rid, owner, row) for rid, owner, row in model.iter_method_rows()
                if owner == "Script.Player" and str(row.Name) == "OniRecoverMissingStartup"]
    if len(recovery) != 1:
        raise ValueError("missing unique startup recovery")
    changed, first = replace_entry(payload, "Assembly-CSharp.dll", assembly_path.read_bytes())
    result = pack_app(source, changed, first)
    out.mkdir(parents=True)
    (out / "app.unity3d").write_bytes(result)
    (out / "il-verification.json").write_text(json.dumps(il, indent=2), encoding="utf-8")
    manifest = {"source_app_sha256": APP_SHA, "source_dll_sha256": DLL_SHA,
                "app_sha256": sha(result), "dll_sha256": sha(assembly_path.read_bytes()),
                "unchanged_entries": [entry.name for entry in parsed.entries
                                      if entry.name != "Assembly-CSharp.dll"],
                "compatibility_patch": "only finish failed scr2_000001_01 through original callback",
                "missing_script_restored": False, "progression_gates_changed": False}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.app, args.assembly, args.out)))
