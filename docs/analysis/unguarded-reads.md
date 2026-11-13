# 无守卫读键扫描（静态）

给任务 #7「接口响应字段核对与补齐」用的一把尺子：把反编译树里所有 `["命名键"]` 形式的
读取点抽出来，先判方法内有没有同键 `ContainsKey` 守卫，再和契约表 `response_keys` 对账，
输出「客户端无守卫读、契约没声明」的候选行。目的是把「会崩客户端的键」从 1074 个候选里
再筛一遍，而不是靠人肉扫 2034 个 `.cs`。

**结论先行**：这把尺子能复用，但只有方法级精度。104 条候选行里抽验的 3 条全部是误报，
误报机制已经摸清（见下），真缺口是从误报的上下文里反推出的 `common/getEventStatuses`
嵌套字段。

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

## 抽验记录（3 条，全部证伪）

| 候选行 | 判决 | 依据 |
|---|---|---|
| `turfWar/getWarSituation` / `TurfWarBriefCache.setup` / `closeWarTime,status` | 误报 | `table` 是 `activeEvents_["turfWar"]`（`StatusView.cs:480-520`），不是该端点响应根。**但同一回调里另有真缺口**：`(Hashtable)result["selfBelong"]` 之后直接取值（`TurfWarBriefCache.cs:362-370`），已补（见下） |
| `quest/getQuestBossPunish` / `QuestScriptCommand.startQuest` / `obstacle` | 误报 | `encountWorks["obstacle"]` 来自 `getQuestEncountWorks`（`QuestScriptCommand.cs:429-442`） |
| `common/getServerTime` / `StatusView.resetStatus` / `actionPoints,entity,resources` | 误报 | `StatusView.cs:286` 在 `getPlayerParams` 回调分支里，与 `getServerTime` 无关 |

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

* 104 条候选行只逐条读码确认了 3 条；四类误报是抽验得出的机制，不是对全部候选的分类统计。
* 不覆盖：DTO / 构造函数里的读取（`AdversaryData` 一类）、跨方法传播的守卫、
  动态拼出的键（`string.Format` 等）、表访问器键。
* `cast` 列会带 `(text)` / `(key)` / `(notify)` 这类 ilspy 对局部变量的写法，不影响键判定。
