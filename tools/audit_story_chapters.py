"""Check installed PC story tables and referenced bundle paths without playing a save."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tables import TableCatalog, TableError
from app.business.adventure_obstacle_services import section_at
from tools.audit_pc_story_cache import asset_key


def audit(root: Path) -> dict:
    catalog = TableCatalog(root / "tables")
    index = catalog.load("quest_1_index")
    enabled = [row for row in index.values() if row["enable"] and row["clientEnable"]]
    by_story = defaultdict(list)
    for row in enabled:
        by_story[row["questNo"]].append(row)
    bundle_root = root / "bundles"
    result = []
    for story, chapters in sorted(by_story.items()):
        key = f"quest_1_{story:04d}"
        try:
            sections = catalog.load(key)
            rewards = catalog.load(key + "_reward")
        except TableError as exc:
            result.extend({"chapter": row["id"], "tableError": str(exc)} for row in chapters)
            continue
        for row in sorted(chapters, key=lambda row: row["chapterNo"]):
            chapter = row["chapterNo"]
            chapter_sections = [s for s in sections.values() if s["chapterNo"] == chapter]
            backgrounds = set()
            script_groups = set()
            for section in chapter_sections:
                if section.get("bgImage") not in (None, "", "none"):
                    backgrounds.add(section["bgImage"])
                scripts = [section.get("startScriptId"), section.get("endScriptId")]
                for slot in range(1, 16):
                    event = section.get(f"event{slot}")
                    if isinstance(event, list) and len(event) >= 3 and event[0]:
                        scripts.append(event[2])
                script_groups.update(s.rsplit("_", 1)[0] for s in scripts
                                     if isinstance(s, str) and s.startswith("stq"))
            unsupported_areas = []
            for area in range(1, row["areaCount"] + 1):
                try:
                    section_at(sections, chapter, area, row[f"areaStep{area}"] - 1)
                except ValueError:
                    unsupported_areas.append(area)
            result.append({
                "chapter": row["id"],
                "areaCount": row["areaCount"],
                "areasWithoutSectionCoverage": unsupported_areas,
                "rewardTableRows": len(rewards),
                "missingBackgroundPaths": sorted(name for name in backgrounds
                    if not (bundle_root / "qbg" / (asset_key(name) + ".unity3d")).is_file()),
                "missingScriptPaths": sorted(name for name in script_groups
                    if not (bundle_root / "stq" / (asset_key(name) + ".unity3d")).is_file()),
            })
    return {"indexRows": len(index), "clientEnabledStories": len(by_story),
            "clientEnabledChapters": len(enabled), "clientEnabledAreas": sum(row["areaCount"] for row in enabled),
            "nativePlaytested": False, "chapters": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    output = audit(args.root)
    with args.report.open("x", encoding="utf-8") as report:
        json.dump(output, report, ensure_ascii=False, indent=2)
        report.write("\n")
    print({key: value for key, value in output.items() if key != "chapters"})


if __name__ == "__main__":
    main()
