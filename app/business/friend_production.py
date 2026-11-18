"""Atomic friend visits/help with original wire fields and explicit local rules.

Compatibility: per-friend daily quotas follow friend_complete_level, reset at
UTC+8 midnight. Help harvest credits the owner and visitor equally, consumes one
owner cycle, and costs no PP. Friend acceleration is free and quota-limited.
"""
from __future__ import annotations

import copy
import math
from functools import partial

from app import state
from app.business import response_shapes
from app.business.city_services import CityServices, building_id
from app.business.player_services import integer
from app.business.production_inventory import ProductionInventory


class FriendProduction(CityServices):
    def __init__(self, service, social):
        super().__init__(service)
        self.social, self.clock = social, social.clock

    def register(self, registry) -> None:
        for name in ("getFriendMap", "getFriendMapData", "getFriendMapData2", "visitFriendMap",
                     "building/getFriendProductsByBuilding", "task/completeFriendTasks",
                     "task/accelerateFriendProduceTask"):
            registry.register("friend/" + name, partial(self.call_friend, name))

    def quota(self, actor: dict, target: str) -> dict:
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("no stub response: invalid friend production clock")
        now = int(value)
        day = (now + 8 * 3600) // 86400
        ledger = actor.setdefault("friendProductionV1", {"day": day, "targets": {}})
        if (not isinstance(ledger, dict) or not isinstance(ledger.get("targets"), dict)
                or not isinstance(ledger.get("day"), int) or ledger["day"] > day):
            raise ValueError("no stub response: invalid friend production ledger")
        if ledger["day"] < day:
            ledger.update(day=day, targets={})
        return ledger["targets"].setdefault(target, {"complete": 0, "accelerate": 0, "visited": False})

    def limit(self, actor: dict) -> int:
        level = integer(actor["entity"].get("level"), 1)
        candidates = [r for r in self.table("friend_complete_level").values() if integer(r.get("level"), 1) <= level]
        if not candidates:
            raise ValueError("stub has no assets: friend production quota missing")
        return integer(max(candidates, key=lambda r: r["level"])["count"], 1)

    def call_friend(self, name: str, params: dict, session: dict | None) -> dict:
        api = "friend/" + name
        actor = self.service._player_id(session)
        try:
            if not actor:
                raise ValueError("authentication required")
            target = self.social.target_id(params)
            # FriendListWindow/PoliticFSMChangeFriendMap use -1 on initial
            # visits; 0 explicitly selects the main city. Subcities stay gated.
            if actor == target or integer(params.get("mapId", -1), -1) not in (-1, 0):
                raise ValueError("only another friend's main map is supported")

            def action(rows, expired):
                if self.social.pair_status(actor, target, rows[actor], rows[target]) != "ok":
                    raise ValueError("accepted mutual friendship required")
                for pid in (actor, target):
                    prepared = self.service._prepare_state(rows[pid], pid)
                    rows[pid].clear()
                    rows[pid].update(prepared)
                visitor, owner = rows[actor], rows[target]
                self.service.automatic_production.restore(owner)
                quota, maximum = self.quota(visitor, target), self.limit(visitor)
                counts = {"completecount": float(max(0, maximum - integer(quota.get("complete")))),
                          "acceleratecount": float(max(0, maximum - integer(quota.get("accelerate"))))}
                if name == "visitFriendMap":
                    quota["visited"] = True
                    return {"navigator": copy.deepcopy(owner["navigator"]),
                            "isFirst": False, "reward": {}, "toInbox": {}}
                if name in ("getFriendMap", "getFriendMapData", "getFriendMapData2"):
                    map_data, groups = self.service._map_state(owner)
                    placed = {key: value for key, value in groups["buildings"].items()
                              if value.get("deployedMapKey") == "map001"}
                    groups = {"buildings": placed, "producings": {key: value for key, value in groups["producings"].items() if key in placed}}
                    return {"map": map_data, "buildings": groups["buildings"], "tasks": groups,
                            "producings": groups["producings"], "buildingEvents": {}, "currentMapId": 0.0,
                            "activeMapIds": {"0": "map001"}, "mapProfiles": {"0": {"name": map_data.get("name", "")}},
                            "friendInfo": {}, "isFirst": False, "reward": {}, "toInbox": {}, **counts}
                if name == "building/getFriendProductsByBuilding":
                    return self.products(owner, params)
                key = building_id(params.get("buildingId"))
                if key not in owner["buildings"]:
                    return {"errno": 2.0, **counts}
                engine = self.service._production_for(owner, key)
                _, _, plan, task = engine.active(owner, key)
                now = engine.now()
                if name == "task/completeFriendTasks":
                    if counts["completecount"] <= 0 or now < integer(task["dueTime"], 0, 9007199254740991):
                        return {"errno": 1.0, **counts}
                    result = engine.harvest(owner, [key], point_cost=0)
                    ProductionInventory(self.service).grant(visitor, result[key]["reward"])
                    quota["complete"] += 1
                    return {"producings": result, "autoProducings": {key: copy.deepcopy(owner["produce"][key])}
                            if key in owner["produce"] else {}, "buildingCount": float(len(owner["buildings"])),
                            "completecount": float(maximum - quota["complete"])}
                if counts["acceleratecount"] <= 0 or now >= integer(task["dueTime"], 0, 9007199254740991):
                    return {"errno": 1.0, **counts}
                code = params.get("id")
                rule = self.table("accelerate_produce_task").get(code) if isinstance(code, str) else None
                if not isinstance(rule, dict):
                    raise ValueError("unknown friend production acceleration")
                task["dueTime"] = plan["dueTime"] = float(max(now, task["dueTime"] - integer(rule.get("time"), 1)))
                quota["accelerate"] += 1
                return {"producings": {key: copy.deepcopy(task)}, "acceleratecount": float(maximum - quota["accelerate"])}

            return response_shapes.success(api, self.social.transact((actor, target), action))
        except (ValueError, state.StateConflictError) as exc:
            return self.service._failure(api, str(exc))
