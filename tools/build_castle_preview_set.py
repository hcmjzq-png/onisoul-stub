"""Stage three tribes' grade 1-5 castles without touching installed PC assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.port_building_bundle import convert, read_tree, sha

TRIBES = (("human", "人族", "002"), ("oni", "鬼族", "001"), ("evil", "幻魔族", "000"))


def filename(logical: str) -> str:
    return hashlib.md5(logical.encode("utf-16le")).hexdigest() + ".unity3d"


def load_table(directory: Path, name: str) -> dict:
    return next(iter(json.loads((directory / (name + ".json")).read_text(encoding="utf-8")).values()))


def main() -> None:
    import UnityPy
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tables", type=Path, required=True)
    ap.add_argument("--pc-buildings", type=Path, required=True)
    ap.add_argument("--ps3-buildings", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--reuse-candidates", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    for protected in (args.pc_buildings, args.ps3_buildings, args.tables):
        if out == protected.resolve() or protected.resolve() in out.parents:
            ap.error("output must be separate from installed/source assets")
    if out.exists() and any(out.iterdir()):
        ap.error("choose a fresh output directory")
    buildings, models = load_table(args.tables, "building"), load_table(args.tables, "buildingModel")
    before = {str(p.resolve()): sha(p.read_bytes()) for p in args.pc_buildings.glob("*.unity3d")}
    rows = []
    # Resolve every original table reference before producing any candidate.
    for tribe, title, code in TRIBES:
        for grade in range(1, 6):
            model_id = f"building200_{code}_{grade:02}_01_1_1"
            row = buildings[model_id]
            if row["grade"] != grade or row["waitImages"] != [model_id]:
                raise ValueError("castle appearance differs from the expected original mapping")
            logical = models[model_id]["fileGroup"]
            pc, source = args.pc_buildings / filename(logical), args.ps3_buildings / filename(logical)
            if not pc.is_file() and not source.is_file():
                raise ValueError(f"stub has no assets: {model_id}")
            rows.append({"tribe": tribe, "tribe_name": title, "grade": grade,
                         "level_cap": grade * 10, "building_id": model_id,
                         "logical": logical, "size": row["size"], "pc_existing": pc.is_file(),
                         "original_pc_path": str(pc.resolve()), "source": str(source.resolve())})
    out.mkdir(parents=True, exist_ok=True)
    candidates = out / "bundles"
    candidates.mkdir()
    reused = 0
    for row in rows:
        if row["pc_existing"]:
            path = Path(row["original_pc_path"])
            blob = path.read_bytes()
            row.update(bundle=str(path), sha256=sha(blob), provenance="existing_pc_preserved")
        else:
            destination = candidates / filename(row["logical"])
            previous = args.reuse_candidates / destination.name if args.reuse_candidates else None
            proof = None
            if previous and previous.is_file() and previous.with_suffix(".json").is_file():
                saved = json.loads(previous.with_suffix(".json").read_text(encoding="utf-8"))
                if (saved["source_sha256"] == sha(Path(row["source"]).read_bytes())
                        and saved["template_sha256"] == sha(args.template.read_bytes())
                        and saved["output_sha256"] == sha(previous.read_bytes())):
                    blob, proof = previous.read_bytes(), saved
                    reused += 1
            if proof is None:
                blob, proof = convert(Path(row["source"]), args.template, row["logical"])
            with destination.open("xb") as stream:
                stream.write(blob)
            proof["output"] = str(destination)
            destination.with_suffix(".json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            row.update(bundle=str(destination), sha256=sha(blob), provenance=proof["provenance"])
        objects = list(UnityPy.load(blob).objects)
        roots = [o for o in objects if o.type.name == "GameObject" and read_tree(o)[0]["m_Name"] == row["building_id"]]
        if len(roots) != 1:
            raise ValueError("required exact castle GameObject missing or ambiguous")
        row["root_path_id"] = roots[0].path_id
        row["object_count"] = len(objects)
        row["preview"] = f"previews/{row['tribe']}-grade{row['grade']}.png"
        print(f"{row['tribe']} grade {row['grade']}: {'preserved' if row['pc_existing'] else 'candidate'}", flush=True)
    after = {str(p.resolve()): sha(p.read_bytes()) for p in args.pc_buildings.glob("*.unity3d")}
    if before != after:
        raise RuntimeError("installed building resources changed during staging")
    manifest = {"scope": "three tribes, grade 1-5; preview only, not installed",
                "existing_pc_preserved": sum(r["pc_existing"] for r in rows),
                "missing_pc_candidates": sum(not r["pc_existing"] for r in rows),
                "prior_candidates_reused": reused, "installed_building_files_before": before,
                "installed_building_files_unchanged": True, "files": rows}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in manifest.items() if k != "files" and k != "installed_building_files_before"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
