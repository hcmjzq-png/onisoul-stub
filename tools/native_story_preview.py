"""Read-only chapter and area projections for the isolated PC preview client."""
from __future__ import annotations

from app.business.adventure_services import FLAGS
from app.business.local_quest_menu import LocalQuestMenu
from app.business.player_services import integer


class NativeStoryPreview(LocalQuestMenu):
    def __init__(self, service):
        super().__init__(service)
        index = self.table("quest_1_index")
        self.chapters = {(row["questNo"], row["chapterNo"]): row for row in index.values()
                         if row["enable"] is True and row["clientEnable"] is True}
        self.stories = sorted({quest for quest, _ in self.chapters})

    def complete_flags(self, player, params):
        saved = super().complete_flags(player, params)
        return {self.quest_key("story", quest): saved.get(self.quest_key("story", quest), dict.fromkeys(FLAGS, 0.0))
                for quest in self.stories}

    def reward_flags(self, player, params):
        quest = integer(params.get("questId"))
        if quest == 0:
            return super().reward_flags(player, params)
        if quest not in self.stories:
            raise ValueError("quest is disabled in the client preview")
        return dict.fromkeys(FLAGS, False)

    def chapter(self, player, params):
        quest = integer(params.get("questId"))
        chapter = integer(params.get("chapterId"), 1, 5)
        row = self.chapters.get((quest, chapter))
        if row is None:
            raise ValueError("quest chapter is disabled in the client preview")
        if quest == 0:
            return super().chapter(player, params)

        sections = self.table(self.quest_key("story", quest))
        response = {"complete": 0.0, "clearCount": 0.0}
        for area in range(1, integer(row["areaCount"], 1, 10) + 1):
            first = sections[f"{chapter}_{area}_1"]
            value = {"complete": 0.0, "step": 0.0, "maxStep": float(integer(row[f"areaStep{area}"], 1))}
            for slot in range(1, 5):
                key = f"item{slot}"
                if first.get(key) not in (None, "", "none"):
                    value[key] = {"open": 0.0}
            response[f"area{area}"] = value
        return response
