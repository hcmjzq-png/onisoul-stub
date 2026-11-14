"""Verified lesson claims and the level/mission gate portion of player progression.

No random rewards, overflow mail or unverified level-up refills are generated.
See docs/analysis/remaining-services-20261115/README.md for the supported scope.
"""
from __future__ import annotations

from functools import partial
from typing import Any

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


def mission_closed(player: dict, code: str, missions: dict) -> bool:
    row = missions.get(code)
    if not isinstance(row, dict) or "index" not in row:
        return False
    return (player.get("missions") or {}).get(str(int(row["index"]))) == "C"


def level_cap(player: dict, levels: dict, missions: dict, limit: int) -> int:
    """Stop at the first uncleared requirementForNext; never infer mission success."""
    available = sorted(int(k) for k in levels if str(k).isdigit() and 0 < int(k) <= limit)
    if not available:
        return 1
    for level in available:
        required = levels[str(level)].get("requirementForNext", "none")
        if required not in (None, "", "none") and not mission_closed(player, required, missions):
            return level
    return available[-1]


class ProgressionServices(PlayerServices):
    def register(self, registry: Any) -> None:
        for api, action in {
            "politic/mypage/takeLesson": self.take_lesson,
            "common/increasePlayerLevel": self.increase_level,
            "common/solvePlayerLevelCap": self.solve_cap,
            "common/getPlayerEntity": self.player_entity,
        }.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))
        for api in ("common/getServerTime", "auth/keepAliveContainer"):
            registry.register(api, partial(self.session_ack, api))

    def session_ack(self, api: str, params: dict, session: dict | None) -> dict:
        # HTTP transport resolves/touches the existing token before dispatch.
        # SessionKeeper.refreshKeepAliveContainer does not read any result fields.
        if not self.service._player_id(session):
            return self.service._failure(api, "authentication required")
        return response_shapes.success(api)

    @staticmethod
    def player_entity(player: dict, params: dict) -> dict:
        # The verified consumer is WebApiClient.debugCreateQuestEncount.
        return {"playerId": player["entity"]["playerId"]}

    def take_lesson(self, player: dict, params: dict) -> dict:
        if not player["entity"].get("created"):
            raise ValueError("player must be created before taking lessons")
        code = params.get("lessonId")
        if not isinstance(code, str) or code not in self.table("lesson"):
            raise ValueError("unknown lessonId")
        if code in player.get("lessonsDone", []):
            return {"reward": {}, "toInbox": {}}
        row = self.table("lesson")[code]
        triggers = row.get("triggerMissions")
        if not isinstance(triggers, list) or not all(isinstance(value, str) for value in triggers):
            raise ValueError("stub has no assets: invalid lesson triggerMissions")
        missions = self.table("politicMission")
        if any(not mission_closed(player, value, missions) for value in triggers if value != "none"):
            raise ValueError("lesson prerequisite mission is not closed")
        reward_id = row.get("reward")
        reward = self.table("reward14_lesson").get(reward_id)
        if not isinstance(reward, dict):
            raise ValueError("stub has no assets: lesson reward row missing")
        amounts: dict[str, int] = {}
        groups = set()
        for index in range(1, 11):
            item = reward.get(f"itemId{index}")
            if item in (None, "", "none"):
                continue
            group = reward.get(f"group{index}")
            if (not isinstance(group, str) or group in ("", "none") or group in groups
                    or reward.get(f"ratio{index}min") != 1 or reward.get(f"ratio{index}max") != 1):
                raise ValueError("lesson reward selection rule is not supported")
            groups.add(group)
            low, high = reward.get(f"count{index}min"), reward.get(f"count{index}max")
            if low != high:
                raise ValueError("lesson reward count range requires verification")
            amount = integer(low, 1)
            amounts[item] = amounts.get(item, 0) + amount
        if not amounts:
            raise ValueError("stub has no assets: lesson has no supported reward rows")
        # Validate the entire reward before changing anything. Character/tactic
        # delivery and inbox overflow need their own rules, not inventory tokens.
        resource_ids = {"item11_0000101": "gold", "item11_0000201": "wood",
                        "item11_0000301": "food", "item11_0000401": "iron"}
        updated: dict[str, int] = {}
        for item, amount in amounts.items():
            if item == "item11_0000501":
                updated["exp"] = integer(player["entity"].get("exp", 0)) + amount
                integer(updated["exp"])
            elif item in resource_ids:
                key = resource_ids[item]
                current = player["resources"][key]
                total = integer(current["amount"]) + amount
                if total > integer(current["maxAmount"]):
                    raise ValueError("lesson resource overflow delivery is not implemented")
                updated[key] = total
            else:
                raise ValueError("lesson reward delivery category is not implemented")
        for key, amount in updated.items():
            if key == "exp":
                player["entity"]["exp"] = amount
            else:
                player["resources"][key]["amount"] = amount
        player.setdefault("lessonsDone", []).append(code)
        return {"reward": {item: float(amount) for item, amount in amounts.items()}, "toInbox": {}}

    def progression_tables(self) -> tuple[dict, dict, int]:
        levels, missions = self.table("playerLevel"), self.table("politicMission")
        rule = self.table("defines").get("level_limit")
        if not isinstance(rule, dict):
            raise ValueError("stub has no assets: level_limit missing")
        return levels, missions, integer(rule.get("value"), 1)

    def solve_cap(self, player: dict, params: dict) -> dict:
        if not player["entity"].get("created"):
            raise ValueError("player must be created before level progression")
        levels, missions, limit = self.progression_tables()
        cap = level_cap(player, levels, missions, limit)
        player["entity"]["cap"] = cap
        return {"cap": float(cap)}

    def increase_level(self, player: dict, params: dict) -> dict:
        self.solve_cap(player, params)
        levels = self.table("playerLevel")
        entity = player["entity"]
        level, exp, cap = integer(entity["level"], 1), integer(entity["exp"]), integer(entity["cap"], 1)
        # exp is cumulative. Deriving the eligible level makes retries with the
        # same experience idempotent; it never subtracts or grants experience.
        while level < cap:
            row = levels.get(str(level))
            if not isinstance(row, dict) or str(level + 1) not in levels:
                raise ValueError("stub has no assets: player level row missing")
            if exp < integer(row.get("exp"), 1):
                break
            level += 1
        entity["level"] = level
        self.service._apply_limits(player)
        return {"kokudaka": float(player.get("kokudaka", 0)),
                "possessionLimits": self.service._possession_limits(player)}
