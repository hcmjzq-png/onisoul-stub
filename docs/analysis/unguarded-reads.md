# 无守卫读键扫描（静态）

给任务 #7「接口响应字段核对与补齐」用的一把尺子：把反编译树里所有 `["命名键"]` 形式的
读取点抽出来，先判方法内有没有同键 `ContainsKey` 守卫，再和契约表 `response_keys` 对账，
输出「客户端无守卫读、契约没声明」的候选行。目的是把「会崩客户端的键」从 1075 个已声明键里
再筛一遍，而不是靠人肉扫 2034 个 `.cs`。

**结论先行**：这把尺子能复用，但只有方法级精度——它按「类名.方法名」归属读键，
同一方法里读任何 hashtable 都会被挂到该方法的端点上，所以它给的是**候选**不是结论。
104 条候选已于 2026-11-14 逐条判读完毕（每条带 `file:line` 依据，见
`docs/analysis/unguarded_gaps_verdicts.tsv`）：**67 条读的不是回包、33 条读的是另一端点回包、
只有 4 条是真缺口**。真缺口与逆推出来的 `common/getEventStatuses` / `turfWar/getWarSituation`
嵌套字段都已补进契约。判读完成后又把 67 条误报的**来源特征**做成了机械规则
（`gap --filter origin`），再跑一遍候选只剩 **33 行 / 25 个端点**——**全部是
`other_endpoint`（方法级归属错），真缺口已清零**，不含任何「读的不是回包」的行。
最后 3 行的处置见下「round2 收尾」：1 条是真缺口（`debug/resetDedication.score`，已补），
2 条是「根/嵌套双读」的扫描伪键（`deck/extendCharacterStore` / `quest/clearObstacle`）。

## 复现

```bash
python3 tools/unguarded_reads.py dump --src <il_csharp/app> --out reads.tsv
python3 tools/unguarded_reads.py gap  --dump reads.tsv \
    --contract docs/analysis/api_contract.tsv \
    --receivers docs/analysis/verify/gap_receivers.tsv \
    --origins   docs/analysis/verify/gap_origins.tsv \
    --filter origin \
    --out docs/analysis/unguarded_gaps.tsv
```

* 仅标准库，Python 3；`<il_csharp/app>` 是 `ilspycmd` 反编译产物（2034 个 `.cs`，不入仓）。
* 去掉 `--filter origin`（以及后两个参数）就是**过滤前**的口径，产出 104 行候选快照；
  两种口径共用同一份 dump，`dump` 段的 3835 / 3345 / 3009 不受影响。
* `dump` 可单独复用：一张 `file / class / method / line / key / cast / guarded / snippet`
  的表，`cast` 是 `[` 前面紧邻的强转（`(int)((double)` 之类，能看出读的是 `double`
  还是 `Hashtable`），`guarded=1` 表示方法体内出现过 `ContainsKey("同一键")`。
* `gap` 只读 `dump`，按 (类,方法,键) 去重后只取契约 `call_sites` 里的 `Class.method`，
  与该端点 `response_keys` 的**根段**比较（`a.b` 视为声明了根 `a`），保留键
  `succeeded / now / errorReason` 算已声明。

## 基线数字（2026-11-14 实测）

| 阶段 | 数量 |
|---|---|
| `.cs` 文件 | 2034 |
| 原始读取点 | 3835 |
| 去重 (类,方法,键) | 3345 |
| 无守卫 | 3009 |
| 契约 `call_sites`（`Class.method` 形态） | 521 |
| 其中在扫描结果里有读取的调用点 | 206 |
| (调用点,键) 对 | 503 |
| 对账命中已声明 | 149 |
| 候选缺口行 / 涉及端点（过滤前，2026-11-14 判读时的快照） | **104 / 69** |
| 同上，按当前契约复跑（`--filter none`） | 105 / 69（多出的一行是 `strategy/getStrategyCommandInfo` 上 `StrategyCommandSelector.createConfirmDialog` 读的 `STRATEGY_MSG_COMMAND_TRAINING_INFO0`，判读台账建立时还没有这行，已被来源过滤按 `message_table` 剔除） |
| 来源过滤剔除的键 | 159（`write` 35 / `html_request` 52 / `config_table` 41 / `message_table` 17 / `dialog_result` 7 / `task_param` 4 / `local_build` 1 / `nested_child` 2） |
| **候选缺口行 / 涉及端点（过滤后）** | **33 / 25** |
| 判读：读的不是回包（`not_response`） | 67 |
| 判读：读的是另一端点回包（`other_endpoint`） | 33 |
| 判读：真缺口（`real_gap`） | 4 |

产物 `unguarded_gaps.tsv`（37 行含表头，过滤后口径；过滤前的 105 行快照见上表，
`friend/getFriendMapData` 的调用点归属修正后，原先算在它头上的那一行随之消失）列：
`endpoint / callsite / missing_keys / first_evidence`。

## 来源过滤（`--filter origin`）

误报不是随机噪声，都能落到「读的接收者是哪来的」这一个问题上。所以过滤不去改扫描器，
而是让它读两张**取证表**：

* `docs/analysis/verify/gap_receivers.tsv`——候选涉及的 178 个 (调用点,键) 的接收者取证：
  `callsite / key / line / receiver / write`。`receiver` 是 `["键"]` 前面那个表达式
  （`args`、`input.hash`、`task.TaskParams`、`table_`、`selfData`、`instance`…），
  `write=W` 表示这一处是 `ht["k"] = ...` 写侧。客户端一次性抽取，不入仓源码。
* `docs/analysis/verify/gap_origins.tsv`——非回包来源表：`callsite / receiver / origin / evidence`，
  `callsite` 支持 `fnmatch`（`HTMLRankingMediator_*`），`receiver` 为 `*` 表示整个调用点的读
  都不是端点回包。`origin` 词表：`write` / `html_request` / `task_param` / `config_table` /
  `dialog_result` / `local_build` / `debug_build` / `message_table`。

`gap` 的判定只有两条，都只看这两张表：①某键的所有出现都是写侧 → 剔除；②任一次出现的接收者
命中来源表 → 剔除。**没被取证覆盖的 (调用点,键) 一律保留**（宁漏不误杀），所以 D 类
（「读的是另一端点回包」）机械上分不出来，仍留在候选里——这正是过滤后还剩 36 行的原因，
也正好和台账里 33 条 `other_endpoint` + 3 条 `real_gap` 对得上。

更新方式：新增候选若来自新调用点，先补 `gap_receivers.tsv` 的接收者行；确认不是回包再往
`gap_origins.tsv` 加一行（必须带 `file:line` 证据）。`tests/test_gap_verdicts.py` 会校验
两张表的调用点都在契约 `call_sites` 里、`origin` 在词表里、以及**每个被剔除的键都能在这两张表
里找到出处**——过滤掉的键必须可解释，不能靠人眼。

## round2 收尾：最后 3 行怎么落的

| 行 | 结论 | 依据 |
|---|---|---|
| `debug/resetDedication` · `score` | **真缺口，已补** `score:double` | `MightOfNationDialog.cs:430-435` 的回调就是 `debug_addDedicateScore` / `resetDedication` 的 responder，`:433` 直接 `hashtable["score"]` |
| `deck/extendCharacterStore` · 根键 `character` | **伪键（`covered_nested`）** | `DeckAddMaxCharacter.cs:147` `hashtable3 = res["possessionLimits"]`，`:151` 读的是 `hashtable3["character"]`，即已声明的 `possessionLimits.character` |
| `quest/clearObstacle` · 根键 `category` | **伪键（`covered_nested`）** | `QuestScriptCommand.cs:2207` `uses = res["uses"]`，`:2210` `switch((string)uses["category"])`，即已声明的 `uses.category` |

两行伪键按新来源类别 `nested_child` 进了 `verify/gap_origins.tsv`（`receiver` 就写
`hashtable3` / `uses`），所以机械口径也自动不再产出这两行。

## 剩下的两块宽度工作（已量化，未动契约）

扫描层面到这里已经收敛，剩下的是**覆盖宽度**，不是「缺口」：

* **零字段端点 122**（`verify/zero_field_triage.tsv`）：`no_call_site` 53、
  `no_literal_read` 61（调用点有、但 responder 里没有任何字面读键，属正常）、
  `reads_present` 8。8 个里有 5 个的调用点是端点独占的，且读的键基本是 debug 自造表 /
  消息表 / 请求入参（`color1..color5`、`items`、`enable`、`mailIds`），
  与 104 条判读里的误报同源——**真正需要补键的接近 0**。
* **已声明但无类型的键 481**（`verify/untyped_backlog.tsv`）：能靠 `dump` 的 `cast` 列
  唯一定型的只有 **31** 个，**450 个没有 cast 证据**（客户端读键后没做强转，或类型在
  `HashAccessor.getString/getInt` 这类访问器里）。所以「补类型」不能只靠扫描器，
  要么回客户端看访问器调用，要么接受 450 个裸键继续裸着。

## 四类已在代码里确认的误报

1. **方法级归属**：一个方法连发多个请求，读键判不到具体响应。
   `QuestScriptCommand.startQuest` 在 `QuestScriptCommand.cs:429` 发
   `getQuestEncountWorks`，`:431` 收进 `encountWorks`，`:442` 读
   `encountWorks["obstacle"]`；表里这行却被算给 `quest/getQuestBossPunish`
   （同一方法 `:455` 才发它）。`quest/getQuestEncount`、`quest/getQuestEncountWorks`
   两条同源同因。
2. **读的对象不是响应根**：`TurfWarBriefCache.setup(Hashtable table, Callback)`
   （`TurfWarBriefCache.cs:346-355`）读 `table["status"]`、`(long)(double)table["closeWarTime"]`，
   而 `table` 是 `StatusView.setupEventInformation`（`StatusView.cs:480-520`）传进来的
   `activeEvents_["turfWar"]`，即 `common/getEventStatuses` 的子表，不是
   `turfWar/getWarSituation` 的响应根。
3. **读的不是响应**：请求参数回读（`ranking/*` 成批的 `turn` / `aroundRank`）、
   文案常量（`strategy/*` 那几条 `STRATEGY_MSG_CONFIRM_COMMAND*` / `REVENGE_INFO`）、
   方法形参。
4. **间接守卫**：`StatusView.isEventOpen(name)` = `activeEvents_.ContainsKey(name)`
   （`StatusView.cs:555-561`）。反过来，`getPlayerParams` 回调
   （`StatusView.cs:215-225`）只对 `loginStamp` 用了 `ContainsKey`，
   `entity / actionPoints / resources / navigators` 是真·无守卫读——但契约已声明这 12 键，
   所以对账时算命中、不报。

## 104 条逐条判读（2026-11-14 完成）

逐行结论落在 `docs/analysis/unguarded_gaps_verdicts.tsv`（104 行，七列
`endpoint / callsite / missing_keys / verdict / real_owner / evidence / filter`），每行都给到
`file:line` 依据与归属结论；`filter` 列标出该行在**来源过滤后**的去向：`dropped` 67 行
（读的不是回包，已被 `--filter origin` 剔除）、`kept` 33 行（过滤后仍是候选，全部 `other_endpoint`）、
`mixed` 2 行（`debug/dedicate`：`dedication` / `nationalPower` 是本地写被剔除，
`score` 已补进契约）、`nested` 2 行（`covered_nested`：读的是已声明子表，根键是扫描伪键）。
判读分布：67 `not_response` / 33 `other_endpoint` / 2 `real_gap` / 2 `covered_nested`。

| verdict | 行数 | 含义 |
|---|---|---|
| `not_response` | 67 | 读的不是响应：请求参数回读、本地入参 / 任务参数、写侧赋值、配置表访问器、UI 对话框结果、本地构造表 |
| `other_endpoint` | 33 | 读的确实是回包，但属于另一个端点（方法级归属错）；`real_owner` 列给出真端点 |
| `real_gap` | 4 | 契约确实缺键，本批已补 |

抽样对照（三类机制的代表行）：

| 候选行 | 判决 | 依据 |
|---|---|---|
| `turfWar/getWarSituation` / `TurfWarBriefCache.setup` / `closeWarTime,status` | `other_endpoint` → `common/getEventStatuses` | `table` 是 `activeEvents_["turfWar"]`（`StatusView.cs:480-520`），不是该端点响应根 |
| `quest/getQuestBossPunish` / `QuestScriptCommand.startQuest` / `obstacle` | `other_endpoint` → `quest/getQuestEncountWorks` | `encountWorks["obstacle"]` 来自 `getQuestEncountWorks`（`QuestScriptCommand.cs:429-442`），该端点已声明 `obstacle` |
| `common/getServerTime` / `StatusView.resetStatus` / `actionPoints,entity,resources` | `other_endpoint` → `common/getPlayerParams` | `StatusView.cs:282-287` 在 `getPlayerParams` 回调分支里，已声明 12 键 |
| `battle/executeBattle` / `BattleLogManager.getParameterFromServerForDebug` / `debug,monsterId` | `not_response`（写侧） | `BattleLogManager.cs:5214-5219` 先 `info["monsterId"]=` / `info["debug"]=` 再发请求 |
| `deck/getDecks` / `PluginRunner_DoBattleSiege.Init` / `BattleMoney` | `not_response`（任务参数） | `PluginRunner_DoBattleSiege.cs:28` 读 `task.TaskParams["BattleMoney"]` |
| `navigator/getNavigatorDetails` / `getNavigatorDetails` / `color1..color5` | `not_response`（debug 自造） | `NavigatorChangeSelect.cs:339-356` 在 `isDebugMode()` 分支里自己 new 一个 hashtable |
| `quest/clearObstacle` / `PluginQuestStepHelper.OnObstacle` / `obstacleInfo.*` | `other_endpoint` → `battle/executeBattle` | `ProcessQuestStep` 的 `hash` 是 `executeBattle` 回调对象（`PluginRunner_DoDreamSpace.cs:117`），`eventInfo` 是它的一级键 |

## 真缺口（本批已补进契约）

| 端点 | 补的键 | 依据 |
|---|---|---|
| `debug/dedicate` | `score:double`（0 键 → 1 键） | `MightOfNationDialog.cs:433` 读回调 `res["score"]` |
| `deck/extendCharacterStore` | `possessionLimits:Hashtable` + `possessionLimits.character:Hashtable` | `DeckAddMaxCharacter.cs:147-151` |
| `quest/clearObstacle` | `uses:Hashtable` + `uses.category:string` | `QuestScriptCommand.cs:2180-2210`（`res` 就是 `clearObstacle` 回包） |
| `battle/executeBattle` | `executeInfo:Hashtable` + `executeInfo.step:double` | `PluginRunner_DoDreamSpace.cs:98-102`、`PluginRunner_DoOniQuest.cs:159-163`（`onQuestExecute` 的 `obj` 是 `executeBattle` 回包） |
| `politic/support_item/getPotions` | `potions*` → `potions:Hashtable` + `potions.potion0000102:Hashtable` + `potions.potion0000102.amount:double` | `QuestScriptCommand.cs:1606-1613`；原先 `potions` 无类型，占位会整键跳过 |

同时剔除 2 个契约污染键：`strategy/getStrategyCommandInfo` 的
`STRATEGY_MSG_COMMAND_CONSCRIPT_INFO0` / `STRATEGY_MSG_COMMAND_TRAINING_INFO0` 是消息表取值
（`StrategyCommandSelector.cs:281`、`:306` 走 `StrategyLayoutMessageTableAccessor`），不是回包键。

## 判读带出来的两个宿主缺口（本批已补）

* 事件哈希的宿主是 `battle/executeBattle`：`PluginQuestStepHelper.ProcessQuestStep(... , Hashtable hash, ...)`
  的 `hash` 就是 `executeBattle` 回调对象（`PluginRunner_DoDreamSpace.cs:100/117` 传同一个 `hashtable`），
  它在 `:36-40` 直接读 `executeInfo.missionPoint`、`eventInfo`、`rewardInfo`、`bonusInfo`；
  `eventInfo` 再按 `eventType` 分发（`PluginQuestStepHelper.cs:91-128`），
  `obstacleInfo.amount/needAmount/type/category`（`:186-192`）与
  `treasureInfo.keyItemId/keyItemCount/haveCount/treasureId/rewardId`（`:312-318`、
  `QuestScriptCommand.cs:655-662`）都是它的嵌套键。已补 16 键。
* `strategy/getStrategyStatus` 缺 `self` / `cell` 子表：`StrategyDataCache.SelfData` = `updateData["self"]`
  （`StrategyDataCache.cs:80-90`），`updateData` 只在 `Strategy.resetAllData` 赋值
  （`Strategy.cs:239-249`），来源是 `getStrategyStatus` 回调（`:128-161）。该子表原先整块未声明，
  `self` 缺失时 `SelfData` 为 null（`Strategy.cs:251-252` 之后连续取键）。已补 `self` + 13 个有 cast 证据的
  子键，另补 `cell` + `cell.attackLogs`（`StrategyCellLog.cs:126`）。

## 仍未取证（留档，不入表）

* `eventInfo` 的其它事件分支（`item` / `character` / `enemy` / `boss` / `playerBattle`）各自的嵌套键未逐一取证，
  本批只补到 `obstacle` 与 `treasureBox` 两支。
* `strategy/getStrategyStatus` 的 `map` 子表：`StrategyDataCache.MapData`（`:24-34`）存在访问器，
  但全仓没有 `MapData["字面键"]` / 对应局部变量的字面读，键由表访问器动态拼出，未能取证，
  因此只按 `cell` / `self` 两支落表。

## 从误报上下文里反推出的真缺口（可进 #7）

* `turfWar/getWarSituation`：回调读 `selfBelong`（`TurfWarBriefCache.cs:362-370`）、`bonus`（`:325-338`）、`situation.global.advantage`（`:203-205`）、`isMovable`（`:235`）、`situation.battlefields`（`:94-104`）、`battleRules`（`:171-173`），契约原先只声明 3 个根键、且无嵌套。**已补 18 个键 + 战况 handler**（`fca4a6c` 之后的批次）。
* `common/getEventStatuses` 的 `turfWar` 子表：契约只声明 `turfWar:Hashtable`，
  客户端实际要 `status`（`string`）与 `closeWarTime`（按 `double` 读、转 `long`）——
  见 `TurfWarBriefCache.cs:353-354`。`strategy` / `siege` / `giganticRaidBoss` 同理，
  子表字段由 `StrategyDataCache.setup` / `SiegeBriefDataCache.setup` /
   `GiganticRaidBossDataCache.setup` 分别读取，契约表同样未声明嵌套键。补齐需要嵌套占位。
* 契约表自身错位：`friend/getFriendMapData`（2 参、0 键）的 `call_sites` 挂着
  `Politic.resetFriendMap`，而该调用点实参 3 个（`Politic.cs:318`），必然落到
  `friend/getFriendMapData2`（`WebApiClient.cs:2697`）；`friend/visitFriendMap`
  又复用同一 `call_sites`。表里这两行的调用点归属需要修。

## 还没做（别把上面的数字当普查结论）

* 104 条候选行已全部逐条读码判读（67 `not_response` / 33 `other_endpoint` / 4 `real_gap`），
  来源过滤后候选降到 33 行（全部归属错，真缺口 0）；但 `eventInfo` 的其余事件分支与 `getStrategyStatus.map`
  两类嵌套子表仍未取证（见上「仍未取证」），别把 4 这个数字当成缺口总量。
* 不覆盖：DTO / 构造函数里的读取（`AdversaryData` 一类）、跨方法传播的守卫、
  动态拼出的键（`string.Format` 等）、表访问器键。
* `cast` 列会带 `(text)` / `(key)` / `(notify)` 这类 ilspy 对局部变量的写法，不影响键判定。
