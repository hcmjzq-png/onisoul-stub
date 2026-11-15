# 三套战争的时序及证据边界

原代码目录：`C:/Users/74378/AppData/Local/Temp/onisoul-static-original-20261115`。
目标包 `OniSoul_Setup_20140712.exe`。下列为客户端时序，不冒充原服务器实现。

| 系统 | 开启／报名／配对 | 行动／战斗 | 结算与日志 | 本轮处理 |
| --- | --- | --- | --- | --- |
| siege 攻城战 | 活动信息→getBrief→检查编队→enter；getBrief 读取 day/stage/isEntry/attacker/defender/role；getPairings 展示同一期国家配对 | getSiegeStatus→openingBet(spot,food,wood,iron)→B 的城战战斗→discharge；成功投入回调扣三个资源，放出回调读取 gainBlackSoul 并刷新 charge/record/dischargeLogs | 按期、日段、城门累计需独立状态；getSiegeResultLog/lookSiegeResult 共用显示器，但不证明同一发奖副作用 | 不挂载；当期公告能证 24 小时日段，不能证国力相邻配对算法、资源公式或奖励事务 |
| strategy 国战／大合战 | getStrategyBrief→getMercenaryEmployInfo→entryStrategy；佣兵费用成功回调扣显示金币；getStrategyStatus 进入战场 | traceroute 回 reachable/route/coolTime/seqId→getStrategyCommandInfo→march2(seqId)；其他行动共用结果处理器但字段不能混用 | PromptReport、cell/action/battle/personal logs 需真实动作/格子结算；lookStrategyResult、WinLossRecords 依赖战局结算 | 不挂载；strategy_battlefield 仍缺失，isAlive/history 仍仅旧投影 |
| turfWar 天下分目／天下割据战 | getWarSituation 返回 selfBelong；活动 open 且 team=none→entryWar 自动报名→返回 team；首次选择 catalogue ID→entryBattlefield | 前端先改 Battlefield，再发请求；isMovable 分支才调 moveBattlefield；战斗由 B 处理 | receiveTurfWarReward 与 getTurfWarResultLog 共用 HTML 转换器；不能把内部关期当发奖或已看结果 | 已实现受限报名/首次选场事件生产与回读；全局战况、战斗、转场、结算不接 |

## 客户端锚点

- siege：`siegeBriefMenu.cs:90-185,445-455`；`siegeBriefMenuDesc.cs:setup`；
  `vsSetting_Siege.cs:744-765,775-811`；`WebApiClient.cs:4076-4117`；
  `SiegeResultRenderer.cs:39-96`；`HTMLSiegeMediator.cs:61-118`。
- strategy：`StrategySelect.cs:196-238`；`StrategyMoveableRegionSelector.cs:145-168`；
  `StrategyCommandResultProcessor.cs:17-112`；`StrategyResultWindow2.cs:150-278`；
  `HTMLStrategyMatchMediator_History.cs:179-248`。
- turfWar：`WebApiClient.cs:2784-2839`；`TurfWarBriefCache.cs:235,349-393`；
  `TurfWarWorldMap.cs:146-166,195-202,291-328`；`TurfWarInformation.cs:37-49`；
  `TurfWarDetail.cs:80-103`；`TurfWarResultRenderer.cs:61-195,209-235`。
- 原 `turf_war_battlefield` 的 `battlefield01/02/03.catalogId` 分别为
  `battlefield_0000101/0000201/0000301`。它们引用原 catalogue 的三行，不是 111 个战场全开放。
  表中的 day0..4/rewards 并不能证固定五天赛程或发奖抽样算法。

## 外部交叉核对结论

E01 的东／西军三战场和 E02 的国家分组支持 turfWar 分类；原 token-only 的 entryWar 保留最终协议约束。
E06 大陆服宣传的自由选阵营与早期日服说明不同：不把它转成新字段，也不强称已恢复 2014 台服分组算法。

E03 台服公告明说攻城战开期后满 24 小时日结，E04 日服分日列时间。这是运营实例证据，不能把 UTC+8
日期显示（TimeFuncs）理解成零点结算，也不能把天下分目、攻城、国战排期统一。
E05 玩家文图可以定位 siege 的投入和放出顺序；与原回调相符的只是行为阶段。
胜负、20 连胜、好友黑魂和收益数学仍缺对应原表/战斗证据，保留 hypothesis。

旧网页证据保持只读：`parallel-342/f-war-campaigns/html-lifecycle.md` 与 `web-evidence.json`。
已证原 app.html/app.js/unityProxy.js/commontool.js 不等于取到五个 iframe。
`func/isMe/def0Rank/responseId/names/victory` 属于中介或桥接生成，不当作 HTTP 原始字段。

## 可执行状态与尚未执行的部分

新日志只包含 `entered`、`selected`、`closed`（本服内部 schema），日志生产和查询校验使用同一状态机。
原公开结果 API 绝不读取这些内部事件当作战斗日志。未参战的个人登记状态可由真实空 journal 得到，
但不能由其推出全国 0 分、平局、国力或奖励为 0。未声明活动也不能返回成功空记录。

未获得同版本录屏的可核验操作序列；搜索词与失败记在 external-evidence.json。
接下来需要的是 B 的真实战斗提交和 I 的事务适配，以及 capture-plan 中列出的具体运行证据。
