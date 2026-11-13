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
    EXACT = "exact"


# Each entry is backed by a callback that enumerates the response root and casts
# every value to Hashtable. Empty maps are valid "no records" placeholders.
# Shared enumerators are allowed when several endpoints consume through the same
# helper: `DeckConflateCards.createStatus` is used by common/getCharacters,
# common/getEquips and common/getTactics.
BARE_MAP_EVIDENCE: dict[str, str] = {
    "auction/auctionCardSale": "AuctionDataManager.cs:OnGetMySellingCards",
    "auction/auctionResourceSale": "AuctionDataManager.cs:OnGetMySellingResources",
    "common/getCharacters": "DeckConflateCards.cs:createStatus",
    "common/getEquips": "DeckConflateCards.cs:createStatus",
    "common/getSelectCharacters": "QuestDataCache.cs:calcDeckParameter",
    "common/getTactics": "DeckConflateCards.cs:createStatus",
    "dailymission/getDailyMission": "DailyMissionScene.cs:Start",
    "deck/getAvatarCharacters": "Politic.cs:resetMap",
    "deck/getProtectedCharacterIds": "DeckScene.cs:OnEnable",
    "deck/getProtectedEquipIds": "DeckScene.cs:OnEnable",
    "deck/setCharacterProtect": "CharacterConflatePreview_Character.cs:protectOrRelease",
    "deck/setDecks": "DeckMake.cs:deckSave",
    "deck/setEquipProtect": "CharacterConflatePreview_Equip.cs:protectOrRelease",
    "friend/findFriends": "FriendListWindow.cs:getFindData",
    "friend/getFriends": "FriendListWindow.cs:getFriendData",
    "politic/building/getDrafts": "UserStatus.cs:setDraftInfo",
    "politic/waterborneTrade/getStatus": "PoliticMissionProgressList.cs:updateWaterTradeList",
    "quest/checkEmergencyQuest": "EmergencyQuestChecker.cs:sendRequest",
    "quest/getQuestCompleteFlags": "PluginQuestDataManager.cs:onGetStoryProgress",
    "quest/getQuestProgress": "QuestDataCache.cs:setQuestParameter",
}

BARE_MAP_ENDPOINTS = frozenset(BARE_MAP_EVIDENCE)

# These callbacks read named keys from the response root and unbox scalar
# values. They must keep the normal envelope and typed contract placeholders.
# This mapping is evidence bookkeeping only: `shape_for()` decides by
# `BARE_MAP_ENDPOINTS`, and everything outside it already defaults to envelope.
SCALAR_ROOT_EVIDENCE: dict[str, str] = {
    "politic/support_item/usePotions": "DailyMissionScene.cs:convertRewardByUsePotionsAPIResult",
    "quest/getChapterData": "PluginRunner_DoEvent.cs:onQuestChapterData",
    "siege/getBrief": "siegeBriefMenuDesc.cs:setup",
    "siege/getSiegeStatus": "vsSetting_Siege.cs:getSiegeSituation",
    "trophy/getTrophyProgress": "TrophyWindow.cs:load",
}


# 少数回调按「根键个数」判定成功，多注入一个 `now` 就走失败分支：
#   UserStatus.cs:1393（ymbga）要求 Keys.Count == 1 且 succeeded == true；
#   UserStatus.cs:1401（非 ymbga）要求 Keys.Count == 0。
# 两者无法同时满足，取唯一不崩的公共解：只回 `succeeded`（ymbga 分支能读、
# 非 ymbga 分支只数个数），并因此不注入 `now`。
EXACT_BODY_EVIDENCE: dict[str, str] = {
    "politic/map/setMapName2": "UserStatus.cs:1379-1403",
}

EXACT_BODY_ENDPOINTS = frozenset(EXACT_BODY_EVIDENCE)


def shape_for(api: str) -> ResponseShape:
    if api in BARE_MAP_ENDPOINTS:
        return ResponseShape.BARE_MAP
    if api in EXACT_BODY_ENDPOINTS:
        return ResponseShape.EXACT
    return ResponseShape.ENVELOPE


def success(api: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return endpoint data in the shape required by its client callback."""
    body = dict(payload or {})
    if shape_for(api) is ResponseShape.BARE_MAP:
        return body
    if shape_for(api) is ResponseShape.EXACT:
        exact = {"succeeded": True}
        exact.update(body)
        return exact
    return envelope.ok(body)
