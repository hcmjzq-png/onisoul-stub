"""Resource-only obstacle resolution for trusted, already-generated encounters.

No encounter generator or event scheduler is supplied. All original obstacle
rows found in this bundle belong to disabled events. An explicit server-side
authorizer is mandatory; this module must never enable events from table data.
The internal record/receipt schema and once-per-area restriction are simulator
decisions. They are NOT claims about original server storage or retry behavior.
"""
from __future__ import annotations

import copy
import hashlib
import json
from functools import partial
from typing import Any, Callable

from app.business.adventure_services import AdventureServices, TYPES, mapping
from app.business.player_services import integer


def section_at(rows: dict, chapter: int, area: int, step: int) -> tuple[int, int]:
    """QuestAreaTableAccessor.getSectionId: step is zero-based BEFORE a step."""
    step = integer(step)
    total = 0
    for section in range(1, len(rows) + 1):
        row = rows.get(f"{chapter}_{area}_{section}")
        if not isinstance(row, dict):
            raise ValueError("quest section row not found")
        count = integer(row.get("stepCount"), -1)
        if count < 0 or step + 1 <= total + count:
            return section, step - total
        total += count
    raise ValueError("quest section reference does not cover step")


def displayed_cost(rows: dict, chapter: int, area: int, section: int, correction: int = 0) -> int:
    """QuestStoryAreaConfirm.getCostPoint; preview ONLY, not server MP debit."""
    section = integer(section, 1)
    correction = integer(correction)
    for number in range(section, 0, -1):
        row = rows.get(f"{chapter}_{area}_{number}")
        if not isinstance(row, dict):
            raise ValueError("quest cost section row not found")
        value = row.get("cost")
        if value == "":
            continue
        cost = integer(value, -1)
        if cost >= 0:
            return cost + correction
    return -1


class AdventureObstacleServices(AdventureServices):
    def __init__(self, service: Any, *, authorize: Callable[[dict, dict], bool] | None = None) -> None:
        super().__init__(service)
        self.authorize = authorize

    def register(self, registry: Any) -> None:
        for name, action in {"getQuestEncountWorks": self.works, "clearObstacle": self.clear}.items():
            api = "quest/" + name
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    @staticmethod
    def key(kind: str, quest: int, chapter: int, area: int) -> str:
        return f"{kind}:{quest}:{chapter}:{area}"

    def checked(self, player: dict, key: str, event: Any) -> tuple[dict, dict, str]:
        event = mapping(event)
        kind = self.quest_type(event)
        quest = integer(event.get("quest"))
        chapter = integer(event.get("chapter"), 1, 5)
        area = integer(event.get("area"), 1, 10)
        step = integer(event.get("step"))
        if key != self.key(kind, quest, chapter, area):
            raise ValueError("obstacle location mismatch")
        if not isinstance(event.get("eventId"), str) or not event["eventId"]:
            raise ValueError("trusted obstacle instance id required")
        if event.get("status") not in ("pending", "cleared"):
            raise ValueError("invalid obstacle state")
        if self.authorize is None or self.authorize(copy.deepcopy(player), copy.deepcopy(event)) is not True:
            raise ValueError("no stub response: trusted event authorization required")
        # Authorization decides live event access; bundle enable/1999 dates do not.
        row = self.table(f"quest_{TYPES[kind]}_index").get(f"{quest}_{chapter}")
        if not isinstance(row, dict):
            raise ValueError("quest index row not found")
        if area > integer(row.get("areaCount"), 1, 10):
            raise ValueError("obstacle area outside index")
        maximum = integer(row.get(f"areaStep{area}"), -1)
        if maximum >= 0 and step > maximum:
            raise ValueError("obstacle step outside index")
        resolution = mapping(event.get("resolution"))
        # Explicit empty disposition from trusted producer, never absence => no reward.
        if resolution.get("reward") != {} or resolution.get("toInbox") != {}:
            raise ValueError("no stub response: reward-bearing/unknown obstacle settlement")
        resource = resolution.get("type")
        if resolution.get("category") != "resource" or resource not in ("gold", "food", "wood", "iron"):
            raise ValueError("no stub response: only resource obstacles supported")
        amount = integer(resolution.get("needAmount"), 1)
        # Compare trusted cost with original row, rather than derive a fee from a guess.
        rows = self.table(self.quest_key(kind, quest))
        section = integer(event.get("section"), 1)
        slot = integer(event.get("eventSlot"), 1, 15)
        source = rows.get(f"{chapter}_{area}_{section}")
        if not isinstance(source, dict):
            raise ValueError("quest obstacle section reference not found")
        param = source.get(f"event{slot}")
        if not isinstance(param, list) or len(param) != 7 or param[1] != 10 or param[4:] != ["resource", resource, amount]:
            raise ValueError("trusted obstacle cost disagrees with original row")
        # Resolve a persisted post-step event against its original originating section.
        if step < 1 or section_at(rows, chapter, area, step - 1)[0] != section:
            raise ValueError("obstacle section disagrees with saved step")
        contract = {k: v for k, v in event.items() if k != "status"}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return event, resolution, digest

    def works(self, player: dict, params: dict) -> dict:
        kind = self.quest_type(params)
        quest = integer(params.get("questId"))
        events = mapping(self.snapshot(player).get("obstacles"))
        matches = []
        for key, event in events.items():
            event = mapping(event)
            if event.get("questType") != kind or event.get("quest") != quest:
                continue
            event, resolution, _ = self.checked(player, key, event)
            if event["status"] == "cleared":
                continue
            amount = integer(mapping(mapping(player.get("resources")).get(resolution["type"])).get("amount"))
            matches.append({"questId": self.quest_key(kind, quest),
                            **{field: float(event[field]) for field in ("chapter", "area", "step")},
                            "category": "resource", "type": resolution["type"],
                            "needAmount": float(resolution["needAmount"]), "amount": float(amount)})
        if len(matches) > 1:
            raise ValueError("no stub response: multiple pending obstacles for one quest type")
        return {"obstacle": {kind: matches[0]} if matches else {}}

    def clear(self, player: dict, params: dict) -> dict:
        kind = self.quest_type(params)
        quest = integer(params.get("questId"))
        chapter = integer(params.get("chapterId"), 1, 5)
        area = integer(params.get("areaId"), 1, 10)
        saved = self.snapshot(player)
        key = self.key(kind, quest, chapter, area)
        event, resolution, digest = self.checked(player, key, mapping(saved.get("obstacles")).get(key))
        receipts = mapping(saved.get("obstacleReceipts"))
        if key in receipts:
            receipt = mapping(receipts[key])
            if receipt.get("digest") != digest or event["status"] != "cleared":
                # Request has no encounter id. Never charge a replacement on an old retry.
                raise ValueError("no stub response: obstacle area already resolved; replacement unsupported")
            return copy.deepcopy(mapping(receipt.get("response")))
        if event["status"] != "pending":
            raise ValueError("cleared obstacle has no settlement receipt")
        last = mapping(mapping(mapping(saved.get("progress")).get(kind)).get("last"))
        if any(last.get(field) != event[field] for field in ("quest", "chapter", "area", "step")):
            raise ValueError("obstacle is not at player's current location")
        box = mapping(mapping(player.get("resources")).get(resolution["type"]))
        balance, cost = integer(box.get("amount")), integer(resolution["needAmount"], 1)
        if balance < cost:
            return {"isSuccess": False}
        response = {"isSuccess": True, "uses": {"category": "resource", resolution["type"]: float(cost)}}
        # One player save persists balance, state, and replay receipt together.
        box["amount"] = float(balance - cost)
        event["status"] = "cleared"
        receipts[key] = {"digest": digest, "response": copy.deepcopy(response)}
        return response
