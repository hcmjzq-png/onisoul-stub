# F：战争分类复核与天下分目选场登记

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`；分支 `feature/research331-f-war-20261115`。
本轮仅修改任务授权的 F 文件，未部署、未操作原客户端或生产玩家。

交付覆盖 **47/47** 个入口，见 [endpoints.tsv](endpoints.tsv)。新增的是天下分目战的受限登记流程，
不是三种战争的完整恢复。统计口径：**11 项入口补充了版本/规则辨析；1 个隔离登记闭环；
2 个新候选处理器；达到正常客户端接入条件的闭环 0；正式注册减少 0；Unity 验收 0**。
原有 pairing/history/isAlive 三个投影仍无权威战争生产者，不申请挂载。

## 新证据与排除的猜测

- `turfWar` 是天下分目／台服天下割据战，旧 F 报告的“公会战”分类有误。
  [2012-05-25 官方资料转载](https://www.4gamer.net/games/150/G015000/20120525074/)
  说明东／西军与三个战场；原 `TurfWarBriefCache.cs:349-393`、三条 `turf_war_battlefield`
  和对应 catalogue 行共同支持分类。它不包含 strategy 的行军、兵力或 siege 的城门投入。
- 新核对 active 表的三个 `catalogId`，HTTP 选场使用 `battlefield_0000101` 等 catalogue ID，
  不是 `battlefield01` 槽位。`TurfWarWorldMap.cs:146-166,195-202,291-328` 与
  `TurfWarInformation.cs:37-49` 构成完整参数链。原 catalogue 有 111 行，不能全部当作本期开放。
- [2013-06-18 台服公告转载](https://www.games.idv.tw/news.php?nid=9540) 给出当期攻城战
  6/21—6/24、开战满 24 小时结算一日以及国力配对；
  [2013-08-22 日服公告转载](https://www.gamer.ne.jp/news/201308220014/) 列的是另一期三个日段。
  二者均不能成为本服固定活动排期或统一日界线；当期参与黄魂也不是通用登录奖励。
- [开发者早期访谈](https://game.watch.impress.co.jp/docs/interview/523851.html) 说国家划分东／西军；
  [2014-07-23 大陆服宣传](https://news.17173.com/content/2014-07-23/20140723093638401.shtml)
  又有自由选择阵营的描述。目标客户端 `entryWar` 只发 token、回调接收 team，不能添加 team 请求参数。
  分组算法仍未恢复；本实现只消费明确的服务端分组声明，不随机造原服配对。
- [2014-08-12 玩家流程说明](https://gwz.yeyou.com/news/08122014/151510978.shtml) 自述混用了台服资料，
  可辅助辨识 siege 的入场→城门投入→战斗→放出→日结阶段。好友优先、连胜 20、积分倍率、奖励数量
  均未升级为生产规则；源码回调只能证明字段与增减行为。没有取得可核验的同版本完整玩家录屏。
- 原父页／Unity 桥接与五个缺失 iframe 的旧结论保留；没有用截图或宣传文案补回调字段。
  `strategy/getStrategyBattleLogs` 与 B 的 `battle/getVsBattleLogs` 继续分开。
  既有 history.rate 的 float32/Int32 检查未放宽，原回归仍执行。

来源、访问失败、服别和每项采用范围在 [external-evidence.json](external-evidence.json)。
完整时序、分类和未恢复边界见 [lifecycle.md](lifecycle.md)。

## 已实现的受限闭环

`declare_turf_war`（内部显式声明）→ `entryWar`（实际报名事件）→ `entryBattlefield`（实际首次选择事件）
→ 同一事务存储 → 服务重建/重登 → `turf_enrollment` 回读 → 到期拒绝写入 → 内部 `close_turf_war` 归档。

生产模块：

- `app/business/war_campaigns_events.py`：声明、完整日志校验、按服务端时间判断活动期、关闭归档。
- `app/business/war_campaigns_commands.py`：实际请求生成 entered/selected 记录；从事务内玩家国籍取所属军。
- `app/business/war_campaigns_services.py`：两个候选端点、认证和参数白名单、事务提交后才成功。
- `app/business/war_campaigns_views.py`：只从事件回放生成 selfBelong/isMovable 片段，不造战况或战绩。

声明必须在开期前产生、具有独立 ID、明确时间、全体声明国家的分组和原表引用；不存在自动开期、
自动配对或按老公告复活活动。活动不存在、未开始、到期、坏记录、时间回退、国籍变化、额外参数均拒绝。
相同报名/选场重试只返回 team/确认，不追加事件、不重放资源增量。不同选场拒绝，不绕过 moveBattlefield。
查询不创建报名、关闭记录、历史或奖励。关闭登记只是内部归档，绝不生成 winner/score/rank/gainRedSoul。

明确的 **compatibility-policy**：本服登记不扣资源；仅首次选场；暂不接容量、额外资格、转场；
countryTeams 是需审核的运营输入而非恢复算法；活动实例固定，自动轮换关闭。未声称原服这些规则如此。
这些限制使组件可以隔离测试，不能据此向普通客户端宣布完整战争开放。

## 接入条件与剩余阻塞

必须由 I 实现同库存储的活动→玩家原子事务、唯一插入及持久事件记录。当前测试用临时 JSON 单文档
事务验证行为，未验收 MySQL／跨进程锁／掉电耐久。**测试适配器不可复制到生产。**
`turfWar/getWarSituation` 还需真实全局战况、battleRules、bonus、活动时间及排行生产者；
本片段不能覆盖到旧 `body()` 的零分假战况上。没有战斗提交及可靠结算，所以转场、战绩、领奖仍未实现。

[integration.patch](integration.patch) 基于固定起点，只含共享文件的显式候选接线函数与字段来源，
不修改默认注册器；[integration-notes.md](integration-notes.md) 给出 I/B/G 和汇总组适配要求。
仅加 handler 或 patch 检查通过不代表 ready。需要串行客户端验证的步骤在 [capture-plan.md](capture-plan.md)。

验证记录见 [validation.json](validation.json)。缺文件/不能加载为 `stub has no assets`；
缺活动、规则或坏引用为 `no stub response`。本轮未修复任何运行时资源 404。
