#!/usr/bin/env python3
"""Repair only untouched created accounts with missing starter rosters.

Dry run by default. --apply requires a private backup directory. Existing cards,
formations, buildings, and accounts past the opening mission are never changed.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, state
from app.business.gameplay import GameplayService


def candidate(player: dict) -> bool:
    entity = player.get("entity") or {}
    return bool(
        entity.get("created") and entity.get("country")
        and not any(player.get(key) for key in ("characters", "decks", "buildings", "missionRewards", "missionProgress"))
        and not (player.get("counters") or {}).get("characterCount")
        and player.get("missions") in ({"0": "C"}, {"0": "C", "1": "O"})
    )


def repaired(service: GameplayService, player: dict, player_id: str) -> dict | None:
    if not candidate(player):
        return None
    country = player["entity"]["country"]
    equipment = service._table("beginning_equipment").get(country)
    if not equipment:
        raise ValueError("starter country table row missing")
    items = service._table("item01")
    characters = service._table("character")
    item_ids = [item for key in ("questCharacters", "attackCharacters", "defenseCharacters")
                for item in equipment.get(key, [])]
    if not item_ids or any((items.get(item) or {}).get("parameterId") not in characters for item in item_ids):
        raise ValueError("starter character table rows missing")
    result = copy.deepcopy(player)
    result["characters"] = service._initial_characters(country)
    prepared = service._prepare_state(result, player_id)
    # Keep this maintenance operation narrow: no unrelated defaults/limits/unlocks.
    result["decks"] = prepared["decks"]
    result.setdefault("counters", {})["characterCount"] = len(result["characters"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args(argv)
    if args.apply and args.backup_dir is None:
        parser.error("--apply requires --backup-dir")
    service = GameplayService()
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("SELECT player_id FROM players")
            ids = [row["player_id"] for row in cur.fetchall()]
    plans = []
    for player_id in ids:
        original = state.load(player_id)
        updated = repaired(service, original, player_id)
        if updated is not None:
            plans.append((player_id, original, updated))
    if args.apply and plans:
        args.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(args.backup_dir, 0o700)
        path = args.backup_dir / "starter-rosters-before.json"
        with path.open("x", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            json.dump({pid: old for pid, old, _new in plans}, handle, ensure_ascii=False, indent=2)
        for player_id, _old, updated in plans:
            # State.save checks revisions; a concurrent edit aborts instead of overwriting.
            state.save(updated, player_id)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "eligible": len(plans),
                      "starter_character_counts": [len(new["characters"]) for _, _, new in plans]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
