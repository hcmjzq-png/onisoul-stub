#!/usr/bin/env python3
"""Audit original quest table dependencies without guessing game rules or editing state."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.tables import TableCatalog  # noqa: E402

REWARD_ID = re.compile(r"quest_[1-6]_\d{4}_\d+_\d+")


def audit(table_dir: Path, output: Path) -> dict:
    catalog = TableCatalog(table_dir)
    tables = {entry.root_key: catalog.load(entry.file) for entry in catalog.entries
              if entry.file.startswith("quest_")}
    missing: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    reference_count = over_100 = 0
    for name, rows in tables.items():
        if name.endswith("_reward"):
            continue
        for key, row in rows.items():
            for field, value in row.items():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if not isinstance(item, str) or not REWARD_ID.fullmatch(item):
                        continue
                    reference_count += 1
                    target = "_".join(item.split("_")[:3]) + "_reward"
                    if item not in tables.get(target, {}):
                        missing.setdefault((target, item), []).append((name, key, field))
                if (field.startswith("event") and isinstance(value, list) and len(value) > 1
                        and isinstance(value[0], (int, float)) and value[0] > 100):
                    over_100 += 1
    output.mkdir(parents=True, exist_ok=True)
    with (output / "unresolved-rewards.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["reward_table", "reward_id", "references", "first_source_table", "first_row", "first_field"])
        for (target, item), uses in sorted(missing.items()):
            writer.writerow([target, item, len(uses), *uses[0]])
    summary = {
        "quest_tables": len(tables), "quest_rows": sum(map(len, tables.values())),
        "tables_by_kind": dict(Counter("index" if n.endswith("_index") else "reward" if n.endswith("_reward") else "area" for n in tables)),
        "reward_references_checked": reference_count, "unresolved_unique_reward_ids": len(missing),
        "event_ratio_values_over_100": over_100,
        "tutorial_reward_references_unresolved": sum(any(use[0] == "quest_1_0000" for use in uses) for uses in missing.values()),
        "limits": "Reference inventory only. Disabled rows are included; missing references do not prove an active client failure. No event probability, battle outcome or reward is generated.",
    }
    (output / "table-audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.table_dir, args.out), ensure_ascii=False))
