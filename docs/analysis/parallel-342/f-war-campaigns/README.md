# F：国战、城战、公会战静态复核与限定查询组件

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`；只修改 F 独立工作树。
47 个入口逐行见 `reviewed-endpoints.tsv`，原路径、SHA-256、包装器行号和消费者导航见 `evidence.json`。
这不是 47 个完整玩法实现：部分字段消费者已证，部分仍只有包装器；HTML 下游尚未全部追踪。
未部署、未改共享注册表，**不减少全局占位数**。

## 可集成代码

`app/business/war_campaigns_services.py` 提供：

- `strategy/isAlive` 限定查询：使用既有玩家认证、读档和玩家锁，只读当前账号已保存的有效观测，回根 `isAlive` 布尔。
  缺观测、错误类型、过期或归属不符明确失败，不默认存活/死亡。请求不能指定其他玩家或上传状态。
  真实战斗产生观测的写入端尚未实现，因此**目前不能让普通玩家完成国战**。
- `mercenary_hire_cost`：按原 `defines.mercenaryPrice` 计算菜单报价。原表为 50，3 人报价 150。
  `StrategySelect_army.Cost` 和 `StrategySelect.entryStrategy` 成功回调扣显示金币给出依据；容量、报名资格、实际扣费事务均未实现。
- `command_cost_terms`：读取原 `strategy_command` 三个并列数组，保留 `fixed/force/diffMaxForce` 标签。
  不根据英文标签猜兵力单位、取整或贡献公式，不执行任何扣款。

`_warCampaigns.strategy` 的 `ownerId/observedAt/validUntil/isAlive` 是**模拟服内部观测存储格式**。
有效期是内部新鲜度限制，不代表原活动日期。此批没有观测导入 HTTP 接口、自动迁移或免费初始化。
读取不保存 `_prepare_state` 的兼容修补，重试/并发读取不产生资源或状态副作用。

## 状态链路：已见客户端转换，非还原的服务端状态机

| 类型 | 已证客户端边 | 尚缺权威规则 |
| --- | --- | --- |
| 国战 | getStrategyBrief 展示双方/回合 → getMercenaryEmployInfo 显示常备和上限 → entryStrategy(mercenaryCount) 成功后扣显示金币并进场 → getStrategyStatus 提供 map/battlefield/cell/self → 命令 → 日志/结果 | 报名资格、分队、地图和兵力计算、回合提交边界、胜负/奖励和原服持久化 |
| 城战 | getBrief 的 day/stage/isEntry → enter → getSiegeStatus 的 selfDeck/costs/rival/situation/charge/record → openingBet 更新 charge 并扣显示资源 → discharge 读 gainBlackSoul 并刷新状态 → lookSiegeResult/结果日志 | 投入上限/倍率取整、匹配、累计/放出积分、跨日结算、重试和领奖去重 |
| 公会战 | TurfWarBriefCache 在 open 且 team=none 时 entryWar → 回 team → entryBattlefield/moveBattlefield 成功后本地更新 Battlefield → B 的战斗 → receiveTurfWarReward/结果日志 | 分队及公会权限、战场容量/转移成本、积分周期、奖励发放与重登恢复 |

注意：公会战所依赖的 `turfWar/getWarSituation` 不在本组分配的 47 个入口中，仅作依赖观察，不修改。
原请求包装器存在不代表普通界面实际调用；`getStrategyOverview/getStrategyPairingsChat/getStrategyActionLogs` 等未找到普通 C# 调用，不能标记玩法完成。
`getSelfSituation(string battlefield)` 不发 battlefield；国战 `entryStrategy(string fieldName,...)` 不发 fieldName。

## 关键证据与纠错

1. `StrategyHUDController.cs:985-989` 对根 `isAlive` 直接解包 bool；不能以数值或字符串代替。
2. `WebApiClient.cs:3894-3901` 的 `getStrategyBattleLogs(string force,...)` 请求 **battle/getVsBattleLogs**，属于 B。
   `mypageBattleLogUpdateStrategy.cs:55-61` 的 logs/details/turfWarResultLogCount 不可仅因同名方法挂到 F。
   F 的无 force 重载由 `StrategyLogAnalizer.cs:815-820,1905-1964` 读取 battlefield/logs 及战斗明细。
3. `StrategyCommandResultProcessor.cs:17-112` 会读 isAlive/isExecuted，并在正常执行后更新费用、兵力和冷却。
   回空成功会造成客户端显示与存档脱节；`openingBet` 和 `entryStrategy` 的成功回调也会直接扣显示资源。
4. `siegeBriefMenuDesc.init` 的固定国家和 HTML mediator 的 `getDebugHash`/随机胜负只是客户端初始化或调试材料，未用于本服务。
5. 原表中有 strategy_command、siege_bet_rate 及三类 trophy，并不证明活动开放、掉落选择和结算公式。
   `strategy_battlefield.json` 和 `combo.json` 在给定 662 表目录仍不存在：这是 **stub has no assets**。
   未知玩法规则/缺权威观测是 **no stub response**；已有表缺某个引用行是单独的引用错误。

## 验证与限制

在本工作树执行：

```powershell
python -m unittest tests.test_war_campaigns_services -v
python -m unittest discover -s tests -v
python docs/analysis/parallel-342/f-war-campaigns/war_campaigns_build_audit.py
```

新增 10 项、完整回归 236 项通过，0 跳过。记录见 `test-results.txt`。
覆盖布尔存活/死亡、重新登录读取、账号隔离、参数伪造、过期/坏记录、并发/重试无写入、表解析和原佣兵报价。
只有内存隔离账号测试，没有共享客户端、服务器或真实活动操作。
本批不执行付费、奖励或跨账号写入，因此费用不足/扣款回滚/结算幂等测试不适用于当前组件；不得据此声称这些业务已验证。
只有内存状态重建/重登已测，数据库事务与真实 Unity 表现待总集成验收。

小样本 fixture 仅三条 strategy_command 和一条 defines 原表行，未包含整表、原客户端或数据库。
来源完整文件散列在 evidence.json；小样本与原行相等性由审计脚本核验。
共享挂载建议、B/G 对接和最小动态验证步骤见 `integration-notes.txt`。
