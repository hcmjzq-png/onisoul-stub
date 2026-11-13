# 无守卫读键扫描（静态）

给任务 #7「接口响应字段核对与补齐」用的一把尺子：把反编译树里所有 `["命名键"]` 形式的
读取点抽出来，先判方法内有没有同键 `ContainsKey` 守卫，再和契约表 `response_keys` 对账，
输出「客户端无守卫读、契约没声明」的候选行。目的是把「会崩客户端的键」从 1075 个已声明键里
再筛一遍，而不是靠人肉扫 2034 个 `.cs`。

**结论先行**：这把尺子能复用，但只有方法级精度——它按「类名.方法名」归属读键，
同一方法里读任何 hashtable 都会被挂到该方法的端点上，所以它给的是**候选**不是结论。
104 条候选已于 2026-11-14 逐条判读完毕（每条带 `file:line` 依据，见
`docs/analysis/unguarded_gaps_verdicts.tsv`）：**69 条读的不是回包、31 条读的是另一端点回包、
只有 4 条是真缺口**。真缺口与逆推出来的 `common/getEventStatuses` / `turfWar/getWarSituation`
嵌套字段都已补进契约。

## 复现

```bash
python3 tools/unguarded_reads.py dump --src <il_csharp/app> --out reads.tsv
python3 tools/unguarded_reads.py gap  --dump reads.tsv \
    --contract docs/analysis/api_contract.tsv \
    --out docs/analysis/unguarded_gaps.tsv
```

* 仅标准库，Python 3；`<il_csharp/app>` 是 `ilspycmd` 反编译产物（2034 个 `.cs`，不入仓）。
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
| 候选缺口行 / 涉及端点 | **104 / 69** |
| 判读：读的不是回包（`not_response`） | 69 |
| 判读：读的是另一端点回包（`other_endpoint`） | 31 |
| 判读：真缺口（`real_gap`） | 4 |

产物 `unguarded_gaps.tsv`（105 行含表头；`friend/getFriendMapData` 的调用点归属修正后，原先算在它头上的那一行随之消失）列：
`endpoint / callsite / missing_keys / first_evidence`。

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

逐行结论落在 `docs/analysis/unguarded_gaps_verdicts.tsv`（104 行，六列
`endpoint / callsite / missing_keys / verdict / real_owner / evidence`），每行都给到
`file:line` 依据与归属结论。

| verdict | 行数 | 含义 |
|---|---|---|
| `not_response` | 69 | 读的不是响应：请求参数回读、本地入参 / 任务参数、写侧赋值、配置表访问器、UI 对话框结果、本地构造表、插件事件哈希 |
| `other_endpoint` | 31 | 读的确实是回包，但属于另一个端点（方法级归属错）；`real_owner` 列给出真端点 |
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

## 仍未取证（不入表，留档）

* 事件哈希嵌套子表：`quest/clearObstacle` 行的 `obstacleInfo.amount / needAmount / type / category`
  （`PluginQuestStepHelper.cs:186-192`）与 `quest/openTreasureBox` 行的 `treasureInfo.*`
  （`:312-318`、`QuestScriptCommand.cs:655-662`），`eventInfo` 由
  `QuestAreaTableAccessor.EventType` 分发（`PluginQuestStepHelper.cs:108-128`），
  既不是 `clearObstacle` 也不是 `openTreasureBox` 的回包；其宿主端点尚未定死。
* `strategy/getStrategyStatus` 缺整个 `self` 子表：`strategy/isAlive` 行的
  `selfData["command"] / ["route"]`（`StrategyHUDController.cs:976-986`）读的是
  `StrategyDataCache.SelfData` = `updateData["self"]`（`StrategyDataCache.cs:80-90`），
  而 `updateData` 来自 `getStrategyStatus` 回调（`Strategy.cs:128-161`）。

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
  但仍有两类嵌套子表没定宿主端点（见上「仍未取证」），别把 4 这个数字当成缺口总量。
* 不覆盖：DTO / 构造函数里的读取（`AdversaryData` 一类）、跨方法传播的守卫、
  动态拼出的键（`string.Format` 等）、表访问器键。
* `cast` 列会带 `(text)` / `(key)` / `(notify)` 这类 ilspy 对局部变量的写法，不影响键判定。
