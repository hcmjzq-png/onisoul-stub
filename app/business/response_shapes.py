"""Response shapes that the PC client expects from individual endpoints.

Most endpoints share the ``{succeeded, now, ...}`` envelope. A verified set of
endpoints instead walks every value in the response root and casts it to a
Hashtable. Those endpoints must return a bare map, without scalar envelope keys
such as ``succeeded`` (bool) or ``now`` (double).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from app.protocol import envelope


class ResponseShape(str, Enum):
    ENVELOPE = "envelope"
    BARE_MAP = "bare_map"


# Each entry is backed by a callback that enumerates the response root and casts
# every value to Hashtable. Empty maps are valid "no records" placeholders.
BARE_MAP_EVIDENCE: dict[str, str] = {
    "auction/auctionCardSale": "客户端枚举响应根表",
    "auction/auctionResourceSale": "客户端枚举响应根表",
    "common/getCharacters": "DeckConflateCards.createStatus",
    "common/getEquips": "客户端枚举响应根表",
    "common/getSelectCharacters": "QuestDataCache.calcDeckParameter",
    "common/getTactics": "客户端枚举响应根表",
    "dailymission/getDailyMission": "每日任务回调两层枚举响应",
    "deck/getAvatarCharacters": "PoliticAvatorCache.setup",
    "deck/getProtectedCharacterIds": "客户端枚举响应根表",
    "deck/getProtectedEquipIds": "客户端枚举响应根表",
    "deck/setCharacterProtect": "客户端枚举响应根表",
    "deck/setDecks": "DeckMake.deckSave 以 Count 判定成功",
    "deck/setEquipProtect": "客户端枚举响应根表",
    "friend/findFriends": "客户端枚举响应根表",
    "friend/getFriends": "客户端枚举响应根表",
    "politic/building/getDrafts": "UserStatus.setDraftInfo",
    "politic/support_item/usePotions": "客户端枚举响应根表",
    "politic/waterborneTrade/getStatus": "PoliticMissionProgressList.updateWaterTradeList",
    "quest/checkEmergencyQuest": "EmergencyQuestChecker.sendRequest",
    "quest/getChapterData": "PluginQuestDataManager.onGetStoryProgress",
    "quest/getQuestCompleteFlags": "PluginQuestDataManager.onGetStoryProgress",
    "quest/getQuestProgress": "QuestDataCache.setQuestParameter",
    "siege/getSiegeStatus": "客户端枚举响应根表",
}

BARE_MAP_ENDPOINTS = frozenset(BARE_MAP_EVIDENCE)


def shape_for(api: str) -> ResponseShape:
    if api in BARE_MAP_ENDPOINTS:
        return ResponseShape.BARE_MAP
    return ResponseShape.ENVELOPE


def success(api: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return endpoint data in the shape required by its client callback."""
    body = dict(payload or {})
    if shape_for(api) is ResponseShape.BARE_MAP:
        return body
    return envelope.ok(body)
