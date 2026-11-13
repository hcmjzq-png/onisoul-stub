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
    "auction/auctionCardSale": "AuctionDataManager.cs:GetMySellingCardsFromServer",
    "auction/auctionResourceSale": "AuctionDataManager.cs:GetMySellingResourceFromServer",
    "common/getCharacters": "DeckConflateCards.cs:createStatus",
    "common/getEquips": "DeckConflateCards_Equip.cs:setup",
    "common/getSelectCharacters": "QuestDataCache.cs:calcDeckParameter",
    "common/getTactics": "DeckConflateCards_Tactics.cs:setup",
    "dailymission/getDailyMission": "DailyMissionScene.cs:Start",
    "deck/getProtectedCharacterIds": "DeckScene.cs:OnEnable",
    "deck/getProtectedEquipIds": "DeckScene.cs:OnEnable",
    "deck/setCharacterProtect": "CharacterConflatePreview_Character.cs:protectOrRelease",
    "deck/setDecks": "DeckMake.cs:deckSave",
    "deck/setEquipProtect": "CharacterConflatePreview_Equip.cs:protectOrRelease",
    "friend/findFriends": "FriendListWindow.cs:getFindData",
    "friend/getFriends": "FriendListWindow.cs:getFriendData",
    "politic/building/getDrafts": "UserStatus.cs:setDraftInfo",
    "politic/support_item/usePotions": "PoliticItemInventory.cs:useItem",
    "politic/waterborneTrade/getStatus": "PoliticMissionProgressList.cs:updateWaterTradeList",
    "quest/checkEmergencyQuest": "EmergencyQuestChecker.cs:sendRequest",
    "quest/getChapterData": "PluginQuestDataManager.cs:onGetStoryProgress",
    "quest/getQuestCompleteFlags": "PluginQuestDataManager.cs:onGetStoryProgress",
    "quest/getQuestProgress": "QuestDataCache.cs:setQuestParameter",
}

BARE_MAP_ENDPOINTS = frozenset(BARE_MAP_EVIDENCE)

# These callbacks read named keys from the response root and unbox scalar
# values. They must keep the normal envelope and typed contract placeholders.
SCALAR_ROOT_EVIDENCE: dict[str, str] = {
    "deck/getAvatarCharacters": "PoliticAvatorCache.cs:setup",
    "siege/getBrief": "siegeBriefMenuDesc.cs:setup",
    "siege/getSiegeStatus": "vsSetting_Siege.cs:getSiegeSituation",
    "trophy/getTrophyProgress": "TrophyWindow.cs:load",
}


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
