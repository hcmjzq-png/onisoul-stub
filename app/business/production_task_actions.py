"""Owned production cancellation and credit acceleration from PC callbacks."""
from __future__ import annotations

import copy
from functools import partial

from app.business.city_services import CityServices
from app.business.player_services import integer


class ProductionTaskActions(CityServices):
    def register(self, registry) -> None:
        for api, action in (("politic/task/cancelTasks", self.cancel),
                            ("politic/task/accelerateProduceTask", self.accelerate)):
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def cancel(self, player: dict, params: dict) -> dict:
        keys = self.ids(params.get("buildingIds"))
        candidate = copy.deepcopy(player)
        for key in keys:
            engine = self.service._production_for(candidate, key)
            record, row, _, _ = engine.active(candidate, key)
            if row.get("produceType") not in ("manual", "single"):
                raise ValueError("automatic timers stop when the building is put into storage")
            # The original callback only clears production. It neither restores
            # materials/PP nor grants experience or decrements durability.
            del candidate["produce"][key]
            del engine.plans(candidate)[key]
            record["status"] = "waiting"
        player.clear()
        player.update(candidate)
        return {}

    def accelerate(self, player: dict, params: dict) -> dict:
        key, _, _ = self.owned(player, params.get("buildingId"))
        engine = self.service._production_for(player, key)
        _, _, plan, task = engine.active(player, key)
        code = params.get("id")
        row = self.table("accelerate_produce_task").get(code) if isinstance(code, str) else None
        if not isinstance(row, dict):
            raise ValueError("no stub response: unknown production acceleration")
        count = integer(params.get("count", 1), 1)
        credit = integer(integer(row.get("credit"), 1) * count)
        seconds = integer(integer(row.get("time"), 1) * count)
        now = engine.now()
        due = integer(task.get("dueTime"), 0, 9007199254740991)
        if now >= due:
            raise ValueError("production is already ready for harvest")
        box = player["resources"]["credit"]
        if integer(box.get("amount")) < credit:
            raise ValueError("insufficient credits for production acceleration")
        due = float(max(now, due - seconds))
        box["amount"] -= credit
        task["dueTime"] = plan["dueTime"] = due
        return {"producings": {key: copy.deepcopy(task)}, "now": float(now)}
