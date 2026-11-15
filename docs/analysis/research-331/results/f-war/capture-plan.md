# 汇总对话串行抓取方案

本轮没有启动 Unity；保持原游戏尺寸，监控面板同尺寸对齐。本机和局域网分别记录配置，
沿 **客户端→hosts→proxy80→stub** 保存脱敏请求、响应、时间和前后存档；不改生产玩家。

前提：独立测试账号、I 的隔离活动事务、可用原战争资源；需要原服行为时优先有来源的历史录屏/捕获。
对模拟服候选的流量只能验证兼容性，不能反证原服公式。

| 场景 | 入口／预期API | 需要记录 | 能区分的问题 |
| --- | --- | --- | --- |
| 开期与自动报名 | 城下町活动→getEventStatuses→getWarSituation→entryWar | event status、selfBelong、实际请求是否仅 token、返回 team、存档唯一 entered | 客户端自动报名与用户选择阵营；缺活动是否错误显示运行 |
| 首次选场 | 世界地图→详情→确认→entryBattlefield | 实际 battlefield 字符串、发包前后画面、唯一 selected | catalogue ID 与 active slot；失败时本地先改字段是否会残留 |
| 同场重试／丢回包 | 丢弃首次成功回包后重试，随后重登 | journal 次数、team、selected field、资源余额、缓存清理 | 成功回放是否只赋值而无重复资源增量；重登是否从权威状态恢复 |
| 转场 | 明确原 isMovable=true 时换场→moveBattlefield | 可移动资格产生时点、原时间字段、费用、失败恢复 | 按日界线还是滚动冷却；不是凭2012访谈摘要采用24小时 |
| 关期但无结算 | 到 closesAt 后请求报名、查询 | 不再追加；内部 closed 与原 UI close/result 的差别 | 不把内部归档误发为已结算/可领奖 |
| 城战投入／放出 | getBrief→enter→getSiegeStatus→openingBet→B战斗→discharge | spot/charge/costs/record、真实战斗ID、前三资源和black魂增量 | 投入系数/上限/取整、胜败蓄力、重试是否重复扣费；先测小额合法投入 |
| 战绩／奖励重载 | 原结果页 load、关闭、重开、重登 | getResultLog与receive/look请求区别、ledger、gain*、无names/victory/responseId冲突 | 查询和领取副作用、丢回包后是否刷新余额、一次性发放 |
| 国战路线与命令 | traceroute→getCommandInfo→march2(seqId)→cancelMarch | 原地图、seqId、route、currentForceSize、资源、冷却 | 有效期/重复提交/路径占用；地图缺失先报assets，不造路线 |

仍缺的静态材料：五个 iframe 原正文及 JS（带原 URL/散列），strategy_battlefield 原表。
同版本录像应包含活动标题、时间、完整报名到结果过程；截图不能证明调用次数或回包字段。
