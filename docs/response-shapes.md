# 响应根形态

`app/business/response_shapes.py` 区分两类接口响应。普通接口使用
`{succeeded, now, ...}` 信封；裸映射接口的根表会被客户端逐项遍历，每一项再
`castclass Hashtable`，因此根上不能出现 `succeeded`（bool）或 `now`（double）。

空映射 `{}` 是“当前没有任何记录”的有效占位，不会进入遍历分支。

## 已登记的裸映射接口

| 接口 | 客户端读取点 |
|---|---|
| `deck/getAvatarCharacters` | `PoliticAvatorCache.setup` |
| `common/getCharacters` | `DeckConflateCards.createStatus` |
| `common/getSelectCharacters` | `QuestDataCache.calcDeckParameter` |
| `politic/building/getDrafts` | `UserStatus.setDraftInfo` |
| `politic/waterborneTrade/getStatus` | `PoliticMissionProgressList.updateWaterTradeList` |
| `quest/checkEmergencyQuest` | `EmergencyQuestChecker.sendRequest` |
| `quest/getChapterData` | `PluginQuestDataManager.onGetStoryProgress` |
| `quest/getQuestCompleteFlags` | `PluginQuestDataManager.onGetStoryProgress` |
| `quest/getQuestProgress` | `QuestDataCache.setQuestParameter` |
| `trophy/getTrophyProgress` | `TrophyWindow.init` |
| `dailymission/getDailyMission` | 任务回调的两层根表遍历 |
| `deck/setDecks` | `DeckMake.deckSave` 以 `Count` 判定成功 |
| `common/getEquips` / `common/getTactics` | 客户端逐项枚举根表 |
| `deck/getProtectedCharacterIds` / `deck/getProtectedEquipIds` | 客户端逐项枚举根表 |
| `deck/setCharacterProtect` / `deck/setEquipProtect` | 客户端逐项枚举根表 |
| `friend/findFriends` / `friend/getFriends` | 客户端逐项枚举根表 |
| `siege/getSiegeStatus` | 客户端逐项枚举根表 |
| `auction/auctionCardSale` / `auction/auctionResourceSale` | 客户端逐项枚举根表 |
| `politic/support_item/usePotions` | 客户端逐项枚举根表 |

依据来自客户端反编译回调的方法体，不在本 PR 中扩展未经证实的接口。新增裸映射
接口时必须先补客户端读取点，再加入 `BARE_MAP_EVIDENCE`。

## 不是裸映射

`siege/getBrief` 与 `trophy/getTrophyProgress` 的契约键位于根级，回调按 key
读取并拆箱，而不是遍历根表。它们继续使用 envelope 和类型化占位字段：

- `siege/getBrief`：`siegeBriefMenuDesc.setup` 读取 `day`、`stage`、`isEntry`、
  `winner` 等键。
- `trophy/getTrophyProgress`：`TrophyWindow.load` 读取根级 `level`、`status` 等键。
