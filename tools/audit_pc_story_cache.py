#!/usr/bin/env python3
"""Read-only inventory of PC story assets in a legacy client cache or bundle archive.

Pass cache/data7, Unity/WebPlayer/Cache/Shared or an extracted bundle directory.
UnityPy is required. Outputs an audit only; no files are installed. The PS3 or
Android bundle sharing a URL key is not counted as an original PC candidate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.extract_cached_bundles import extract_body, read_record


def asset_key(group: str) -> str:
    return hashlib.md5(group.encode("utf-16le")).hexdigest()


NAMES = {
    "quest": ("scene", ()),
    "questAssets": ("scene", ("autoskip", "fullautoskip", "questfullautoskipcaution")),
    "vsBattle": ("scene", ()),
    "vsBattleAssets": ("scene", ("battleeventtimeline", "battlefixedchar", "battle_end_0001")),
    "cch1_00001_01_3_01": ("cch", ("cch1_00001_01_3_01",)),
    "stq0_main": ("stq", ("stq0_main_01",)),
    "stq0_100010": ("stq", tuple(f"stq0_100010_{i:02d}" for i in (*range(9), 98, 99))),
    "stq0_300001": ("stq", ("stq0_300001_01",)),
}
WIRES = {asset_key(name): name for name in NAMES}
SCENES = {"quest", "vsBattle"}
SERIALIZED = ("BuildPlayer-quest", "BuildPlayer-vsBattle", "CustomAssetBundle-")


def required_members(group: str, category: str, names: tuple[str, ...]) -> set[str]:
    if group in SCENES:
        return {f"BuildPlayer-{group}", f"BuildPlayer-{group}.sharedAssets"}
    if category == "stq":
        return {member for name in names for member in (name, name + "_stringtable.json")}
    return set(names)


def bundle_bytes(data: bytes) -> bytes:
    if not data.startswith(b"UnityWeb\x00"):
        return data
    version = struct.unpack_from(">I", data, 9)[0]
    if version not in (1, 2, 3):
        raise ValueError("unsupported UnityWeb version")
    pos = data.index(0, data.index(0, 13) + 1) + 1
    length = struct.unpack_from(">I", data, pos)[0]
    if not pos + 24 <= length <= len(data):
        raise ValueError("invalid UnityWeb size")
    return data[:length]


def is_candidate_file(path: Path) -> bool:
    name = path.name.lower()
    return (path.suffix.lower() in {".d", ".unity3d", ".unityweb", ".bundle", ".unity"}
            or path.name.startswith(SERIALIZED) or name == "__data")


def scan(roots: list[Path]) -> dict:
    import UnityPy

    audited_members = set().union(*(required_members(group, category, names)
                                    for group, (category, names) in NAMES.items()))
    seen = {}
    hits = defaultdict(list)
    failures = []
    examined = 0
    for root in roots:
        candidates = (sorted(p for p in root.rglob("*") if p.is_file() and is_candidate_file(p))
                      if root.is_dir() else [root])
        for p in candidates:
            examined += 1
            expected = None
            try:
                wire = urlsplit(read_record(str(p))).path if p.suffix.lower() == ".d" else ""
                key = Path(wire or p.name).stem.rsplit("__", 1)[-1].lower()
                expected = WIRES.get(key)
                if p.stat().st_size > 256 * 1024 * 1024:
                    raise ValueError("analysis size limit")
                data = p.read_bytes()
                if p.suffix.lower() == ".d":
                    if not wire.lower().endswith(".unity3d"):
                        continue
                    data, _ = extract_body(data)
                    if data is None:
                        raise ValueError("no Unity body in cache record")
                data = bundle_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                # The optional on-disk name and URL only matter for partial
                # evidence; identical bytes still share the content inventory.
                named_node = p.name if p.name.startswith("BuildPlayer-") else None
                identity = (digest, named_node)
                if identity not in seen:
                    env = UnityPy.load(data)
                    objs = list(env.objects)
                    if not objs:
                        raise ValueError("no readable serialized objects")
                    nodes = {o.assets_file.name for o in objs}
                    # Standalone cache nodes may be named by the UnityPy in-memory
                    # stream. The on-disk node name identifies their scene half.
                    if named_node:
                        nodes.add(named_node)
                    fmt = sorted({(int(o.platform), o.assets_file.reader.endian) for o in objs})
                    entries = {}
                    for name, ptr in env.container.items():
                        name = name.casefold()
                        if name.startswith("stq0_") or name in audited_members:
                            entries[name] = ptr.get_obj().type.name
                    content = {}
                    for group, (category, assets) in NAMES.items():
                        required = required_members(group, category, assets)
                        if group in SCENES:
                            present = nodes & required
                        else:
                            kind = {"stq": "TextAsset", "scene": "GameObject", "cch": "Texture2D"}[category]
                            present = {member for member in required if entries.get(member) == kind}
                        content[group] = (sorted(present), sorted(required - present))
                    seen[identity] = (fmt, content)
                fmt, content = seen[identity]
                for group, (present, missing) in content.items():
                    if not present and group != expected:
                        continue
                    hits[group].append({"source": str(p), "cache_path": wire, "sha256": digest,
                        "format": fmt, "present": present, "missing": missing,
                        "complete_pc_candidate": fmt == [(7, "<")] and not missing})
            except (OSError, ValueError, struct.error, RuntimeError, EOFError, TypeError, IndexError, KeyError) as exc:
                if expected or p.suffix.lower() != ".d":
                    failures.append({"source": str(p), "asset": expected, "error_type": type(exc).__name__})
    return {"examined": examined, "distinct_readable": len(seen), "failures": failures,
            "assets": {name: {"path": f"{category}/{asset_key(name)}.unity3d",
                              "candidates": hits[name]}
                       for name, (category, _) in NAMES.items()}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("roots", nargs="+", type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    for root in args.roots:
        if not root.exists():
            p.error(f"input does not exist: {root}")
    summary = scan(args.roots)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
        output.write("\n")
    for name, asset in summary["assets"].items():
        candidates = asset["candidates"]
        print(name, len(candidates), "matches,", sum(c["complete_pc_candidate"] for c in candidates), "complete PC candidates")


if __name__ == "__main__":
    main()
