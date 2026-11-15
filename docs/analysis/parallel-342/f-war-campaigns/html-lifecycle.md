# 第二轮：原网页桥接与报名—结算链

## 原始来源和仍缺的页面

从 `C:\Users\74378\Downloads\OniSoul_Setup_20140712.exe` 用 innoextract 1.9 的 `-I data7` 重新静态解出缓存。
安装包 SHA-256 与本项目基线一致。共 159 条 `.d`，逐条 URL 去查询串后的清单、缓存散列和正文散列见 `web-evidence.json`。
原文件仅放本工作树忽略目录 `war_campaigns_local/`；不提交缓存、历史 token、网页整包或安装包。
复现脚本 `war_campaigns_web_audit.py` 会先验证安装包散列，永不导出 URL query/fragment。

本轮实际取得原 **app.html、app.js、unityProxy.js、commontool.js**。以下五个战争 iframe 路径有原桥接引用，
但安装包缓存无其正文：

- `strategy/strategymatch.html`：app.js:53-61。
- `strategy/strategy.html`：app.js:63-71。
- `siege/siege.html`：app.js:73-80。
- `siegeResult/siegeResult.html`：SiegeResultRenderer.cs:10。
- `turfWarResult/turfWarResult.html`：TurfWarResultRenderer.cs:10。

因此本轮补全的是**原父页面和 C# 中介消费者链**，不是已经取得五个 iframe 的 DOM/JS。
范围仅限这份安装包缓存；不证明页面从未存在，也不把五个静态引用直接计为五个新增运行时 404。
旧 E 盘 pcweb/server/AI 修改没有用于原版字段证据。

## 两种桥接，不能混作服务端协议

旧配对/日志页面：app.js:15-31 接收消息并调用 Unity.SendMessage；中介 `request` 取 HTTP 数据，
生成展示对象后调用 `reseiveMessage`（原拼写）；app.js:169-173 用 postMessage 发给当前 iframe。
例如 `func/size/isMe/def0/atk0/def0Rank/atk0Rank` 在 C# 中介内生成，不是接口必需的根字段。

结果页：`BrowserProxy.cs:65-101` 按网页传入的 `function/argv/receive/responseId` 派发，
`SiegeResultRenderer` 和 `TurfWarResultRenderer` 只绑定 `load`（另继承 echo/onEnd/playSe）。
HTTP 回包先经 convertHtmlParameter，再由 BrowserProxy 加 responseId，最后 unityProxy.js:103-140
删除 responseId 并调用等待的 JS 回调。服务端不应预置 responseId 或把展示文字当原协议值。

## 配对和历史的已证层级

| HTTP 入口 | C# 实际读取 | 中介生成的展示值 |
| --- | --- | --- |
| siege/getPairings | `pairings.0..N.defender.0`、`attacker.0`、可选 `attacker.1`，值为国家 ID 字符串 | 译名、位置派生的 Rank、isMe、size；不能反推服务端真实排名 |
| strategy/getStrategyPairings | 根 `match_01..N.a.0.countryId/rate`，`b.0` 和可选 `b.1` 同结构；`winReward/loseReward` 为奖励表 ID | 图标路径、第一奖励槽 countMin、attackerPoint 等；不证明实际发放第一槽/最低值 |
| strategy/getStrategyWinLossRecords | `totalCount`；`records.0..N.openTime`；每条记录内 `decisions.match_01..N.a/b.<slot>.countryId/rate` 和 `winner` | 日期、局部 size、译名、isMe、展示位置 Rank；totalCount=0 有明确分支 |

证据：HTMLSiegeMediator.cs:61-118；HTMLStrategyMatchMediator.cs:134-221；
HTMLStrategyMatchMediator_History.cs:179-248。`getDebugHash` 的国家、随机 winner 和奖励 ID 均未采用。
尤其**历史不是根 match_XX**：getOneRecordDebugHash 的 match 只是内层对象，
完整 getDebugHash 与实际 analize 都还有 records/decisions 层级；不能将内层对象当整包响应。
History.getDate→TimeFuncs.cs:10-13 明确按 epoch+8 小时生成展示日期，不证明服务器日界线或赛季重置时刻。
连续序号消费者遇缺口会停止，因此新限定查询对记录缺口整批拒绝，不截断成看似正常的历史。

新增两个只读投影：`siege/getPairings`、`strategy/getStrategyWinLossRecords`。
它们只读可信生产端保存的完整数据集，校验归属、时效和必要类型，过滤内部字段；
没有生成配对、胜负、奖励、赛程或排名。生产端仍未实现且没有挂载；不是完整玩法完成。
显式 `complete=True,rows=[]` 与不存在记录不同；只有前者可回真实空历史/空配对。
历史 totalCount=len(rows) 是当前“完整历史数据集”支持范围，不证明原服没有分页或保留上限。

## 报名、行动、结算逐边证据

| 阶段 | 已证行为 | 尚不能推断 |
| --- | --- | --- |
| 国战报名 | StrategySelect.cs:196-238 检查 emptyDeck、canEmploy、常备和佣兵不同时为零，再发 entryStrategy；成功扣显示金币，转 strategy | 两套牌具体合法性、服务器最大兵力/常备兵公式、队伍匹配及扣款去重 |
| 国战路径 | StrategyMoveableRegionSelector.cs:145-168：traceroute 回 reachable(bool)、route.0..N(格子字符串)、coolTime、seqId；随后 getStrategyCommandInfo("march")；确认后 march2(seqId) | 路径选择、seqId 有效期/绑定、重试重放、占格和战斗事务 |
| 国战行动回调 | StrategyCommandResultProcessor 读 isAlive/isExecuted；正常分支更新兵力/熟练度/冷却/资源；traceroute 回调已先更新 self.route | 服务端费用/技能/回合冲突规则；错误过滤不能撤销已更新的路径显示 |
| 国战即时报告 | StrategyResultWindow2.cs:150-278：reportHash.currentCellLog、mainlyCells、topRankers；窗口 hash 的 position/fieldCatalogId/matchId/team/commonEffectId 是另一来源 | 不把窗口参数和 HTTP reportHash 混合；兵力和贡献不能从 UI 默认值生成 |
| 城战报名 | siegeBriefMenu.cs:90-185：活动信息刷新→getBrief→未报名则检查卡组→enter→vsSetting_Siege；已报名可直接进 | 资格/敌手选择/报名原子性和周期切换 |
| 城战投入/放出 | vsSetting_Siege.cs:754-763 成功扣 food/wood/iron 显示并设 charge；784-801 discharge 读 gainBlackSoul 并刷新 situation/charge/record/dischargeLogs/selfDeck/costs/rival | 投入倍率、黑魂发放、失败退还、重复 discharge；table 系数不能取代缺失规则 |
| 公会战报名 | TurfWarBriefCache.cs:349-393：请求 getWarSituation（依赖、不归本组）；open 且 team=none 才自动 entryWar，返回 team | team 的分配算法、公会权限、容量和跨账号事务 |
| 公会战选场 | TurfWarWorldMap.cs:291-328 **先**改 Battlefield 和选中状态，再按 isMovable 调 moveBattlefield/entryBattlefield；成功时置本地 isMovable=false 并清敌手缓存 | 失败回调是否恢复、冷却多久、转场费用；仅返回 errorReason 不等于 UI 已回滚 |
| 结果入口 | PoliticButton.goStrategySelect/goSiegeBrief/goTurfWar 在 close 分支打开结果；缓存按钮的 open/pause/close 还可能由本地定时器改变 | 本地状态变化不是服务器已结算；关闭窗口清缓存/隐藏按钮不是持久领取证明 |

`StrategyResultPoliticWindow.setup` 另读 points/playerCounts/forceSizes/belongCountries/rates、won/team、
contributions.battle/supply.score/rank，以及 activityReward.winLoss/base/ratio/result/isCapOver。
这是候选国战结果窗的直接字段消费者，但 `strategyResultWindow` prefab 到该类的绑定本轮未验证，
不单靠名称就把它升级为完整 lookStrategyResult 契约，也不按 base*ratio 猜奖励结算。

## 城战、公会战结果字段与副作用边界

SiegeResultRenderer.cs:39-96 要求 `schedule.open/close`、`record.rank/globalTotalScore`、
`role`、`winner.dayN`、`attacker/defender.<序号>`。它在本地生成 victoryPoint/bonus，转换 schedule 为文字；
原 day 循环只是展示证据，不证明每场必须固定三天。

TurfWarResultRenderer.cs:61-195 深层字段：

```text
schedule.{open,close}; gainRedSoul; rank; score; defenseScore
global.end.{score,rank,defenseScore}
global.daily.<day>.{score,rank,defenseScore}
battlefield.end.<field>.{score,rank}
battlefield.daily.<day>.<field>.{score,rank}
bonuses.{fieldWon?,teamWon?}
```

该类用 `res.Add("names",...)`、`res.Add("victory",false)`，后者按 teamWon 键存在转 true。
**names/victory 必须留给客户端生成**，否则 Hashtable.Add 可能重复键失败。
转换器改写 daily/end 为数组、bonuses 为展示列表、schedule/rank/score 为文字；这些不是服务器原层级。
15 日循环是界面显示上限，不能推断赛季恰好 15 天。

`openLog` 调 getTurfWarResultLog，`openResult` 调 receiveTurfWarReward；城战同理选择 getSiegeResultLog/lookSiegeResult。
两个入口共用转换器只证明显示形态，**不证明读取与领取有相同副作用**。
网页重载会再次 load；服务器的已领取标志、奖励事务和重登去重仍须外部证据，未在本轮开放。

## 最小下一步

先取得以上五个 iframe 原文件及引用 JS（带来源 URL/缓存散列），验证 postMessage 消费和结果 load 次数。
由总集成安排独占客户端：分别观察新报名/已报名、路径取消与 seqId 重试、转场失败、结果页重载及重登。
记录客户端→hosts→proxy80→stub 链路与持久化前后差异；本机/局域网分开配置。
地图表缺失、网页正文缺失属于资源取证边界；缺真实配对/结算/领取规则属于业务未实现，不互相代替。
