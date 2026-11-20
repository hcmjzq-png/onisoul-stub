"""Package the three original icon images used after finishing tutorial 17."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_quest_collection_icons import asset_id, build, table


FINALE = "po_mission_00013"
FOLLOWUPS = {
    "po_mission_00020": "mission_000016",
    "po_mission_00033": "mission_000029",
    "po_mission_00304": "mission_000020",
    "po_mission_00488": "mission_000016",
}
TEMPLATE = "mission_000023"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tables", "bundles", "art", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    missions = table(args.tables, "politicMission")
    expected = {key: row["iconFileName"] for key, row in missions.items()
                if FINALE in row.get("bootCheckData", [])}
    if expected != FOLLOWUPS:
        raise ValueError("unexpected tutorial 17 follow-up mission table")
    template = (args.bundles / "mission" / f"{asset_id(TEMPLATE)}.unity3d").read_bytes()
    records = {}
    for icon in sorted(set(FOLLOWUPS.values())):
        blob, pixels = build(template, TEMPLATE, icon, {icon: args.art / f"{icon}.png"})
        if pixels[icon][0] != (64, 64):
            raise ValueError(f"unexpected mission icon size: {icon}")
        records[icon] = (blob, pixels[icon][1])
    (args.out / "mission").mkdir(parents=True, exist_ok=False)
    manifest = []
    for icon, (blob, pixel_hash) in records.items():
        relative = f"mission/{asset_id(icon)}.unity3d"
        with (args.out / relative).open("xb") as stream:
            stream.write(blob)
        manifest.append({"icon": icon, "relative": relative, "sha256": hashlib.sha256(blob).hexdigest(),
                         "rgba_sha256": pixel_hash})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(manifest)} PC icons for {len(FOLLOWUPS)} follow-up missions")


if __name__ == "__main__":
    main()
