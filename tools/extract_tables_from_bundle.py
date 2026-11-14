#!/usr/bin/env python3
"""Extract manifest-declared JSON TextAssets from the original PC UnityWeb bundle.

The verified Unity 3.5 TextAsset layout stores an LE length-prefixed UTF-8 name,
4-byte alignment, then an LE byte length and the UTF-8 script. Match both lengths
and the JSON root; do not scan arbitrary JSON fragments or rewrite string data.
This is a targeted extractor for this client's table bundle, not a Unity parser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.minijson import MiniJsonError, parse_json_document  # noqa: E402
from app.tables import MANIFEST_PATH, QUEST_MANIFEST_PATH, SERVER_MANIFEST_PATH  # noqa: E402
from tools.import_tables import read_manifest  # noqa: E402

LZMA_PROPS = b"\x5d\x00\x00\x80\x00"
# Catalog references also match, but must pass script length, JSON and root checks.
NAME_PATTERN = re.compile(rb"([\x01-\x7f]\x00\x00\x00)([A-Za-z0-9_]+\.json)")


@dataclass(frozen=True)
class TextAsset:
    file: str
    root_key: str
    name_offset: int
    script_offset: int
    raw: bytes
    rows: int

    def evidence(self) -> dict:
        return {
            "file": self.file, "root_key": self.root_key,
            "container_name_offset": self.name_offset,
            "script_offset": self.script_offset, "script_length": len(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(), "rows": self.rows,
        }


def decompress_bundle(path: str | Path) -> bytes:
    blob = Path(path).read_bytes()
    idx = blob.find(b"UnityWeb")
    if idx < 0:
        raise ValueError(f"not a UnityWeb bundle: {path}")
    off = blob.find(LZMA_PROPS, idx)
    if off < 0:
        raise ValueError(f"LZMA block not found: {path}")
    return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(blob[off:])


def extract_assets(container: bytes, declared: dict[str, str]) -> dict[str, TextAsset]:
    """Return validated named TextAssets; reject ambiguous duplicate assets."""
    found: dict[str, TextAsset] = {}
    for match in NAME_PATTERN.finditer(container):
        name = match.group(2).decode("ascii")
        if name not in declared or struct.unpack("<I", match.group(1))[0] != len(name):
            continue
        length_offset = (match.end() + 3) & ~3
        if length_offset + 4 > len(container):
            continue
        size = struct.unpack_from("<I", container, length_offset)[0]
        start = length_offset + 4
        if size < 2 or size > len(container) - start:
            continue
        raw = container[start:start + size]
        if not raw.lstrip().startswith((b"{", b"\xef\xbb\xbf")):
            continue
        try:
            document = parse_json_document(raw)
        except MiniJsonError:
            continue
        root = declared[name]
        if not isinstance(document, dict) or not isinstance(document.get(root), dict):
            continue
        if name in found:
            raise ValueError(f"duplicate TextAsset: {name}")
        found[name] = TextAsset(name, root, match.start(2), start, raw, len(document[root]))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--report", help="JSON report with hashes and TextAsset byte offsets")
    args = parser.parse_args(argv)
    declared: dict[str, str] = {}
    for path in (MANIFEST_PATH, SERVER_MANIFEST_PATH, QUEST_MANIFEST_PATH):
        for row in read_manifest(path):
            name, root = row["table_file"].strip(), row["root_key"].strip()
            if name in declared and declared[name] != root:
                raise ValueError(f"conflicting table root: {name}")
            declared[name] = root
    container = decompress_bundle(args.bundle)
    assets = extract_assets(container, declared)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    skipped = 0
    for name, asset in assets.items():
        target = out / name
        if args.only_missing and target.exists():
            skipped += 1
            continue
        temporary = target.with_suffix(".json.tmp")
        temporary.write_bytes(asset.raw)
        temporary.replace(target)
    missing = sorted(set(declared) - assets.keys())
    if args.report:
        Path(args.report).write_text(json.dumps({
            "bundle_sha256": hashlib.sha256(Path(args.bundle).read_bytes()).hexdigest(),
            "container_sha256": hashlib.sha256(container).hexdigest(),
            "tables": [assets[name].evidence() for name in sorted(assets)],
            "missing": missing,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"validated={len(assets)} written={len(assets) - skipped} skipped={skipped} missing={len(missing)}")
    for name in missing:
        print(f"stub has no assets: {name}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
