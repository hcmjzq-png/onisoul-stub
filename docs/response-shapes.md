# 响应根形态

`app/business/response_shapes.py` 区分两类接口响应。普通接口使用
`{succeeded, now, ...}` 信封；裸映射接口的根表会被客户端逐项遍历，每一项再
`castclass Hashtable`，因此根上不能出现 `succeeded`（bool）或 `now`（double）。

空映射 `{}` 是“当前没有任何记录”的有效占位，不会进入遍历分支。

## 已登记的裸映射接口

| 接口 | 客户端读取点 |
|---|---|
| `auction/auctionCardSale` | `AuctionDataManager.cs:OnGetMySellingCards` |
| `auction/auctionResourceSale` | `AuctionDataManager.cs:OnGetMySellingResources` |
| `common/getCharacters` | `DeckConflateCards.cs:createStatus` |
| `common/getEquips` | `DeckConflateCards.cs:createStatus` |
| `common/getSelectCharacters` | `QuestDataCache.cs:calcDeckParameter` |
| `common/getTactics` | `DeckConflateCards.cs:createStatus` |
| `dailymission/getDailyMission` | `DailyMissionScene.cs:Start` |
| `deck/getAvatarCharacters` | `Politic.cs:resetMap` |
| `deck/getProtectedCharacterIds` | `DeckScene.cs:OnEnable` |
| `deck/getProtectedEquipIds` | `DeckScene.cs:OnEnable` |
| `deck/setCharacterProtect` | `CharacterConflatePreview_Character.cs:protectOrRelease` |
| `deck/setDecks` | `DeckMake.cs:deckSave` |
| `deck/setEquipProtect` | `CharacterConflatePreview_Equip.cs:protectOrRelease` |
| `friend/findFriends` | `FriendListWindow.cs:getFindData` |
| `friend/getFriends` | `FriendListWindow.cs:getFriendData` |
| `politic/building/getDrafts` | `UserStatus.cs:setDraftInfo` |
| `politic/map/setMapName2` | `UserStatus.cs:setMapName`（none 容器分支） |
| `politic/waterborneTrade/getStatus` | `PoliticMissionProgressList.cs:updateWaterTradeList` |
| `quest/checkEmergencyQuest` | `EmergencyQuestChecker.cs:sendRequest` |
| `quest/getQuestCompleteFlags` | `PluginQuestDataManager.cs:onGetStoryProgress` |
| `quest/getQuestProgress` | `QuestDataCache.cs:setQuestParameter` |

依据来自客户端反编译回调的方法体，不在本 PR 中扩展未经证实的接口。新增裸映射
接口时必须先补客户端读取点，再加入 `BARE_MAP_EVIDENCE`。

`BARE_MAP_EVIDENCE` 里允许出现共享枚举器：`common/getCharacters`、
`common/getEquips`、`common/getTactics` 三个端点都通过
`DeckConflateCards.cs:createStatus` 枚举根表。`common/getSelectCharacters` 的
回调 `PlayerDeck.cs:getCharacters` 只把结果存进 `PlayerDeckCache.Characters`，
真正的枚举发生在 `QuestDataCache.cs:calcDeckParameter`，因此证据指向后者。

证据格式为 `<文件名>.cs:<方法名>@0x<容器绝对偏移>`。证据变更必须同步重跑
校验；仓库内没有 CI，客户端源码也不入仓：

```bash
python tools/verify_response_shape_evidence.py \
  --assembly app_unity3d.bin
# 期望输出：[shape-evidence] checked=26 failed=0
```

改一条证据就必须附上这次命令的输出，否则视为未验证。

如果同时有 PC 反编译源码，可再检查文件与真实方法声明：

```bash
python tools/verify_response_shape_evidence.py \
  --source /path/to/analysis_full/il_csharp/app \
  --assembly app_unity3d.bin
```

逐端点判决和证据偏移见 `docs/analysis/response_shapes.tsv`：402 个端点中
21 个是 bare-map 覆盖端点，381 个走 envelope；另有 5 个 `SCALAR_ROOT_EVIDENCE`
端点明确保留 envelope 根级标量键。

## 不是裸映射

以下端点的契约键位于根级，回调按 key 读取并拆箱，而不是遍历根表。它们继续使用
envelope 和类型化占位字段：

- `politic/support_item/usePotions`：`DailyMissionScene.cs:convertRewardByUsePotionsAPIResult`
  读取根级 `result` 并展开奖励。
- `quest/getChapterData`：`PluginRunner_DoEvent.cs:onQuestChapterData` 读取
  `clearCount`、`complete`、`maxStep`、`step`。
- `siege/getBrief`：`siegeBriefMenuDesc.cs:setup` 读取 `day`、`stage`、`isEntry`、
  `winner` 等键。
- `siege/getSiegeStatus`：`vsSetting_Siege.cs:getSiegeSituation` 读取 `selfDeck`、
  `costs`、`rival`、`record` 等键。
- `trophy/getTrophyProgress`：`TrophyWindow.cs:load` 读取根级 `level`、`status` 等键。
