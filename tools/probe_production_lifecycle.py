"""Probe original production tables with isolated in-memory players only.

No game process, HTTP service, database or existing player is used. Timers use
an injected clock; this checks backend coverage and never claims UI acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_production_lifecycle import ProductionLifecycleTest
from tests.test_friend_production import FriendProductionTest
from app.minijson import parse_json_document
from app.business.production_availability import FIELD_LESSON_RECIPE, STARTER_INDUSTRIES
import copy


def probe(root: Path) -> dict:
    names = ("building", "product", "reward01_politic", "building_level", "defines",
             "draft", "playerLevel", "politicMission", "accelerate_produce_task", "tactics", "potion", "cannon_shot",
             "item03", "item07", "item11", "item15", "skill", "building_evolutions", "friend_complete_level")
    tables = {name: parse_json_document((root / (name + ".json")).read_bytes())[name]
              for name in names}
    tables["skillMessage.json"] = parse_json_document((root / "skillMessage.json").read_bytes())["message"]
    runner = ProductionLifecycleTest()
    runner.setUp()
    runner.tables = tables
    counts, supported, excluded, withheld, failures = Counter(), [], [], [], []
    started = time.monotonic()
    for bid, row in tables["building"].items():
        if row.get("map0") is not True or row.get("produceType") not in ("auto", "manual", "single"):
            continue
        for code in row["products"]:
            try:
                runner.place(bid)
                if code == FIELD_LESSON_RECIPE:
                    player = runner.saved()
                    player["missions"].pop("5")
                    runner.save(player)
                    accepted = runner.call("politic/mission/changeState",
                                           missionIds=["po_mission_00005"], states=["accepted"])
                    assert accepted["succeeded"], accepted
                elif row.get("itemId") in STARTER_INDUSTRIES and tables["product"][code]["dueInterval"] < 60:
                    listed = runner.call("politic/building/getProductsByBuilding", buildingId=1)
                    assert listed["succeeded"] and code not in listed["products"], listed
                    runner.fails("politic/task/submitProduceTask", buildingId=1, productId=code)
                    withheld.append({"building": bid, "product": code})
                    continue
                engine = (runner.service.automatic_production if row["produceType"] == "auto"
                          else runner.service.fixed_production)
                if row["produceType"] == "auto":
                    mapped = runner.call("politic/map/getMapData")
                    assert mapped.get("succeeded"), mapped.get("errorReason")
                    task = mapped["producings"]["1"]
                    assert task["dueTime"] - task["createdTime"] == tables["product"][code]["dueInterval"]
                    counts["automatic_timers"] += 1
                try:
                    engine.reward_plan(runner.saved()["buildings"]["1"], row, code)
                except ValueError as exc:
                    excluded.append({"building": bid, "product": code, "reason": str(exc)})
                    continue
                if row["produceType"] != "auto":
                    result = runner.call("politic/task/submitProduceTask", buildingId=1, productId=code)
                    assert result.get("succeeded"), result.get("errorReason")
                task = runner.saved()["produce"]["1"]
                runner.now = task["dueTime"]
                result = runner.call("politic/task/completeTasks", buildingIds=[1])
                assert result.get("succeeded"), result.get("errorReason")
                final, durability = runner.saved(), row["durability"]
                assert result["buildings"]["1"]["durability"] == (durability if durability == 10001 else durability - 1)
                if row["produceType"] == "auto" and durability > 1:
                    assert "1" in result["autoProducings"]
                elif durability == 1:
                    assert "1" not in final["buildings"]
                else:
                    assert not result["autoProducings"]
                counts[row["produceType"] + "_settlements"] += 1
                supported.append({"building": bid, "product": code, "finite": durability != 10001})
            except Exception as exc:
                failures.append({"building": bid, "product": code, "reason": str(exc), "type": type(exc).__name__})
    # Exercise all friend-only grades through the actual visitor transaction.
    helper = FriendProductionTest()
    helper.setUp()
    helper.tables = tables
    friend_rows, evolution_rows, evolution_excluded = [], [], []
    for bid, row in tables["building"].items():
        if row.get("map0") is not True or row.get("produceType") != "friend":
            continue
        try:
            for session in (helper.actor, helper.owner):
                player = helper.states.load(session["playerId"])
                player["entity"]["level"] = 100
                for resource in ("gold", "wood", "food", "iron"):
                    player["resources"][resource]["amount"] = 0
                player.pop("friendProductionV1", None)
                helper.states.save(player, session["playerId"])
            helper.set_owner(bid)
            helper.now = helper.states.load(helper.owner["playerId"])["produce"]["1"]["dueTime"]
            result = helper.f("task/completeFriendTasks", mapId=0, buildingId=1)
            assert result.get("succeeded") and "errno" not in result, result
            assert "1" in result["autoProducings"]
            friend_rows.append({"building": bid, "product": row["products"][0]})
        except Exception as exc:
            failures.append({"building": bid, "stage": "friend", "reason": str(exc), "type": type(exc).__name__})
    family = {(r["itemId"], r["grade"]): key for key, r in tables["building"].items()}
    for bid, row in tables["building"].items():
        next_id = family.get((row["itemId"], row["grade"] + 1))
        if next_id is None:
            continue
        if not row.get("map0") or row.get("category") == "fabric":
            evolution_excluded.append({"building": bid, "reason": "outside main-city evolution source scope"})
            continue
        try:
            max_levels = [level for level in range(1, row["grade"] * 10 + 1)
                          if tables["building_level"].get(f"{row['levelUpTypeId']}{row['grade'] * 1000 + level}", {}).get("needExp") == 0]
            if not max_levels:
                evolution_excluded.append({"building": bid, "reason": "original table has no maximum level row"})
                continue
            runner.place(bid, level=max(max_levels))
            player = runner.saved()
            player["buildings"]["1"].update(deployedMapKey="none", status="waiting")
            player["buildings"]["2"] = {**copy.deepcopy(player["buildings"]["1"]), "instanceId": 2}
            player["occupiedGrids"], player["produce"] = {}, {}
            player["counters"].update(nextBuildingId=3, buildingCount=2)
            fee = tables["building_evolutions"].get(bid, {})
            for potion, amount in zip(fee.get("fabrics", []), fee.get("amount", [])):
                item = tables["potion"][potion]["itemID"]
                player["items"][item] = player["items"].get(item, 0) + amount
            runner.save(player)
            result = runner.call("politic/building/conflateBuilding", first=1, second=2)
            assert result.get("succeeded"), result.get("errorReason")
            assert result["building"]["buildingTypeId"] == next_id
            assert set(runner.saved()["buildings"]) == {"3"}
            evolution_rows.append({"building": bid, "next": next_id, "maximum_level": max(max_levels)})
        except Exception as exc:
            failures.append({"building": bid, "stage": "evolution", "reason": str(exc), "type": type(exc).__name__})
    summary = {
        "passed": not failures and not excluded, "offline_memory_only": True, "network_or_database_used": False,
        "counts": dict(counts), "supported_buildings": len({r["building"] for r in supported}),
        "supported_recipes": len({r["product"] for r in supported}), "supported_pairs": len(supported),
        "finite_pairs": sum(r["finite"] for r in supported), "excluded_pairs": len(excluded),
        "withheld_short_recipe_pairs": len(withheld),
        "friend_pairs": len(friend_rows), "evolution_pairs": len(evolution_rows),
        "evolution_excluded_pairs": len(evolution_excluded),
        "unexpected_failures": len(failures), "seconds": round(time.monotonic() - started, 2),
        "source_canonical_sha256": {name: hashlib.sha256(json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest() for name, value in tables.items()},
    }
    return {"summary": summary, "supported": supported, "friend": friend_rows,
            "evolution": evolution_rows, "evolution_excluded": evolution_excluded,
            "excluded": excluded, "withheld_short_recipes": withheld, "failures": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.tables)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    raise SystemExit(0 if result["summary"]["passed"] else 1)
