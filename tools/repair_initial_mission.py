#!/usr/bin/env python3
"""Preview/repair only the known first-mission O-without-progress seed defect.

No default writes. --report creates a private plan. --apply requires that exact
plan and a new private backup file; all selected players commit atomically.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, state
from app.business.gameplay import GameplayService


def digest(player: dict) -> str:
    return hashlib.sha256(json.dumps(player, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def repaired(player: dict, rows: dict) -> dict | None:
    row = rows.get("po_mission_00001", {})
    if (row.get("index") != 1 or row.get("isAutoStart") != "TRUE"
            or row.get("bootCheckFunc") != "none"):
        raise ValueError("original first-mission definition is missing or different")
    if (not player.get("entity", {}).get("created")
            or player.get("missions") != {"0": "C", "1": "O"}
            or any(player.get(key) for key in ("missionProgress", "missionRewards", "missionChecks"))):
        return None
    result = copy.deepcopy(player)
    del result["missions"]["1"]
    return result


def write_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Refuse to overwrite previous evidence, including via an existing symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def apply_plan(plan: dict, rows: dict, backup_path: Path) -> int:
    entries = plan.get("players")
    if plan.get("version") != 1 or not isinstance(entries, list) or not entries:
        raise ValueError("empty or invalid repair plan")
    ids = tuple(entry["player_id"] for entry in entries)
    if any(not isinstance(pid, str) or not pid for pid in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid or duplicate repair identities")
    with state.atomic_players(ids) as players:
        updated = {}
        for entry in entries:
            pid = entry["player_id"]
            before = players[pid]
            if digest(before) != entry["before_sha256"]:
                raise state.StateConflictError("player changed after preview; regenerate the plan")
            after = repaired(before, rows)
            if after is None or digest(after) != entry["after_sha256"]:
                raise ValueError("repair candidate no longer matches the plan")
            updated[pid] = after
        write_private(backup_path, {"version": 1, "plan": plan, "before": players})
        for pid, after in updated.items():
            players[pid].clear()
            players[pid].update(after)
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--backup-file", type=Path)
    args = parser.parse_args(argv)
    rows = GameplayService().missions.rows()
    if args.apply:
        if args.plan is None or args.backup_file is None or args.report is not None:
            parser.error("--apply requires --plan and --backup-file, without --report")
        count = apply_plan(json.loads(args.plan.read_text(encoding="utf-8")), rows, args.backup_file)
        print(json.dumps({"mode": "apply", "repaired": count}))
        return 0
    if args.plan is not None or args.backup_file is not None:
        parser.error("--plan/--backup-file require --apply")
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("SELECT player_id FROM players")
            ids = [row["player_id"] for row in cur.fetchall()]
    entries = []
    for pid in ids:
        before = state.load(pid)
        after = repaired(before, rows)
        if after is not None:
            entries.append({"player_id": pid, "before_sha256": digest(before), "after_sha256": digest(after)})
    if args.report is not None:
        write_private(args.report, {"version": 1, "players": entries})
    print(json.dumps({"mode": "dry-run", "scanned": len(ids), "eligible": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
