"""Local-test quest discovery and opening the verified first story chapter."""
from __future__ import annotations

from functools import partial
from typing import Any

from app.business import placeholders, response_shapes
from app.business.adventure_events import AdventureEvents
from app.business.registry import Registry

OPEN_QUEST = "quest/openQuest"
PROGRESS = "quest/getQuestProgress"
FLAGS = "quest/getQuestCompleteFlags"
EVENT_TYPES = frozenset({"event", "event2", "event3"})


class LocalQuestMenu(AdventureEvents):
    def register(self, registry: Registry) -> None:
        registry.register(OPEN_QUEST, self.service._guard(OPEN_QUEST, self.open_quest))
        for api, action in {
            PROGRESS: self.progress,
            FLAGS: self.complete_flags,
            "quest/getChapterData": self.chapter,
            "quest/getQuestRewardOpenFlags": self.reward_flags,
        }.items():
            read = partial(self.read_story, api, action, placeholders.make_handler(api))
            registry.register(api, self.service._guard(api, read))

    def open_quest(self, params: dict, session: dict | None) -> dict:
        kind = params.get("questType")
        if kind == "story":
            return self.call(OPEN_QUEST, self.open_story, params, session)
        if not isinstance(kind, str) or kind not in EVENT_TYPES:
            return placeholders.make_handler(OPEN_QUEST)(params, session)
        if not self.service._player_id(session):
            return self.service._failure(OPEN_QUEST, "authentication required")

        # An empty completion map disables that activity. Closed local schedules
        # do not interrupt the whole quest menu or create any player work.
        return response_shapes.success(OPEN_QUEST, {"questType": kind, "questIds": {}, "addWork": False})

    def read_story(self, api: str, action: Any, fallback: Any,
                   params: dict, session: dict | None) -> dict:
        if api != PROGRESS and params.get("questType") != "story":
            return fallback(params, session)
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        _, player, _ = found
        if api in {PROGRESS, FLAGS} and not (player.get("entity") or {}).get("created"):
            return response_shapes.success(api)
        try:
            if "adventureV1" not in player:
                # The client requests progress before it calls openQuest. Project
                # the same initial chapter on a copy; only explicit open saves it.
                player = dict(player)
                self.open_story(player, {"questType": "story"})
            return response_shapes.success(api, action(player, params))
        except ValueError as exc:
            return self.service._failure(api, str(exc))
