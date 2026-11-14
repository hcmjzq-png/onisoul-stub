# 关卡动态表与战斗调用复核（2026-11-15）

基于已合并的 `85b5ad0`，继续使用原安装包内 `b27be699…` 程序集。
本批修复表提取与服务端数据加载，不把表恢复计作接口实现：仍为 402 个登记端点、
45 个专用处理器、357 个占位处理器。尚未验收 Unity 关卡画面和战斗流程。

## 已落实的修复

- 从安装包重新提取 `app/cache/data7/e/389htzvn.d`，没有使用旧 AI 的表文件。
  bundle、解压容器、源码指纹见 `source-proof.json`。
- 新增 `quest_tables.tsv` 的 552 张白名单：6 张索引、273 张区域、273 张奖励表，
  合计 53,438 行。`TableCatalog`、导入工具和提取工具均使用这份清单。
- 同一原包找到 `reward14_lesson.json`（24 行），加入服务端依赖表。
  `takeLesson` 的领取条件、幂等处理仍待实现；找到奖励表不等于已开放领奖。
- 原提取工具 `decode('ascii', 'replace')` 损坏了 11 张已部署表的中文/日文。
  109 张同名表全部可由该旧解码方式复现，其中 98 张解析结果相同，11 张不同。
  详细路径差异数、修复前后指纹见 `unicode-repairs.tsv`，并非原版数值规则改变。
- 提取器按 TextAsset 名称长度、脚本字节长度和 JSON 根键定位，原样保存 UTF-8，
  保留字符串里的 `,}`、空表和尾逗号；拒绝同名重复资产。
  `table-inventory.tsv` 记录 662 张匹配表的原始偏移、长度和 SHA-256。
  此提取器针对已验证的 PC 表包布局，不声称支持所有 Unity 格式。

## 本次确认的响应结构（尚未接通业务）

下表用于后续实现审查，**未直接改写占位成功响应**。旧 `api_contract.tsv` 的扁平提取
结果在这些接口上不完整；不能把零值/空表生成器当成关卡实现。

| 接口 | 原客户端消费的结构 | 证据（原始反编译树） |
|---|---|---|
| `quest/getQuestProgress` | `<type>.last.{quest,chapter,area,step}`；story 另读 `current` 同结构 | `QuestDataCache.cs:790–857` |
| `quest/getChapterData` | 根 `complete`、`clearCount`；`areaN.{complete,maxStep,step}`；可选 `areaN.itemN.open` 数值 | `PluginRunner_DoOniQuest.cs:86–122`；`QuestDataCache.cs:915–950`；`QuestStoryAreaSelector.cs:57–97` |
| `quest/getQuestCompleteFlags` | `quest_<type>_<id:D4>.chapterN` 数值；不能在根层平铺 chapter1…5 | `QuestDataCache.cs:899–908`；`QuestStorySelector.cs:177–187` |
| `quest/getQuestRewardOpenFlags` | 当前请求关卡的 `chapterN` 布尔值；不是完成标记的数值类型 | `QuestStorySelector.cs:190–212` |
| `quest/executeQuestEx` | `executeInfo.{step,missionPoint,now}`，`eventInfo.{eventType,eventScript}`，`rewardInfo`、`bonusInfo`；事件另有条件子结构 | `QuestScriptCommand.cs:490–540,749–785`；`PluginQuestStepHelper.cs:27–54` |
| `quest/checkCompleteQuestEx` | 若有 `reward`，UI 读取 `reward.area/chapter/quest`；`toInbox` 按层级检查 | `QuestScriptCommand.cs:993–1049`；`PluginQuestStepHelper.cs:57–83` |
| `battle/executeBattle` | 请求有嵌套 `battleInformation`；QUEST_BATTLE 使用 `questType,encountId,deckIndex`。响应共用 `log,information,process,result`，额外结果按存在性读取 | `WebApiClient.cs:1519–1531`；`BattleLogManager.cs:5563–5593` |

`eventInfo` 的敌兵/首领分支读 `encountInfo.monsterId/encountId`，玩家相遇、障碍、
宝箱、大型首领各有不同子结构，不能由通用空表替代（`QuestScriptCommand.cs:583–744`）。
`encountId` 必须关联此前生成且尚未结算的玩家事件；原服务端分配算法未恢复。

战斗包装方法虽标注 IgBinary，`WebApiClient._httpCall` 实际按响应 Content-Type
选择解码，且该版本调用 `sendRequest(url,form)` 未传 `param.responseFormat_`
（`WebApiClient.cs:275,300–318`）。因此不能把缺少 IgBinary 编码认定为当前战斗阻断原因；
JSON 可以被该客户端解码。真正缺少的是事件状态、完整战斗过程和一致的结算。

## 表数据能证明什么

`QuestIndexTableAccessor.cs:266–314` 定义 story/random/event/random2/event2/event3
为 1…6，索引名 `quest_{type}_index.json`；区域名和键由
`QuestAreaTableAccessor.cs:207–245` 拼接；奖励表由奖励 ID 前三段拼接
（`QuestRewardTableAccessor.cs:36–41`）。旧报告“其余 966 张均可忽略”的结论已撤回。

原始新手关卡是表中存在的 `quest_1_0000`：索引行 `0_1`，1 区域，10 步。
区域表第 5 节有 enemy，第 10 节有 boss；不能以持续无事件或跳过战斗实现通关。
第 10 节 `stepCount=-1` 是客户端的终段标记；空 cost 被 accessor 读成 -1，
不能据此猜成免费、返还行动点或统一扣 1 点。

检查 257,567 处关卡奖励 ID 引用，发现 23 个不同 ID 在本包目标奖励表中不存在，
见 `unresolved-rewards.tsv`。扫描包含未启用内容，这不代表存在 23 个实际运行报错。
新手表 `quest_1_0000` 的奖励引用未发现缺行。

31,402 个事件 ratio 值大于 100；原表字段名和 accessor 能确认位置，不能证明
服务端抽样、分组与保底规则。尚不可把这些值直接作为百分比。

## 下一步与缺失分类

优先建立同一玩家的进度、未完成事件、战斗记录、已领取奖励状态，再实现查询、推进、
战斗结算和重复请求保护。初始开启位置、行动点恢复/扣除、概率规则及战斗公式仍需证据。
动态表恢复后，必须再跑客户端验证实际请求顺序与失败点。

- `stub has no assets`：现存固定表 `combo.json`、`strategy_battlefield.json` 仍未找到；
  新增关卡表不会消除此前 10 个请求资源缺失。`assetbundle.json` 来自主包，不在本表包。
- `no stub response`：仍须实现的业务接口；本批没有减少 357 个占位数。
- 奖励缺行是已存在原表内的引用缺口，与上述两种问题分别记录。

复现：

```powershell
python tools/extract_tables_from_bundle.py --bundle <原表包> --out <表目录> --report <报告.json>
python tools/audit_quest_tables.py --table-dir <表目录> --out <审计目录>
python -m unittest discover -s tests -q
```

提取工具会报告表包本身没有的 `assetbundle.json` 及上述两张缺失表，并返回非零；
三项不允许用空表填充。合并来自主包的真实 assetbundle 后，完整目录仍缺两张表。
