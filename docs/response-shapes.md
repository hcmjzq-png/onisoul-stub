# 响应根形态

`app/business/response_shapes.py` 区分两类接口响应。普通接口使用
`{succeeded, now, ...}` 信封；裸映射接口的根表会被客户端逐项遍历，每一项再
`castclass Hashtable`，因此根上不能出现 `succeeded`（bool）或 `now`（double）。

空映射 `{}` 是“当前没有任何记录”的有效占位，不会进入遍历分支。

## 已登记的裸映射接口

| 接口 | 客户端读取点 |
|---|---|
| `auction/auctionCardSale` | `AuctionDataManager.cs:GetMySellingCardsFromServer` |
| `auction/auctionResourceSale` | `AuctionDataManager.cs:GetMySellingResourceFromServer` |
| `common/getCharacters` | `DeckConflateCards.cs:createStatus` |
| `common/getEquips` | `DeckConflateCards_Equip.cs:setup` |
| `common/getSelectCharacters` | `QuestDataCache.cs:calcDeckParameter` |
| `common/getTactics` | `DeckConflateCards_Tactics.cs:setup` |
| `dailymission/getDailyMission` | `DailyMissionScene.cs:Start` |
| `deck/getProtectedCharacterIds` | `DeckScene.cs:OnEnable` |
| `deck/getProtectedEquipIds` | `DeckScene.cs:OnEnable` |
| `deck/setCharacterProtect` | `CharacterConflatePreview_Character.cs:protectOrRelease` |
| `deck/setDecks` | `DeckMake.cs:deckSave` |
| `deck/setEquipProtect` | `CharacterConflatePreview_Equip.cs:protectOrRelease` |
| `friend/findFriends` | `FriendListWindow.cs:getFindData` |
| `friend/getFriends` | `FriendListWindow.cs:getFriendData` |
| `politic/building/getDrafts` | `UserStatus.cs:setDraftInfo` |
| `politic/support_item/usePotions` | `PoliticItemInventory.cs:useItem` |
| `politic/waterborneTrade/getStatus` | `PoliticMissionProgressList.cs:updateWaterTradeList` |
| `quest/checkEmergencyQuest` | `EmergencyQuestChecker.cs:sendRequest` |
| `quest/getChapterData` | `PluginQuestDataManager.cs:onGetStoryProgress` |
| `quest/getQuestCompleteFlags` | `PluginQuestDataManager.cs:onGetStoryProgress` |
| `quest/getQuestProgress` | `QuestDataCache.cs:setQuestParameter` |

依据来自客户端反编译回调的方法体，不在本 PR 中扩展未经证实的接口。新增裸映射
接口时必须先补客户端读取点，再加入 `BARE_MAP_EVIDENCE`。

## 不是裸映射

以下端点的契约键位于根级，回调按 key 读取并拆箱，而不是遍历根表。它们继续使用
envelope 和类型化占位字段：

- `deck/getAvatarCharacters`：`PoliticAvatorCache.cs:setup` 读取 `baseId`、`grade`、`voice`。
- `siege/getBrief`：`siegeBriefMenuDesc.cs:setup` 读取 `day`、`stage`、`isEntry`、
  `winner` 等键。
- `siege/getSiegeStatus`：`vsSetting_Siege.cs:getSiegeSituation` 读取 `selfDeck`、
  `costs`、`rival`、`record` 等键。
- `trophy/getTrophyProgress`：`TrophyWindow.cs:load` 读取根级 `level`、`status` 等键。
