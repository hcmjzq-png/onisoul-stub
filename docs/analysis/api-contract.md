# API 端点契约（api_contract.tsv）

从 `OniSoul_Setup_20140712.exe` 内 `app.unity3d` 的 `Assembly-CSharp.dll` 反编译源码中静态抽取，未经运行验证。

## 表结构

`api_contract.tsv` 共 402 行（一行一个端点），列定义：

| 列 | 含义 | 取值示例 |
|---|---|---|
| `endpoint` | 线上路径，等于 `httpCall` 字面量 | `auction/auctionCardSearchName` |
| `api_methods` | 发出该端点的 `WebApiClient` 方法，多方法用 `\|` 分隔 | `dedicateBuilding\|dedicateGold` |
| `request_params` | 请求参数键（`params` 内的键），多方法时为**并集** | `article,category,token` |
| `request_template_keys` | 序号拼接的模板键 | `character_id<N>` |
| `request_constants` | 参数取字面量常量（JSON） | `{"category": ["building","character"]}` |
| `response_keys` | 客户端回包读取的键，`;` 分隔，`键:类型`，`*` 表示被 `ContainsKey` 保护 | `succeeded:bool;container:string*` |
| `key_count` | `response_keys` 条目数 | `3` |
| `call_sites` | 调用方类.方法 | `BootUp.login` |
| `call_count` | 调用点数量 | `1` |

响应类型来自 `(bool)` / `(string)` / `(int)(double)` 这类显式 cast；无 cast 证据的键不带类型。

## 覆盖统计

| 指标 | 数量 |
|---|---|
| 端点总数（= `httpCall` 唯一字面量） | 402 |
| 已抽出响应字段 | 279 |
| 被调用但回调体不读命名键 | 69 |
| 本客户端从不调用（无调用点） | 53 |
| 唯一响应键 | 487 |
| 带类型响应键 | 365 |
| 带可选标记（`ContainsKey` 保护） | 73 |
| 一端点多方法（参数取并集） | 10 |
| 带序号模板键的请求 | 4 |
| 带常量枚举的请求 | 14 |

## 抽取手段

字面量正则只能覆盖最简单的写法，实际补了十五类（其中「模型构造传参」经实测 0 命中、予以排除）：

1. **命名参数**：`getAuctionCards(p_responder: OnGetAuctionCards, ...)`，需剥掉 `name:` 前缀。
2. **同类裸调用**：`OnGetAuctionCardsCommon(p_payload)`，无接收者，按当前类解析。
3. **泛型单例接收者**：`Singleton<UserStatus>.Instance.updateKokudaka(result)`；最初只认 `ServiceLocator<T>`。
4. **赋值闭包（污点传播）**：`hashtable3 = hashtable2["possessionLimits"]` 后 `setUpCharacter(hashtable3)`，从载体派生的局部变量也算载体。
5. **成员字段接收者**：`desc_.setup((Hashtable)result)`，靠字段声明 `private siegeBriefMenuDesc desc_;` 把接收者映射到类型。
6. **静态字段跨类传递**：`LoginBounusMenu.LoginHash = (Hashtable)result;`，真正的读取发生在另一个类的属性 getter 与 `UserStatus.addLoginBounus` 里。这类写法让 `common/getLoginStampSheet`、`common/stampLoginSheet` 一度被误判成「不读字段」，见 `verify/static_field_keys.txt`。

7. **成员字段承接**：`charactersTable_ = (Hashtable)result;`，键在同类其它方法里读（`charactersTable_["id"]`），见 `field_keys.tsv`。
8. **属性 setter 承接**：`deckScene_.StorageInfoHash = x;`，setter 里 `storageInfoHash_ = value` 之后立刻读键。
9. **常量键**：键名是 static 字段（`storageExtendSlotKey_g`），值在别处声明，需先建常量表再解析。
10. **`HashAccessor` 访问器**：`getInt("sellPrice")` / `getHash("characterIds")`，正文里没有 `["k"]`。
11. **`HashAccessFuncs` 路径读键**：`getInt(hash, "myRecord", "rank", -1)`，两个字符串是**父子键**，落表时记作 `myRecord.rank`。
12. **方法组引用**：`WebApiFunc v = client.getRankersInBattle;`，委托存进 Hashtable、按 span 取出后才 `v(...)` 传入回调。
13. **responder 变量 / 跨帧**：`WebApiClient.Responder response = delegate(object result){...};` 定义在别处，由另一个 lambda 传出，按变量名与形参回溯最多 3 层。
14. **外层动态 id + 内层固定字段**：`foreach (x in hash.Values)` 后包 `HashAccessor`，内层读 `amount`，落表记作 `<id>.amount`，外层键本身是数据 id、服务端可自由决定。
15. **模型构造传参**：`new Xxx(result)` / `Xxx.Parse(result)` 这路**实测 0 命中**，此写法在本客户端不存在。
16. **全局唯一方法名兜底 / 最内层同类解析**：接收者类型推不出时，按方法名唯一性或最内层类作用域解析；前者补出 1 个，后者 0 命中。

递归深度上限 4，带环保护与 memo。多数响应字段不在回调体里读，而是 result 被转发后再读，必须做「result → 参数 → 下游方法」递归才能取到。

## 校验（`verify/`）

| 校验 | 方法 | 结果 |
|---|---|---|
| 端点完整性 | 契约↔源码字面量双向对账 | 402↔402，0 差；唯一非字面量命中是 `private void httpCall(string api,...)` 方法定义本身 |
| 方法归属 | 花括号配对定位方法体 | 445/445 个真实方法全部定位（另 6 个 `public delegate` 声明非方法） |
| 参数正确性 | 用方法体重算参数并集，与表对比 | 差异 6 项，已全部修正（见下） |
| 字段真实性 | 1107 个键逐个回查源码字面量 | 0 个找不到；`verify/final_check.txt` 是 990 键时期的快照，当前键数/类型数/结构类问题以 `python3 tools/contract_check.py` 输出为准（1108 键 / 658 带类型 / 0 问题） |
| 类型自洽性 | 同一端点内的声明类型 vs 实测 cast | 658 处带类型读取，0 冲突 |
| 表结构与编码 | 9 列齐整 / UTF-8 无 BOM / 仅 LF / 无重复端点 / `key_count` 与条目数一致 | 全部通过 |
| 键名一致性 | 回包键不得与同端点请求参数同名 | 5 例经核对为**回显读取**（客户端读回自己发过的值），非错误 |
| 方向一致性 | 键必须出现在「回包路径」而非「请求构造路径」 | `politic/waterborneTrade/send` 两处疑似请求侧复用，已排除未并入 |
| 旁路通道 | 扫 `new WWW(`/`WWWForm`/`TcpClient` | 见下节，不属于本表 |

## 修正过的三类缺陷

1. **一端点多方法**（10 个）。原先按方法名归并，只取到一个方法的参数。典型：
   - `battle/executeBattle` 由 10 个方法发出（`executeBattle`、`...Monster`、`...NPC`、`...Player`、`...Quest`、`...RaidBoss`、`...Siege`、`...Strategy`、`...OutBreak`、`...GiganticRaidBoss`），此前漏了 `buildingId, command, difficulty, encountId, entry, monsterId, npcId, questType, requestPhase` 9 个参数；
   - `common/dedicate` 由 5 个方法发出（character / building / tactics / equip / gold）。
2. **同一方法按分支发不同端点**：`getFriendMapData` / `getFriendMapData2`、`setMapName` / `setMapName2`。原先以方法名为主键，第二个端点被吞掉，端点总数因此少 2。
3. **模板键被当成字面量键**：`hashtable.Add("character_id" + num, ...)` 实际发出 `character_id1..N`，`skill_id` 同理。
4. **方法级归属误挂**（`common/getEventStatuses` 根上 13 个键）。该端点有 6 个调用点
   （`StatusView.cs:485`、`giganticRaidBossScene.cs:63`、`Strategy.cs:72`、`StrategySelect.cs:52`、
   `PluginRunner_DoBattleSiege.cs:259`、`BoardBody.cs:830`），全部只读四个事件子表——
   `StatusView.cs:490/500/510/520` 与 `giganticRaidBossScene.cs:66`、`Strategy.cs:75`、
   `StrategySelect.cs:55`、`PluginRunner_DoBattleSiege.cs:266-271`。根上的
   `attackList` / `chain` / `phase` / `punishPoint` / `monsterId` / `needPoint` / `endTime` 读的是
   `giganticRaidBoss/getGiganticRaidBossInformation` 的回包（`giganticRaidBossScene.cs:120-130`、
   `giganticRaidBossStatus.cs:22-36`），`a` / `b` / `current` / `max` 读的是
   `strategy/getStrategyBrief` 的回包（`StrategySelect.cs:102-110`），`status` / `isEntry` 读的是各子表内的同名键
   （`PluginRunner_DoBattleSiege.cs:269-271`、`StrategyDataCache.cs:196-197`）。这 13 个根键已从
   `common/getEventStatuses` 剔除，键数 1074→1068；同一批核对里把该端点确实缺的
   `giganticRaidBossPoint` / `hp` / `damage` / `needPoint.0..2` 补进了 `giganticRaidBossInformation`；
   该端点的 `monsterId` 原先无类型（占位会整键跳过，`giganticRaidBossScene.cs:130` 的
   `hashtable["monsterId"].ToString()` 会 NRE），按 `createBg(string)` → `getMenuBg(string)` 的口径定成 `string`。
* `unguarded_gaps.tsv` 的 104 条候选缺口已逐条判读（明细见 `docs/analysis/unguarded_gaps_verdicts.tsv`，口径见 `unguarded-reads.md`）：67 条读的不是回包、33 条读的是另一端点回包、4 条真缺口。
  本批据此补 5 处：`debug/dedicate.score`、`deck/extendCharacterStore.possessionLimits(+.character)`、
   `quest/clearObstacle.uses(+.category)`、`battle/executeBattle.executeInfo(+.step)`、
   `politic/support_item/getPotions.potions(+.potion0000102.amount)`；同时剔除
   `strategy/getStrategyCommandInfo` 上 2 个消息表污染键。键数 1068→1075，带类型 584→594，
   唯一 453→456，可选 74→73。
* 判读带出的两个宿主缺口也一并补上：`battle/executeBattle` 补 `executeInfo.missionPoint` 与
  `eventInfo` 家族（`eventInfo` / `eventType` / `obstacleInfo.amount,needAmount,type,category` /
  `treasureInfo.keyItemId,keyItemCount,haveCount,treasureId,rewardId`）+ `rewardInfo` / `bonusInfo` 共 16 键，
  依据 `PluginQuestStepHelper.cs:28-49`（`ProcessQuestStep` 的 `hash` 就是 `executeBattle` 回调对象）与
  `:186-192`、`:312-318`；`strategy/getStrategyStatus` 补 `self` + 13 子键与 `cell` + `cell.attackLogs`（16 键），
  依据 `StrategyDataCache.cs:24-90` 与 `Strategy.cs:128-249`。键数 1075→1107，带类型 594→626，
  唯一 456→487，可选仍 73。
* 判读结论又反向做成了候选过滤（`tools/unguarded_reads.py gap --filter origin`，依据
  `verify/gap_receivers.tsv` + `verify/gap_origins.tsv`）：剔除 157 个「读的不是回包」的键，
  候选 104→33 条 / 25 个端点；`dump` 段基线（3835 / 3345 / 3009）不变，契约键数与端点数不受影响。

## 常量枚举（Stub 必须按此校验，不能任意填）

```
common/dedicate                category: character|building|tactics|equip|gold
battle/executeBattle           battleType: ATTEMPT_BATTLE|BOSS_BATTLE|NPC_BATTLE|PLAYER_BATTLE|
                               QUEST_BATTLE|RAIDBOSS_BATTLE|SIEGE_...|GIGANTIC_RAIDBOSS_BATTLE
battle/getVsBattleLogs         type: strategy|turfWar|vs
battle/getTurfWarReplayData    type: turfWar
trophy/completeTrophy          access: mypage|raidBoss|giganticRaidBoss
trophy/getTrophyProgress       access: mypage|raidBoss|giganticRaidBoss
trophy/messageWindowTrophy     access: mypage
ranking/getRankersInNationalRanking  rankingPeriod: all|weekly
giganticRaidBoss/getGiganticRaidBossEventResult  term: current|last
politic/map/getMapData         assets: map0
quest/executeQuestEx|Ex2      assets: map0
quest/checkEmergencyQuest      questType: event3
debug/debugLogin               username: debug
```

## 嵌套键（未进表，需按结构返回）

原始抽取只记录顶层键，某些键的值是 Hashtable，其子键在源码里按下标或拼接读取。已核实两组，注意二者**不是同一回事**：

### 签到奖励（`common/getLoginStampSheet` / `common/stampLoginSheet`）

```json
{
  "stampCount": 3,                       // 已签到次数，1-based
  "nextStampDate": "2014-07-13T4:00:00+0000",  // 格式 "yyyy-MM-ddTH:mm:ss+0000"
  "loginSheet": {
    "day1": { "itemId": "item11_0000001", "amount": 1 },
    "day2": { "itemId": "...", "amount": 2 },
    "day3": { "itemId": "...", "amount": 3 }
  }
}
```

依据：`UserStatus.addLoginBounus` 先 `ContainsKey("stampCount")` 与 `ContainsKey("loginSheet")` 双判空才继续，再 `int num = (int)(double)hash["stampCount"]`、`hashtable = (Hashtable)hash["loginSheet"]`、`"day" + num` 取当天条目、子键 `itemId`(string) / `amount`(int) 后 `RewardProcessor.process`；`UserStatus.updateLoginStamp` 读 `nextStampDate` 并用 `DateTime.ParseExact`，格式串写死为 `yyyy-MM-ddTH:mm:ss+0000`（注意 `H` 是单字母格式符）。

客户端侧 `LoginBounusMenu.TodayItemId` 用 `hashtable.Count + 1` 反推今天该签第几天，因此 `loginSheet` 里**只应放已签过的天**，未签的不要预置。

### 攻城战三日简报（`siege/getBrief`）

```json
{
  "day": 1, "stage": 1, "isEntry": true, "role": "attacker",
  "winner":   { "day0": "attacker", "day1": "defender", "day2": "none" },
  "attacker": { "0": "country02", "1": "country08" },
  "defender": { "0": "country01" }
}
```

`stage` 取 0/1/2 → `SiegeCategory.One/Two/Final`；`winner.day0..2` 是三天各自的胜方（`Winner[3]`，缺省 `"none"`）；`attacker` 键是数字字符串 `"0"/"1"`（两个攻方国家），`defender` 键是 `"0"`（一个守方国家），缺键退化为 `""`。

`siegeBriefMenuDesc.setup` 里 `Winner[i] = (string)hashtable["day" + i]`（i<3）、`Attacker[j]`（j<2）、`Defender[k]`（k<1）。表里这几个键标为 `Hashtable`，子结构以此处为准。

## WebApiClient 之外的网络通道（不属于本表）

| 通道 | 位置 | 说明 |
|---|---|---|
| 资源下载 | `Loader` / `SimpleLoader` / `StanderdLibrary` / `MoviePlayer` / `SoundPlayer`，`new WWW(` 13 处 | GET 资源服，host 取自配置 `asset` |
| 截图上传 | `SnapshotUploader.cs`，`WWWForm` 5 处 | POST 到 `imageUploderURL_g`（外部 PHP，非本游戏服务端） |
| 聊天 | `Irc.cs`、`Proxy.cs`，`TcpClient` | IRC 长连接，非 HTTP |
| 引擎 | `WWWObject.cs` | PlayMaker 侧对象 |

## 已知缺口

零字段端点共 122 个，逐个给出处置，全量清单见 `verify/no_key_final.txt`：

- **53 个无调用点**：`app/` 内不存在 `.方法名(` 的调用点，只有 `WebApiClient` 自己的包装方法，说明本客户端从不触发。契约参数取自 `WebApiClient` 方法本身。
  （注意：早期口径按「`httpCall` 站点数」判定被调用，把包装方法算进去了，因此曾误报为 55 个。）
- **69 个有调用但不读命名键**：形态已全部归清（69 条，`shape` 无一留空）：
  - `ignored` 26：回调体只置状态位、切场景、改本地 UI，完全不读回包（本轮逐条核实，见下节「口径差」）；
  - `iterates_no_key_name` 5：`foreach` 遍历后取 `item.Key` 当数据 id（如 `deck/getProtectedCharacterIds`），外层键名由服务端决定；
  - `hands_to_callee` 10：原样交给下游方法（`resetItems` / `createPlayerData` / `getQuestProgress` / `cancelWaterTrade` 等），已追一层仍未读到键；
  - `responder_elsewhere` 15：回调体在另一栈帧构造，追 3 层未及；
  - `null_check_only` 3、`count_only` 1、`ui_only` 1、`other` 9：只判空、只取 `.Count`、只喂 UI。
  - 这 70 个回 `{}` 不会导致崩溃（客户端不做命名读取），但可能导致**界面为空**，属运行验证可确认的残余项。
- **模板键的响应侧**：`hashtable["day" + i]` 这类已按上面「嵌套键」处理；其余 `*TableAccessor` 里的动态键读的是**配置表**，不是回包，未列入。
- `friend/getPlayerEntry` 方法发出的是 `common/getPlayerEntity`，名称不一致，原文如此，未改动。

### 补录调用点后新发现的三处缺口（2026-11-13 已补）

2026-11-13 补录三个漏记调用点后，回调体才被真正读到：其中两处直接拆箱根键，按「零字段 → 只回
`succeeded`/`now`」的旧实现会崩。补录时还发现**端点归属错位**：客户端同名方法有两个重载，各打一条
真实路径，键必须挂在调用点实际命中的那条上。

| `WebApiClient` 重载 | 真实路径 | 调用点 |
|---|---|---|
| `getFriendMapData(string, Responder)` `:2688` | `friend/getFriendMapData` | 无（本客户端不触发 2 参版本） |
| `getFriendMapData(string, int, Responder)` `:2697` | `friend/getFriendMapData2` | `Politic.cs:318 resetFriendMap` |
| `setMapName(string, Responder)` `:695` | `politic/map/setMapName` | 无（本客户端不触发 2 参版本） |
| `setMapName(int, string, Responder)` `:704` | `politic/map/setMapName2` | `UserStatus.cs:1377 setMapName`、`mypageCastleTownRename.cs:128 onOk` |
| `getTurnfWarRceiveTurfWarReward(Responder)` `:2834` | `turfWar/receiveTurfWarReward` | `TurfWarResultRenderer.cs:228` |

所以键补在 `...2` 两条路径上；`friend/getFriendMapData`、`politic/map/setMapName` 维持零字段。

验证方式：全仓扫描 `.setMapName(` / `.getFriendMapData(` 共 3 处调用（`UserStatus.cs:1377`、`mypageCastleTownRename.cs:128`、`Politic.cs:318`），实参都是 3 个，全部落在 `...2` 路径上；2 参重载在本客户端没有调用点。

`setMapName2` 的根形态取决于客户端容器，容器链已静态定死：`Configs.Container` 只在 `setContainer` 赋值（`Configs.cs:1317`，表里没有的字符串回落 `none`），唯一运行时入口是 `SessionKeeper.cs:138-141` 读 `gameLogin` 响应的 `container` 字段；本 Stub `app/business/gameplay.py:492` 显式回 `"container": "none"`，所以生效的是非 ymbga 分支，正确响应是 `{}`。若将来改回 ymbga，需把该端点移出 `BARE_MAP_EVIDENCE` 并改回 `{"succeeded": true}`。

本轮补进契约表与占位响应的键（`response_keys` 用点号表示嵌套层级）：

| 端点 | 新增 / 整形 | 依据（`文件:行`） |
|---|---|---|
| `friend/getFriendMapData2` | `completecount:double`、`acceleratecount:double`、`friendInfo:Hashtable`、`friendInfo.turfWar:Hashtable`、`friendInfo.turfWar.team:string` | `Politic.cs:318` 起回调；`(int)(double)` 直接拆箱，`friendInfo → turfWar → team` 三级无守卫 |
| `turfWar/receiveTurfWarReward` | `schedule{open,close}`、`gainRedSoul`、`rank`、`score`、`defenseScore`、`global{end{score,rank,defenseScore},daily}`、`battlefield{end,daily}`、`bonuses` | `TurfWarResultRenderer.cs:62-90`、`:92`、`:116`、`:152` |
| `politic/map/setMapName2` | 根形态改为「裸映射」：回 `{}`（`Keys.Count == 0`） | `UserStatus.cs:1396-1402` 非 ymbga 分支只数键个数；容器链见下 |
| `common/getEventStatuses` | 四个事件子表补嵌套键：`turfWar{status,closeWarTime,endWarTime,updateTime,resultCloseTime}`、`strategy{isEntry,status,closeTime,endTime,resultCloseTime}`、`siege{isEntry,status,advantage,closeTime,endTime,resultCloseTime}`、`giganticRaidBoss{isEntry,status,closeTime,endTime,resultCloseTime}` | `TurfWarBriefCache.cs:353-354` / `:454-469`、`StrategyDataCache.cs:196-198` / `:168-178`、`SiegeBriefDataCache.cs:164-167` / `:173-183`、`GiganticRaidBossDataCache.cs:111-116` / `:82-92`：`StatusView.isEventOpen` 只判 `ContainsKey`，子表一旦存在就进各自的 `setup`，`(long)(double)table[...]` 无守卫拆箱，缺键即 NRE |
| `friend/getFriendMapData` | `call_sites` 清空、`call_count` 归 0（2 参重载无调用点） | `WebApiClient.cs:2688` 定义 2 参；全仓唯一 `.getFriendMapData(` 调用在 `Politic.cs:318` 传 3 个实参，落 `WebApiClient.cs:2697`（`friend/getFriendMapData2`）；`Politic.cs:322` 另一个调用是 `visitFriendMap` |

同族结果渲染器一并补齐（它们的 `schedule` 是复数秒，缺一层就崩）：

| 端点 | 新增 | 依据 |
|---|---|---|
| `giganticRaidBoss/getGiganticRaidBossEventResult` | `schedule{open,end}`、`country:string`、`punishPoint:string`、`damage{top{name,rank,value},self{rank,value}}`、`contribute{top{...},self{...}}` | `GiganticRaidBossResultRenderer.cs:24-44`、`:59-87` |
| `siege/getSiegeResultLog`、`siege/lookSiegeResult` | `schedule{open,close}`、`record{rank,globalTotalScore}`、`attacker` / `defender` 定性为 `Hashtable` | `SiegeResultRenderer.cs:44-55`、`:60-82`、`:84-99` |
| `turfWar/getTurfWarResultLog` | `schedule{open,close}` | `TurfWarResultRenderer.cs:66-68` |

两条硬约束（已写成测试 `tests/test_nested_placeholders.py`）：

1. **不能预置客户端 `res.Add` 的键**。`TurfWarResultRenderer` 会 `Add("victory")` / `Add("names")`，
   `GiganticRaidBossResultRenderer` 会 `Add("bonus")` / `Add("names")` / `Add("attackerRank")` /
   `Add("contributionRank")` / `Add("chainCounts")` / `Add("chainPlayers")`；响应里预置同名键会让
   客户端 `Hashtable.Add` 抛 `ArgumentException`。
2. **`Hashtable` 默认值必须每个键独立**。`placeholders` 原先让所有 `Hashtable` 共用同一个 `{}`
   对象，一旦改成嵌套写入就会互相串（本轮由
   `test_every_envelope_endpoint_keeps_envelope_and_typed_keys` 的「键值类型」断言抓到）。

实现层同时扩了三处，缺一不可：

- `contract.lookup(body, key)`：按点号取路径值，供不变量测试与排障共用；
- `placeholders._assign()`：按点号造嵌套字典；
- `response_shapes` 只需要两种根形态：`politic/map/setMapName2` 直接归入 `BARE_MAP_EVIDENCE`
  （它读的是根表键数，不是命名键），`test_shape_rules_are_known_disjoint_endpoints` 断言
  裸映射与标量根两张证据表不相交。

仍未补 / 未验证：

本轮复核掉的静态疑点（原列为「未验证」）：

- `SiegeResultRenderer.getRankString(0)` / `getRankBonusIcon(0)` 都有 `val <= 0` 守卫
  （`SiegeResultRenderer.cs:24-27`、`:33-36`），rank 占位给 0 安全；
- `TurfWarResultRenderer.convertBonus` 在 `Count == 0` 时短路并 `return`
  （`TurfWarResultRenderer.cs:98-103`），`fieldWon` / `teamWon` 也都走 `ContainsKey`，所以
  `bonuses` 给空表安全——但 `:97` 的 `res.Add("victory", false)` 仍意味着 `victory` 不能预置。

仍未验证：

- `politic/map/setMapName2` 在 ymbga 容器下的分支（`UserStatus.cs:1379-1394`）没有对应实现：
  本 Stub 固定 `container: none`，这条分支只在服务端改回 ymbga 时才生效；
- 上述结论都是静态推断，没有真机单次启动验证。

### 处置清单的口径差（27 条，已逐条核清）

`verify/no_key_final.txt` 的 `usage` 列原按 `.<方法名>(` 字面点判定，与契约 `call_sites` 对不上，差异正好 27 条，现已逐条核对完毕：

- **26 条清单记 `no_call_site`、契约有调用点**：调用点全部真实存在，且回调体不读回包——
  `auth/createPlayer`（`BootUp.cs:182` / `LoginEnvironment.cs:295`，只 `transitionScene`）、
  `auth/refreshToken`（`BoosterPackScene.cs:77`，只弹充值窗）、
  `debug/addItems`（`DebugMakeCharacterMenu.cs:164` / `DebugMakeEquipMenu.cs:145` / `PoliticDebugMenu.cs:73`、`:89`，回调体为空）、
  `debug/debugCreateEquip`（`DebugMakeEquipMenu.cs:221`、`:329`，只复位 `canMake_`）、
  `debug/setQuestStep`（`Quest.cs:116`，空回调）等，全部归入 `ignored`，清单已改成 `called` 并补 `file:line`。
- **1 条方向相反**：`friend/getFriendMapData` 清单记 `called` / `hands_to_callee:PoliticMapInfo,visitFriendMap`，
  但 2 参重载无调用点（`WebApiClient.cs:2688`，三实参落 `:2697`，归 `getFriendMapData2` / `visitFriendMap`），
  清单已改 `no_call_site`。
- **2 条过期**：`battle/getRaidBossLogs`、`turfWar/receiveTurfWarReward` 已在此前批次拿到响应键，已从清单移除。

结论：这 26 个端点回 `{}` 安全，零字段 122 = 53 无调用点 + 69 有调用点（其中 26 条即本次核清的「有调用但不读键」）。
三条口径不变量由 `tests/test_no_key_inventory.py` 守住：清单行数 == 契约零字段端点数、`usage` 与 `call_sites` 同向、
有调用点的行必须给出形态。

- 上述「未读字段 / 未调用」均为静态结论，要变成确定结论只能靠单次启动实测或类型级数据流分析。

## 重跑

前置条件：本地已有反编译产物 `analysis_full/il_csharp/app/`（2034 个 .cs）与 `api_contract.tsv` 的方法表。

```
python a_api_exhaustive.py     # 抽响应字段 → api_contract_final.tsv
python a_contract_v2.py        # 参数并集 + 模板键 + 常量 → api_contract_final_v2.tsv
python a_static_fields.py      # 静态字段跨类传递 → static_field_keys.tsv
python a_verify_endpoints.py   # 端点完整性
python a_verify_channels.py    # 旁路通道
python a_verify_params.py      # 参数重算
python a_verify_types.py       # 类型自洽
python a_verify_dynkeys.py     # 动态键
python a_static_fields.py      # 静态字段跨类传递
python a_field_keys.py         # 成员字段承接
python a_haccessor.py          # HashAccessor 访问器
python a_haccessfunc.py        # HashAccessFuncs 路径读键
python a_methodgroup.py        # 方法组引用
python a_responder_var.py      # responder 局部变量
python a_responder_flow.py     # responder 跨帧回溯
python a_inner_keys.py         # 外层动态 id + 内层字段
python a_final_disp.py         # 零字段端点处置表
python a_final_check.py        # 推送前完整性检查（一次性脚本，未入仓；结构类检查已由
                               # tools/contract_check.py 承接，见「校验」表）
```

反编译：`dotnet tools_ilspy\cmd\tools\net8.0\any\ilspycmd.dll -p -o <outdir> container_dump\Assembly-CSharp.dll`
