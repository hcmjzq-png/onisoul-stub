"""A-owned subcity/background adapter; no default map or entitlement producer.

The original po_mission_00281 (index 306) gates mapId=1. Trusted B/G/map
providers remain integration dependencies. None is a closed gate, never True.
citySubcityAccessV1 is a server-internal receipt, not an original wire field.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from app.business.city_production_services import CityProductionServices
from app.business.economy_shop_services import EconomyShopServices
from app.business.player_services import integer


@dataclass(frozen=True)
class SubcityFacts:
    """One locked player snapshot from B's completion and G's kokudaka sources.

    The map provider must return the player's already materialized original map,
    including its name, size and occupiedGrids. This class does not generate it.
    """

    player_id: str
    story_quest: int
    story_chapter: int
    story_complete: int
    kokudaka: int
    map_key: str
    map_data: dict


@dataclass(frozen=True)
class SubcityRule:
    mission: str
    index: str
    minimum_level: int
    quest: int
    chapter: int
    minimum_kokudaka: int

    @classmethod
    def from_table(cls, rows: dict) -> SubcityRule:
        code = "po_mission_00281"
        row = rows.get(code)
        if not isinstance(row, dict):
            raise ValueError("no stub response: original subcity mission row missing")
        expected = {
            "bootCheckFunc": "player_level", "missionType": "clientCheck",
            "target": "all", "needClearCount": 2, "conditionCount1": 1,
            "conditionTypes1": ["storyQuestClear"], "conditionCheckers1": ["eq_greater_than"],
            "conditionArgs1": [1], "conditionCount2": 1,
            "conditionTypes2": ["getKokudaka"], "conditionGrades2": ["any"],
            "conditionLevels2": ["any"], "conditionTargets2": ["any"],
            "conditionCheckers2": ["eq_greater_than"], "conditionCount3": 0,
            "clearUnlocks": ["unlockChangeMap"],
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("no stub response: unsupported subcity mission conditions")

        def text_integer(field: str) -> int:
            value = row.get(field)
            if (not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str)
                    or not value[0].isascii() or not value[0].isdecimal()):
                raise ValueError("no stub response: invalid subcity condition")
            return integer(int(value[0]), 1)

        amount = row.get("conditionArgs2")
        if not isinstance(amount, list) or len(amount) != 1:
            raise ValueError("no stub response: invalid subcity kokudaka condition")
        # gafIsClearQuest parses conditionTargets1 but does not use it in the
        # predicate: it tests QUEST/CHAPTER completion, not area 10 alone.
        text_integer("conditionTargets1")
        return cls(code, str(integer(row.get("index"), 1)), text_integer("bootCheckData"),
                   text_integer("conditionGrades1"), text_integer("conditionLevels1"), integer(amount[0], 1))

    def qualifies(self, level: Any, facts: SubcityFacts) -> bool:
        if not isinstance(facts, SubcityFacts):
            raise ValueError("no stub response: structured authoritative subcity facts required")
        quest, chapter = integer(facts.story_quest, 1), integer(facts.story_chapter, 1, 5)
        complete = integer(facts.story_complete, 0, 1)
        score = integer(facts.kokudaka)
        if (quest, chapter) != (self.quest, self.chapter):
            raise ValueError("no stub response: wrong story completion for subcity")
        return integer(level, 1) >= self.minimum_level and complete == 1 and score >= self.minimum_kokudaka


class CityBackgroundServices(CityProductionServices):
    """Four background endpoints share actual access, purchases and selection.

    acquire_facts MUST read B/G and an existing map under the player's lock.
    The normal registry supplies no such provider, so these stay unmounted.
    Static sales are an explicit simulator policy, not a recovered schedule.
    """

    def __init__(self, service: Any, *, acquire_facts: Callable[[dict], SubcityFacts] | None = None,
                 static_background_sales: bool = False) -> None:
        super().__init__(service)
        self.acquire_facts = acquire_facts
        self.shop = EconomyShopServices(service, static_background_sales=static_background_sales)

    def register(self, registry: Any, *, apis: frozenset[str]) -> None:
        for api, action in {
            "politic/map/getBackgrounds": self.backgrounds,
            "politic/map/setBackground": self.set_background,
            "politic/shop/getBackgroundItems": self.background_items,
            "politic/shop/buyBackgroundItem": self.buy_background,
        }.items():
            if api in apis:
                registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def require_subcity(self, player: dict) -> None:
        if self.acquire_facts is None:
            raise ValueError("no stub response: authoritative B/G/subcity map providers are not integrated")
        if (player.get("entity") or {}).get("created") is not True:
            raise ValueError("created player required")
        rule = SubcityRule.from_table(self.table("politicMission"))
        facts = self.acquire_facts(player)
        if not isinstance(facts, SubcityFacts) or facts.player_id != player["entity"].get("playerId"):
            raise ValueError("no stub response: invalid subcity facts owner")
        if player.get("missions", {}).get(rule.index) != "C":
            raise ValueError("no stub response: subcity mission is not closed")
        # map1 is independently visible in UserStatus.cs:1359. Do not alias map001.
        data = facts.map_data
        if (facts.map_key != "map1" or not isinstance(data, dict)
                or not isinstance(data.get("name"), str) or not data["name"]
                or data.get("size") != {"width": 40, "height": 40}
                or not isinstance(data.get("occupiedGrids"), dict)):
            raise ValueError("no stub response: verified existing subcity map required")
        proof = player.get("citySubcityAccessV1")
        if proof is None:
            if not rule.qualifies(player["entity"].get("level"), facts):
                raise ValueError("no stub response: subcity conditions not satisfied")
            player["citySubcityAccessV1"] = {
                "version": 1, "playerId": facts.player_id, "mission": rule.mission,
                "mapKey": facts.map_key, "level": integer(player["entity"]["level"], 1),
                "quest": facts.story_quest, "chapter": facts.story_chapter,
                "complete": facts.story_complete, "kokudaka": facts.kokudaka,
            }
        else:
            if (not isinstance(proof, dict) or type(proof.get("version")) is not int or proof["version"] != 1
                    or proof.get("playerId") != facts.player_id or proof.get("mission") != rule.mission
                    or proof.get("mapKey") != facts.map_key):
                raise ValueError("no stub response: invalid subcity access receipt")
            witnessed = SubcityFacts(facts.player_id, proof.get("quest"), proof.get("chapter"),
                                    proof.get("complete"), proof.get("kokudaka"), facts.map_key, data)
            if not rule.qualifies(proof.get("level"), witnessed):
                raise ValueError("no stub response: invalid subcity access conditions")
        # Unlock is latched. Moving/storing buildings later must not revoke it.
        # Never trust unlockBits or a bare legacy mission C without a fresh proof.

    def background_items(self, player: dict, params: dict) -> dict:
        self.require_subcity(player)
        return self.shop.background_items(player, params)

    def buy_background(self, player: dict, params: dict) -> dict:
        self.require_subcity(player)
        return self.shop.buy_background(player, params)

    def map_profile(self, player: dict) -> dict:
        """getMapData.mapProfiles['1'] projection, to be connected by integration.

        No default background items, map grids or mission state are created.
        """
        self.require_subcity(player)
        facts = self.acquire_facts(player)
        return {"name": (player.get("mapNames") or {}).get("1", facts.map_data["name"]),
                **copy.deepcopy(self.selected_background(player, 1))}
