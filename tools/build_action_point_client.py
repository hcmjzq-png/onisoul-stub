"""Build a local PC app bundle with a per-point display timer."""
from __future__ import annotations

import argparse
import hashlib
import lzma
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_country_fix import pack_app, replace_entry
from tools.check_pc_assembly import inspect_assembly
from tools.oni_il import parse_unity_web_data
from tools.repair_unityweb_lzma import layout


def build(source: Path, destination: Path, cecil: Path, references: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    blob = source.read_bytes()
    header, _, length = layout(blob)
    payload = lzma.decompress(blob[header:], format=lzma.FORMAT_ALONE)
    if len(payload) != length:
        raise ValueError("UnityWeb payload length mismatch")
    name = "Assembly-CSharp.dll"
    script = Path(__file__).with_name("patch_action_point_client.ps1")
    with tempfile.TemporaryDirectory(prefix="onisoul-action-point-client-") as directory:
        root = Path(directory)
        for entry in parse_unity_web_data(payload).entries:
            if entry.name.endswith(".dll"):
                if Path(entry.name).name != entry.name:
                    raise ValueError("unexpected managed entry path")
                (root / entry.name).write_bytes(payload[entry.offset:entry.end])
        input_assembly = root / name
        output_assembly = root / "patched.dll"
        subprocess.run(["pwsh", "-NoProfile", "-File", str(script), "-InputAssembly", str(input_assembly),
                        "-OutputAssembly", str(output_assembly), "-CecilPath", str(cecil.resolve()),
                        "-ReferenceDirectory", str(references.resolve())], check=True)
        inspect_assembly(output_assembly)
        updated, first_offset = replace_entry(payload, name, output_assembly.read_bytes())
    result = pack_app(blob, updated, first_offset)
    with destination.open("xb") as stream:
        stream.write(result)
    print(f"input  SHA-256 {hashlib.sha256(blob).hexdigest()}")
    print(f"output SHA-256 {hashlib.sha256(result).hexdigest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cecil", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True, help="Original WebPlayer managed library directory")
    args = parser.parse_args()
    build(args.app, args.output, args.cecil, args.references)
