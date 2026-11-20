"""Package the five missing mission 13 icons from existing artwork for PC."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_quest_collection_icons import asset_id, build, table


MISSION = "po_mission_00012"
ITEMS = {"item07_0010004", "item07_0040005", "item07_0040010", "item07_0040015", "item07_0040020"}
TEMPLATE = "item07_0010003"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tables", "bundles", "art", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    reward_id = table(args.tables, "politicMission")[MISSION]["clearReward"]
    reward = table(args.tables, "reward01_politic")[reward_id]
    item_ids = {item for key, item in reward.items() if key.startswith("itemId") and item.startswith("item07_")}
    if item_ids != ITEMS | {"item07_0010002"}:
        raise ValueError("mission 13 has an unexpected consumable reward list")
    items = table(args.tables, "item07")
    template = (args.bundles / "item" / (asset_id(TEMPLATE) + ".unity3d")).read_bytes()

    candidates = {}
    records = []
    for item in sorted(ITEMS):
        icon = items[item]["iconName"]
        if icon != item:
            raise ValueError(f"unexpected icon name for {item}")
        art = {f"{icon}_{suffix}": args.art / f"{icon}_{suffix}.png" for suffix in ("01", "91")}
        bundle, textures = build(template, TEMPLATE, icon, art)
        if {name: dims for name, (dims, _) in textures.items()} != {
            f"{icon}_01": (64, 64), f"{icon}_91": (128, 256),
        }:
            raise ValueError(f"unexpected icon sizes for {item}")
        filename = asset_id(icon) + ".unity3d"
        candidates[filename] = bundle
        records.append({"item": item, "relative": "item/" + filename,
                        "sha256": hashlib.sha256(bundle).hexdigest(), "textures": textures})

    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "item").mkdir()
    for filename, bundle in candidates.items():
        (args.out / "item" / filename).write_bytes(bundle)
    manifest = {"mission": MISSION, "reward": reward_id, "template": TEMPLATE,
                "template_sha256": hashlib.sha256(template).hexdigest(), "files": records}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(records)} PC bundles and {sum(len(row['textures']) for row in records)} textures")


if __name__ == "__main__":
    main()
