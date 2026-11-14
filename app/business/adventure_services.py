"""Read verified quest snapshots; no quest initialization, combat or rewards.

``adventureV1`` is a proposed SERVER-INTERNAL save schema, not original wire
protocol. A trusted producer/migration must supply it before these APIs work.
Nothing registers this module in production. See the B integration notes.
"""
from __future__ import annotations

from functools import partial
from typing import Any

from app.business.player_services import PlayerServices, integer


TYPES = {"story": 1, "random": 2, "event": 3, "random2": 4, "event2": 5, "event3": 6}
FLAGS = {f"chapter{i}" for i in range(1, 6)}


def mapping(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("no stub response: missing or invalid adventure snapshot")
    return value


class AdventureServices(PlayerServices):
    """Uses PlayerServices authentication, save path and GameplayService lock."""

    def register(self, registry: Any) -> None:
        for name, action in {
            "getQuestProgress": self.progress,
            "getChapterData": self.chapter,
            "getQuestCompleteFlags": self.complete_flags,
            "getQuestRewardOpenFlags": self.reward_flags,
        }.items():
            api = "quest/" + name
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    @staticmethod
    def snapshot(player: dict) -> dict:
        if not (player.get("entity") or {}).get("created"):
            raise ValueError("created player required")
        saved = mapping(player.get("adventureV1"))
        if type(saved.get("version")) is not int or saved["version"] != 1:
            raise ValueError("no stub response: unsupported adventure snapshot version")
        return saved

    @staticmethod
    def quest_type(params: dict) -> str:
        kind = params.get("questType")
        if not isinstance(kind, str) or kind not in TYPES:
            raise ValueError("invalid questType")
        return kind

    @staticmethod
    def quest_key(kind: str, quest: int) -> str:
        return f"quest_{TYPES[kind]}_{quest:04d}"

    def index_row(self, kind: str, quest: int, chapter: int) -> dict:
        rows = self.table(f"quest_{TYPES[kind]}_index")
        row = rows.get(f"{quest}_{chapter}")
        if not isinstance(row, dict):
            # Existing table + absent row is a reference/ID error, not a missing asset.
            raise ValueError("quest index row not found")
        if row.get("enable") is not True or row.get("clientEnable") is not True:
            raise ValueError("quest chapter is disabled in client table")
        return row

    def location(self, kind: str, value: Any) -> dict:
        value = mapping(value)
        quest = integer(value.get("quest"))
        chapter = integer(value.get("chapter"), 1, 5)
        row = self.index_row(kind, quest, chapter)
        area = integer(value.get("area"), 1, integer(row.get("areaCount"), 1, 10))
        step = integer(value.get("step"), 0, integer(row.get(f"areaStep{area}")))
        return {"quest": float(quest), "chapter": float(chapter),
                "area": float(area), "step": float(step)}

    def progress(self, player: dict, params: dict) -> dict:
        records = mapping(self.snapshot(player).get("progress"))
        # No default 0/1 starting position: the original server initialization is unknown.
        if "story" not in records or any(kind not in TYPES for kind in records):
            raise ValueError("no stub response: verified story progress required")
        result = {}
        for kind, record in records.items():
            record = mapping(record)
            result[kind] = {"last": self.location(kind, record.get("last"))}
            if kind == "story":
                result[kind]["current"] = self.location(kind, record.get("current"))
        return result

    def quest_record(self, player: dict, kind: str, quest: int) -> dict:
        self.index_row(kind, quest, 1)
        records = mapping(self.snapshot(player).get("quests"))
        key = self.quest_key(kind, quest)
        if key not in records:
            raise ValueError("no stub response: quest has no verified saved record")
        return mapping(records[key])

    @staticmethod
    def flags(record: dict, field: str) -> dict:
        values = mapping(record.get(field))
        # PluginQuestDataManager reads all five fields even for short quests.
        if set(values) != FLAGS:
            raise ValueError("no stub response: five explicit chapter flags required")
        if field == "rewardOpenFlags":
            if any(type(value) is not bool for value in values.values()):
                raise ValueError("reward-open flags must be boolean")
            return dict(values)
        return {key: float(integer(value, 0, 1)) for key, value in values.items()}

    def complete_flags(self, player: dict, params: dict) -> dict:
        kind = self.quest_type(params)
        records = mapping(self.snapshot(player).get("quests"))
        result = {}
        prefix = f"quest_{TYPES[kind]}_"
        for key, record in records.items():
            if not isinstance(key, str):
                raise ValueError("invalid saved quest key")
            if not key.startswith(prefix):
                continue
            suffix = key[len(prefix):]
            if not suffix.isascii() or not suffix.isdecimal():
                raise ValueError("invalid saved quest key")
            quest = integer(int(suffix))
            if key != self.quest_key(kind, quest):
                raise ValueError("noncanonical saved quest key")
            self.index_row(kind, quest, 1)
            result[key] = self.flags(mapping(record), "completeFlags")
        return result

    def reward_flags(self, player: dict, params: dict) -> dict:
        kind = self.quest_type(params)
        record = self.quest_record(player, kind, integer(params.get("questId")))
        return self.flags(record, "rewardOpenFlags")

    def chapter(self, player: dict, params: dict) -> dict:
        kind = self.quest_type(params)
        quest = integer(params.get("questId"))
        chapter = integer(params.get("chapterId"), 1, 5)
        record = self.quest_record(player, kind, quest)
        row = self.index_row(kind, quest, chapter)
        saved = mapping(mapping(record.get("chapters")).get(str(chapter)))
        complete = integer(saved.get("complete"), 0, 1)
        if complete != self.flags(record, "completeFlags")[f"chapter{chapter}"]:
            raise ValueError("inconsistent saved chapter completion")
        result = {"complete": float(complete), "clearCount": float(integer(saved.get("clearCount")))}
        areas = mapping(saved.get("areas"))
        count = integer(row.get("areaCount"), 1, 10)
        if set(areas) != {str(i) for i in range(1, count + 1)}:
            raise ValueError("no stub response: incomplete saved area records")
        for area in range(1, count + 1):
            value = mapping(areas[str(area)])
            maximum = integer(row.get(f"areaStep{area}"))
            output = {"complete": float(integer(value.get("complete"), 0, 1)),
                      "step": float(integer(value.get("step"), 0, maximum)),
                      "maxStep": float(maximum)}
            # Optional items are emitted only when explicitly saved; never fabricate rewards.
            items = mapping(value.get("items", {}))
            if any(key not in {"1", "2", "3", "4"} for key in items):
                raise ValueError("invalid saved area item slot")
            for key, opened in items.items():
                output[f"item{key}"] = {"open": float(integer(opened, 0, 1))}
            result[f"area{area}"] = output
        return result
