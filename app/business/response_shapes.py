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
    INDEXED_ROWS = "indexed_rows"


# Each entry is backed by a callback that enumerates the response root and casts
# every value to Hashtable (or to double for getSouls). Empty maps are valid
# "no records" placeholders where the corresponding consumer permits them.
# Shared enumerators are allowed when several endpoints consume through the same
# helper: `DeckConflateCards.createStatus` is used by common/getCharacters,
# common/getEquips and common/getTactics.
BARE_MAP_EVIDENCE: dict[str, str] = {
    "deck/getCharactersInStore": "DeckConflateCards_StrageCharacter.cs:setup",
    "auction/auctionCardSale": "AuctionDataManager.cs:OnGetMySellingCards@0x294278",
    "auction/auctionResourceSale": "AuctionDataManager.cs:OnGetMySellingResources@0x2951B8",
    "common/getCharacters": "DeckConflateCards.cs:createStatus@0x2F04E8",
    "common/getEquips": "DeckConflateCards.cs:createStatus@0x2F04E8",
    "common/getSelectCharacters": "QuestDataCache.cs:calcDeckParameter@0x242F4C",
    "common/getTactics": "DeckConflateCards.cs:createStatus@0x2F04E8",
    "dailymission/getDailyMission": "DailyMissionScene.cs:Start@0x2DD6DC",
    "deck/getAvatarCharacters": "Politic.cs:resetMap@0x205930",
    "deck/getProtectedCharacterIds": "DeckScene.cs:OnEnable@0x300FE0",
    "deck/getProtectedEquipIds": "DeckScene.cs:OnEnable@0x300FE0",
    "deck/setCharacterProtect": "CharacterConflatePreview_Character.cs:protectOrRelease@0x2EA4F4",
    "deck/setDecks": "DeckMake.cs:deckSave@0x2F8508",
    "deck/setEquipProtect": "CharacterConflatePreview_Equip.cs:protectOrRelease@0x2EAA64",
    "friend/findFriends": "FriendListWindow.cs:getFindData@0x30D6E8",
    "friend/getFriends": "FriendListWindow.cs:getFriendData@0x30D6A8",
    "politic/building/getDrafts": "UserStatus.cs:setDraftInfo@0x28FE58",
    "politic/lottery/getSouls": "onikujiWork.cs:initSoul:199-206 (root values cast to double)",
    # UserStatus.cs:1393 的 ymbga 分支要求 Keys.Count == 1 且读 succeeded，
    # :1401 的非 ymbga 分支要求 Keys.Count == 0。运行时容器由 gameLogin 响应的
    # `container` 决定（SessionKeeper.cs:138-141 -> Configs.cs:1317，未知值回落 none），
    # 本 Stub 固定回 "container": "none"，所以生效的是非 ymbga 分支：回 `{}` 判成功。
    "politic/map/setMapName2": "UserStatus.cs:setMapName@0x28F970",
    "politic/waterborneTrade/getStatus": "PoliticMissionProgressList.cs:updateWaterTradeList@0x2302C0",
    "quest/checkEmergencyQuest": "EmergencyQuestChecker.cs:sendRequest@0x2413CC",
    "quest/getQuestCompleteFlags": "PluginQuestDataManager.cs:onGetStoryProgress@0x1FA5BC",
    "quest/getQuestProgress": "QuestDataCache.cs:setQuestParameter@0x243180",
    "trophy/getTrophyProgress": "TrophyWindow.cs:load; mypageTrophyUpdate.cs:OnEnable (root rows)",
}

BARE_MAP_ENDPOINTS = frozenset(BARE_MAP_EVIDENCE)

# These callbacks read named keys from the response root and unbox scalar
# values. They must keep the normal envelope and typed contract placeholders.
# This mapping is evidence bookkeeping only: `shape_for()` decides by
# `BARE_MAP_ENDPOINTS`, and everything outside it already defaults to envelope.
SCALAR_ROOT_EVIDENCE: dict[str, str] = {
    "politic/support_item/usePotions": "DailyMissionScene.cs:convertRewardByUsePotionsAPIResult@0x2DE10C",
    "quest/getChapterData": "PluginRunner_DoEvent.cs:onQuestChapterData@0x1FD48C",
    "siege/getBrief": "siegeBriefMenuDesc.cs:setup@0x347618",
    "siege/getSiegeStatus": "vsSetting_Siege.cs:getSiegeSituation@0x34FB10",
}


def shape_for(api: str) -> ResponseShape:
    # PoliticBuilding.SerialBuildAndComplete iterates 0..Count-3 and reads
    # autoProducings. Exactly two metadata keys are allowed. Retain now, omit
    # succeeded; this is a consumer-compatible shape, not an original capture.
    if api == "politic/task/submitSerialBuildAndComplete":
        return ResponseShape.INDEXED_ROWS
    if api in BARE_MAP_ENDPOINTS:
        return ResponseShape.BARE_MAP
    return ResponseShape.ENVELOPE


def success(api: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return endpoint data in the shape required by its client callback."""
    body = dict(payload or {})
    if shape_for(api) is ResponseShape.BARE_MAP:
        return body
    if shape_for(api) is ResponseShape.INDEXED_ROWS:
        result = envelope.ok(body)
        if result.get("succeeded") is True:
            result.pop("succeeded", None)
        return result
    return envelope.ok(body)
