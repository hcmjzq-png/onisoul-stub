#!/usr/bin/env python3
"""Inventory the 47 original country-select dependencies; never substitute assets.

Requires optional UnityPy to inspect actual Texture2D/AudioClip names. A generated
manifest proves provenance only when the file digest matches; it is not UI QA.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request


def asset_hash(name: str) -> str:
    return hashlib.md5(name.encode("utf-16le")).hexdigest()


def inspect(path: Path, kind: str, required: list[str]) -> dict:
    import UnityPy
    try:
        env = UnityPy.load(str(path))
        objects = [obj.read() for obj in env.objects if obj.type.name == kind]
        names = [obj.m_Name for obj in objects]
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "names": names, "missing_names": sorted(set(required) - set(names)),
                "payload_bytes": sum(len(getattr(obj, "image_data", b"")) for obj in objects)
                if kind == "Texture2D" else sum(len(getattr(obj, "m_AudioData", b"")) for obj in objects)}
    except Exception as exc:
        return {"path": str(path), "error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tables", type=Path, required=True)
    ap.add_argument("--bundles", type=Path, required=True)
    ap.add_argument("--generated", type=Path, required=True)
    ap.add_argument("--server", help="Optional HTTP origin; HEAD checks only")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    def table(name):
        return json.loads((args.tables / (name + ".json")).read_text(encoding="utf-8"))[name]
    beginning, items, characters, voices = (table(n) for n in
        ("beginning_equipment", "item01", "character", "characterVoice"))
    manifest = json.loads((args.generated / "manifest.json").read_text(encoding="utf-8"))
    generated = {r["cid"]: r for r in manifest["generated"]}
    rows = []
    for country, equipment in sorted(beginning.items()):
        if country == "common":
            continue
        character_id = items[equipment["questCharacters"][0]]["parameterId"]
        c = characters[character_id]
        image = c["images"] + "_01"
        textures = [image + s for s in ("_1_01", "_1_02", "_1_03", "_3_01")]
        image_hash = asset_hash(image)
        row = {"country": country, "character": character_id, "image": image,
               "image_hash": image_hash, "appearance_clips": voices[c["voice"]]["12"]}
        local = args.bundles / "chara" / (image_hash + ".unity3d")
        row["local_image"] = inspect(local, "Texture2D", textures) if local.exists() else None
        entry = generated.get(c["images"])
        if entry:
            path = args.generated / Path(entry["file"].replace("\\", "/"))
            found = inspect(path, "Texture2D", textures)
            found["manifest_matches"] = found.get("sha256") == entry["sha256"]
            found["provenance"] = entry["status"]
            row["generated_image"] = found
        else:
            row["generated_image"] = None
        row["local_voices"] = []
        for clip in row["appearance_clips"]:
            path = args.bundles / "vse" / (asset_hash(clip) + ".unity3d")
            row["local_voices"].append(inspect(path, "AudioClip", [clip]) if path.exists()
                                       else {"clip": clip, "missing": True})
        rows.append(row)
    if args.server:
        paths = {"/client/pc/jp/assets/chara/" + r["image_hash"] + ".unity3d" for r in rows}
        paths |= {"/client/pc/jp/assets/vse/" + asset_hash(v) + ".unity3d"
                  for r in rows for v in r["appearance_clips"]}
        def head(path):
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with op.open(urllib.request.Request(args.server.rstrip("/") + path, method="HEAD"), timeout=15) as resp:
                    return path, resp.status
            except urllib.error.HTTPError as exc:
                return path, exc.code
            except OSError:
                return path, "connection-error"
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = dict(pool.map(head, sorted(paths)))
        for r in rows:
            r["server_image"] = statuses["/client/pc/jp/assets/chara/" + r["image_hash"] + ".unity3d"]
            r["server_appearance"] = {v: statuses["/client/pc/jp/assets/vse/" + asset_hash(v) + ".unity3d"]
                                      for v in r["appearance_clips"]}
    summary = {"countries": len(rows), "local_images": sum(bool(r["local_image"]) for r in rows),
               "generated_candidates": sum(bool(r["generated_image"]) for r in rows),
               "generated_match_and_names": sum(bool(r["generated_image"] and
                   r["generated_image"].get("manifest_matches") and not r["generated_image"].get("missing_names")
                   and not r["generated_image"].get("error")) for r in rows)}
    if args.server:
        summary.update(server_image_statuses=dict(Counter(str(r["server_image"]) for r in rows)),
                       countries_with_all_appearance_clips=sum(all(v == 200 for v in r["server_appearance"].values()) for r in rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
