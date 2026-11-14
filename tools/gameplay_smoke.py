#!/usr/bin/env python3
"""Run the new-player login/main-map/mission 1-4 flow with in-memory state."""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import paths  # noqa: E402
from app.business.gameplay import GameplayService  # noqa: E402
from app.tables import TableCatalog  # noqa: E402


class MemoryState:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def load(self, player_id: str) -> dict:
        return copy.deepcopy(self.rows.get(player_id, {}))

    def save(self, player: dict, player_id: str) -> None:
        self.rows[player_id] = copy.deepcopy(player)


class MemorySessions:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.counter = 0

    def issue(self, account_key: str, token: str | None = None) -> dict:
        self.counter += 1
        token = token or f"smoke-{self.counter}"
        player_id = "p_" + hashlib.sha1(account_key.encode("utf-8")).hexdigest()[:8]
        session = {"token": token, "playerId": player_id, "accountKey": account_key}
        self.rows[token] = session
        return copy.deepcopy(session)

    def resolve(self, token: str | None) -> dict | None:
        return copy.deepcopy(self.rows.get(str(token or "")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-dir", default=str(paths.TABLE_DIR))
    args = parser.parse_args(argv)

    states = MemoryState()
    sessions = MemorySessions()
    service = GameplayService(
        catalog=TableCatalog(args.table_dir),
        load_state=states.load,
        save_state=states.save,
        session_store=sessions,
    )
    # This tool uses only memory stores; it does not enable public debug login.
    login, existing = service._issue_login("smoke-new-player")
    if existing:
        raise RuntimeError("fresh account was reported as an existing player")
    session = {"token": login["token"], "playerId": login["playerId"]}
    if not service.create_player(
        {
            "username": "smoke-new-player",
            "countryId": "country01",
            "navigatorId": "navi8000101",
            "colorIndex": "color1",
        },
        session,
    )["succeeded"]:
        raise RuntimeError("createPlayer failed")

    params = service.get_player_params({}, session)
    if params["characterCount"] <= 0:
        raise RuntimeError("createPlayer produced no characters")
    expected_cap = max(int(key) for key in service._table("playerLevel"))
    if params["entity"]["cap"] != expected_cap:
        raise RuntimeError(
            f"entity.cap={params['entity']['cap']} does not match max level {expected_cap}"
        )
    map_data = service.get_map_data({}, session)
    if "size" not in map_data["map"]:
        raise RuntimeError("getMapData did not return map size")

    for state in ("opened", "accepted", "finished", "closed"):
        service.change_mission_state(
            {"missionIds": ["po_mission_00001"], "states": [state]}, session
        )
    if states.load(session["playerId"])["resources"]["gold"]["amount"] <= 0:
        raise RuntimeError("mission 1 did not grant gold")

    service.change_mission_state(
        {"missionIds": ["po_mission_00002"], "states": ["accepted"]}, session
    )
    castle = service.submit_build_task(
        {"draftId": "draft2000002", "originCoord": [25, 25]}, session
    )
    if not castle["succeeded"]:
        raise RuntimeError(f"mission 2 castle failed: {castle.get('errorReason')}")
    service.complete_tasks({"buildingIds": [castle["buildingId"]]}, session)
    service.change_mission_state(
        {"missionIds": ["po_mission_00002"], "states": ["closed"]}, session
    )

    for state in ("accepted", "closed"):
        service.change_mission_state(
            {"missionIds": ["po_mission_00003"], "states": [state]}, session
        )
    if "draft2000041" not in service.get_drafts({}, session):
        raise RuntimeError("mission 3 did not grant the field draft")

    service.change_mission_state(
        {"missionIds": ["po_mission_00004"], "states": ["accepted"]}, session
    )
    field = service.submit_build_and_complete(
        {"draftId": "draft2000041", "originCoord": [27, 27]}, session
    )
    if not field["succeeded"]:
        raise RuntimeError(f"mission 4 field failed: {field.get('errorReason')}")
    service.change_mission_state(
        {"missionIds": ["po_mission_00004"], "states": ["closed"]}, session
    )

    player = states.load(session["playerId"])
    if player["missions"].get("4") != "C":
        raise RuntimeError("mission 4 did not close")
    print(
        "[gameplay-smoke] ok "
        f"characters={player['counters']['characterCount']} "
        f"buildings={player['counters']['buildingCount']} "
        f"missions={player['missions']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
