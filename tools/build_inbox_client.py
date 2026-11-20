"""Build a local PC inbox bridge on a verified installed app bundle."""
from __future__ import annotations

import argparse
import hashlib
import lzma
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_country_fix import pack_app, replace_entry
from tools.oni_il import parse_unity_web_data
from tools.repair_unityweb_lzma import layout

ASSEMBLY = "Assembly-CSharp.dll"


def entries(app: bytes) -> tuple[bytes, dict[str, bytes]]:
    body = lzma.decompress(app[layout(app)[0]:], format=lzma.FORMAT_ALONE)
    return body, {entry.name: body[entry.offset:entry.end] for entry in parse_unity_web_data(body).entries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--cecil", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.app.read_bytes()
    if hashlib.sha256(source).hexdigest() != args.base_sha256:
        raise ValueError("Inbox client base fingerprint differs from the verified local app")
    body, original = entries(source)
    with TemporaryDirectory() as temp:
        dll = Path(temp) / ASSEMBLY
        patched = Path(temp) / "patched.dll"
        for name, data in original.items():
            if name.endswith(".dll") and Path(name).name == name:
                (Path(temp) / name).write_bytes(data)
        subprocess.run(["pwsh", "-NoProfile", "-File", str(Path(__file__).with_name("patch_inbox_client.ps1")),
                        "-Original", str(dll), "-Output", str(patched), "-CecilPath",
                        str(args.cecil.resolve(strict=True)), "-References", str(args.references.resolve(strict=True))], check=True)
        assembly = patched.read_bytes()
    changed, offset = replace_entry(body, ASSEMBLY, assembly)
    result = pack_app(source, changed, offset)
    if entries(result)[1] != {**original, ASSEMBLY: assembly}:
        raise ValueError("Unrelated app entries changed")
    with args.output.open("xb") as stream:
        stream.write(result)
    print(f"app sha256={hashlib.sha256(result).hexdigest()}, verified {len(original) - 1} unchanged entries")


if __name__ == "__main__":
    main()
