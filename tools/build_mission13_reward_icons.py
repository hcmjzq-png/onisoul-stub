"""Package missing tutorial consumable icons from existing PC artwork."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_quest_collection_icons import asset_id, build, table


TUTORIALS = {
    13: ("po_mission_00012", {"item07_0010004", "item07_0040005", "item07_0040010",
                            "item07_0040015", "item07_0040020"}, "item07_0010002"),
    17: ("po_mission_00013", {"item07_0010002", "item07_0010006", "item07_0010008"}, "item07_0010004"),
}
TEMPLATE = "item07_0010003"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tutorial", type=int, choices=TUTORIALS, default=13)
    for name in ("tables", "bundles", "art", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    mission, missing, installed = TUTORIALS[args.tutorial]
    reward_id = table(args.tables, "politicMission")[mission]["clearReward"]
    reward = table(args.tables, "reward01_politic")[reward_id]
    item_ids = {item for key, item in reward.items() if key.startswith("itemId") and item.startswith("item07_")}
    if item_ids != missing | {installed}:
        raise ValueError(f"tutorial {args.tutorial} has an unexpected consumable reward list")
    items = table(args.tables, "item07")
    template = (args.bundles / "item" / (asset_id(TEMPLATE) + ".unity3d")).read_bytes()

    candidates = {}
    records = []
    for item in sorted(missing):
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
    manifest = {"mission": mission, "reward": reward_id, "template": TEMPLATE,
                "template_sha256": hashlib.sha256(template).hexdigest(), "files": records}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(records)} PC bundles and {sum(len(row['textures']) for row in records)} textures")


if __name__ == "__main__":
    main()
