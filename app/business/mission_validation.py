"""Server checks for verified mission predicates, without trusting client work values."""
from __future__ import annotations

from app.business.mission_chain import STATE_TO_LETTER, SYSTEM_MISSION


def state_of(player: dict, rows: dict, code: str) -> str:
    index = str((rows.get(code) or {}).get("index"))
    letter = player["missions"].get(index, "L")
    return next((state for state, value in STATE_TO_LETTER.items() if value == letter), "locked")


def eligible(player: dict, rows: dict, code: str) -> bool:
    row = rows[code]
    func = row.get("bootCheckFunc")
    if func == "none":
        return True
    if func == "clear_mission" and isinstance(row.get("bootCheckData"), list):
        return all(target in rows and state_of(player, rows, target) == "closed"
                   for target in row["bootCheckData"])
    return False


def validate_progress(player: dict, rows: dict) -> None:
    """Active summary entries must be restorable by the original client.

    Do not invent timestamps/work values or silently restart accepted missions.
    The narrowly identified old seed defect has a separate preview/repair tool.
    """
    by_index = {str(int(row["index"])): code for code, row in rows.items()}
    details = player.get("missionProgress", {})
    for index, letter in player["missions"].items():
        if letter not in ("O", "A", "F"):
            continue
        code = by_index.get(str(index))
        detail = details.get(code)
        if not isinstance(detail, dict) or STATE_TO_LETTER.get(detail.get("state")) != letter:
            raise ValueError("no stub response: active mission summary/progress mismatch; audit the saved mission")
    for code, detail in details.items():
        if code == SYSTEM_MISSION:
            continue
        if not isinstance(detail, dict) or code not in rows:
            raise ValueError("no stub response: invalid saved mission progress")
        if state_of(player, rows, code) != detail.get("state"):
            raise ValueError("no stub response: mission progress/summary mismatch; audit the saved mission")


def _measure(player: dict, rows: dict, buildings: dict, kind: str, grade: str, level: str, target: str, code: str) -> int:
    if kind == "missionStatus":
        if target not in rows or level not in STATE_TO_LETTER:
            raise ValueError("unsupported mission status condition")
        current = state_of(player, rows, target)
        # Old saves predate server proofs. A finished self-acceptance tutorial has
        # necessarily passed accepted; this does not excuse any building condition.
        return int(current == level or (target == code and level == "accepted" and current == "finished"))
    if kind not in ("totalBuildingCount", "categoryGradeCount"):
        if kind == "resourceCount" and grade == "any" and level == "any" and target in ("food", "gold", "wood", "iron"):
            from app.business.player_services import integer
            return integer(player["resources"][target]["amount"])
        raise ValueError(f"unsupported mission predicate: {kind}")
    if grade != "any" or level != "any":
        raise ValueError("building grade/level mission checks are not implemented")
    count = 0
    for record in player["buildings"].values():
        if record.get("status") == "building":
            # StateBuilding.complete increments UserStatus's total counter before
            # queuing completeTasks. The mission finish can therefore arrive first.
            # Only totalBuildingCount shares that timing; category counts still
            # require IsBuildComplete. Require explicit server-owned readiness.
            remaining = record.get("remainedClickCount")
            if (kind != "totalBuildingCount"
                    or type(remaining) not in (int, float) or remaining != 0):
                continue
        type_id = record.get("buildingTypeId")
        if kind == "totalBuildingCount":
            count += int(type_id == target)
        elif (record.get("deployedMapKey") == player["entity"].get("currentMapKey")
              and (buildings.get(type_id) or {}).get("category") == target):
            count += 1
    return count


def completed(player: dict, rows: dict, buildings: dict, code: str) -> bool:
    row = rows[code]
    needed = int(row.get("needClearCount") or 0)
    if needed <= 0:
        raise ValueError("mission completion rules are missing")
    proofs = player.setdefault("missionChecks", {}).setdefault(code, [])
    clear = set(proofs)
    for group in range(1, 4):
        count = int(row.get(f"conditionCount{group}") or 0)
        if count <= 0 or group in clear:
            continue
        columns = [row.get(f"{field}{group}") for field in
                   ("conditionTypes", "conditionGrades", "conditionLevels", "conditionTargets", "conditionCheckers", "conditionArgs")]
        if any(not isinstance(column, list) for column in columns) or len({len(column) for column in columns}) != 1:
            raise ValueError("mission condition columns are missing or inconsistent")
        passed = 0
        for kind, grade, level, target, checker, arg in zip(*columns):
            if checker != "eq_greater_than":
                raise ValueError(f"unsupported mission comparator: {checker}")
            passed += int(_measure(player, rows, buildings, kind, grade, level, target, code) >= int(arg))
        if passed >= count:
            clear.add(group)
    player["missionChecks"][code] = sorted(clear)
    return len(clear) >= needed


def transition(player: dict, rows: dict, buildings: dict, code: str, target: str) -> str:
    if code == SYSTEM_MISSION or code not in rows or target not in STATE_TO_LETTER:
        raise ValueError("unknown mission or invalid state")
    previous = state_of(player, rows, code)
    if previous == target:
        return previous
    order = list(STATE_TO_LETTER)
    if target == "locked" or order.index(target) < order.index(previous):
        raise ValueError("mission state cannot move backwards")
    if not eligible(player, rows, code):
        raise ValueError("mission prerequisites are not satisfied or not implemented")
    if target in ("finished", "closed"):
        # PoliticMissionProgressStatus.phaseOpened (PC:305-343) goes directly to
        # finished when conditions were met before acceptance. No accepted RPC
        # is sent in that branch. Still require the same server-owned proofs;
        # this does not permit locked -> finished or opened -> closed.
        allowed_previous = (previous in ("accepted", "finished")
                            or previous == "opened" and target == "finished")
        if not allowed_previous or not completed(player, rows, buildings, code):
            raise ValueError("mission completion conditions are not satisfied")
    player["missions"][str(rows[code]["index"])] = STATE_TO_LETTER[target]
    if target == "accepted":
        # A verified condition stays cleared, like PoliticMissionConditionOne.clearTime_.
        # Unsupported later missions may be accepted, but cannot be falsely completed.
        try:
            completed(player, rows, buildings, code)
        except (ValueError, TypeError):
            pass
    return previous
