#!/usr/bin/env python3
"""Exercise original lesson rows with an isolated memory-only player."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.business.gameplay import GameplayService
from app.business.registry import Registry
from app.tables import TableCatalog
from tools.gameplay_smoke import MemoryState, MemorySessions


def run(table_dir: Path) -> dict:
    states, sessions = MemoryState(), MemorySessions()
    catalog = TableCatalog(table_dir)
    service = GameplayService(catalog=catalog, load_state=states.load, save_state=states.save, session_store=sessions)
    registry = service.register(Registry()).register_contract_defaults()
    session, _ = service._issue_login("progression-memory-only")
    assert service.create_player({"username": "progression-memory-only", "countryId": "country37",
        "navigatorId": "navi8000101", "colorIndex": "color1"}, session)["succeeded"]
    player = states.load(session["playerId"])
    assert player["entity"]["cap"] == 5
    # These prerequisites are test setup in memory; no real mission is completed.
    player["missions"].update({str(int(row["index"])): "C" for row in catalog.load("politicMission").values()})
    states.save(player, session["playerId"])
    supported, unsupported = [], {}
    for code in catalog.load("lesson"):
        before = states.load(session["playerId"])
        _, response = registry.dispatch("politic/mypage/takeLesson", {"lessonId": code}, session)
        if response["succeeded"]:
            supported.append(code)
            after = states.load(session["playerId"])
            _, repeated = registry.dispatch("politic/mypage/takeLesson", {"lessonId": code}, session)
            assert repeated["reward"] == {} and states.load(session["playerId"]) == after
        else:
            unsupported[code] = response["errorReason"]
            assert states.load(session["playerId"]) == before
    assert len(supported) == 19
    assert set(unsupported) == {"lesson_00008", "lesson_00018", "lesson_00020", "lesson_00021", "lesson_00022"}
    return {"supported_lessons": len(supported), "blocked_lessons": unsupported,
            "scope": "memory only; no database or player-state writes"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-dir", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().table_dir), ensure_ascii=False))
