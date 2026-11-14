#!/usr/bin/env python3
"""Inventory original city dependencies without interpreting reward ranges as RNG."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.tables import TableCatalog


def audit(table_dir: Path, out: Path) -> dict:
    catalog = TableCatalog(table_dir)
    buildings, products = catalog.load("building"), catalog.load("product")
    rewards, levels, drafts = catalog.load("reward01_politic"), catalog.load("building_level"), catalog.load("draft")
    consumers = {code: [] for code in products}
    missing_products = []
    missing_initial_levels = []
    for code, row in buildings.items():
        for product in row.get("products", []):
            if product in consumers:
                consumers[product].append(code)
            elif product != "none":
                missing_products.append({"building": code, "product": product})
        level_key = str(row.get("levelUpTypeId")) + str(int(row.get("grade", 0)) * 1000 + 1)
        if level_key not in levels:
            missing_initial_levels.append({"building": code, "level_key": level_key})
    rows = []
    for code, product in sorted(products.items()):
        reward = rewards.get(product.get("rewardId"))
        issues = []
        ranges = []
        if not isinstance(reward, dict):
            issues.append("reward_row_missing")
        else:
            groups = set()
            for i in range(1, 11):
                item = reward.get(f"itemId{i}")
                if item in (None, "", "none"):
                    continue
                low, high = reward.get(f"count{i}min"), reward.get(f"count{i}max")
                group = reward.get(f"group{i}")
                ranges.append(f"{item}:{low}..{high}")
                if low != high:
                    issues.append("count_range_settlement_unverified")
                if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low > high:
                    issues.append("inverted_count_range")
                if group in groups or reward.get(f"ratio{i}min") != 1 or reward.get(f"ratio{i}max") != 1:
                    issues.append("selection_rule_unverified")
                groups.add(group)
        rows.append({"product": code, "building_references": ";".join(sorted(consumers[code])),
                     "reward": product.get("rewardId"), "reward_item_ranges": ";".join(ranges),
                     "openLevel": product.get("openLevel"), "openMission": product.get("openMission"),
                     "dueInterval": product.get("dueInterval"), "buildingExp": product.get("buildingExp"),
                     "issues": ";".join(sorted(set(issues))),
                     "status": "recipe query implemented; road bonus/selection/settlement still require evidence"})
    out.mkdir(parents=True, exist_ok=True)
    with (out / "product-dependencies.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    summary = {
        "buildings": len(buildings), "products": len(products), "building_level_rows": len(levels),
        "drafts": len(drafts), "building_produce_types": dict(Counter(row["produceType"] for row in buildings.values())),
        "product_issues": dict(Counter(issue for row in rows for issue in row["issues"].split(";") if issue)),
        "missing_product_references": missing_products, "missing_initial_building_levels": missing_initial_levels,
        "road_buildings": [code for code, row in buildings.items() if row.get("connectChipType") == "road"],
        "recipe_open_level": "player level: PluginManualProduce.cs:105-113 -> UserStatus.getLevelValue",
        "open_mission_values": dict(Counter(str(row.get("openMission")) for row in products.values())),
        "preview_quantity": "ProductItem.cs:98-102 -> UserStatus.cs:1735-1740: floor(float32(min + (level-1)*(max-min)/(grade*10-1))); first reward slot, item15 uses damage value instead; preview is not settlement proof",
        "table_hashes": {name: hashlib.sha256(catalog.path_for(name).read_bytes()).hexdigest()
                         for name in ("building", "product", "reward01_politic", "building_level", "draft", "defines")},
        "scope": "Static table joins only. Count min/max do not establish randomness, road-bonus formula or payout. Missing references may concern unused rows, not observed client failures."
    }
    (out / "table-audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: len(value) if key in {"missing_product_references", "missing_initial_building_levels"} else value
            for key, value in summary.items() if key not in {"table_hashes", "road_buildings"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/analysis/city-contract-20261115")
    args = parser.parse_args()
    print(json.dumps(audit(args.table_dir, args.out), ensure_ascii=False))
