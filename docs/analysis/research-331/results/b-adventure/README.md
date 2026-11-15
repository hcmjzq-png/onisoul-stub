# B：常驻新手前缀、普通战斗输入与 Raid 证据

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`，分支
`feature/research331-b-adventure-20261115`。只修改 B 授权文件；未部署、未合并、未使用生产玩家或共享 Unity。

本轮把 `story/0/1/1` 从人工 adventureV1 快照推进为**操作产生的前 5 步**：
打开 → 剧情两步 → 武将奖励 → 宝玉奖励 → 敌兵实例 → 查询/重登回读。
原表完整目录的隔离 smoke：MP 25→20、武将实例 +1、宝玉 +1、保存敌兵 `q_mons_0000_01`。
第五步以后没有权威战斗求解器，**没有通关、章节完成事件、击杀记录或胜利回放**。
验收中的完整章节仍未达到；原客户端无步进标识，HTTP 推进也仍待接入。

## 本轮新增证据

1. `assets` 不是客户端步数快照：`WebApiClient.cs:1773-1783,1999-2009` 固定传 `map0`。
   网络重发没有 nonce，下一次用户步进的请求参数也相同。CAS 只能防并发覆盖，不能识别
   已提交后的串行重试。没有把时间窗口、每请求 UUID 或参数 hash 冒充解决方案。
2. 从固定 SHA 的原 `tableAssets.bin` 验证 `monster_story_1` TextAsset，偏移 `51248076`，
   长度 `102510`，SHA-256 `e29a3e2bb2d320c3a61014b25c8f400e813a823e161e73c485a0711e2e3bbdd4`。
   `q_mons_0000_01/02.maxHp` 分别为 1000/1200；只有名称、HP、声音和外观，**没有攻防/伤害算法**。
   完整原表在容器内，当前 runtime-tables 未导出；不是永久丢失的原资产。
3. 原新手第 3/4 步分别引用 `quest_1_0000_03_002/003`。每行只有一个正权重候选、
   一个 A 组、数量上下界都为 1；对应 `item01_0032401` 和 `item08_0102701`。
   `HTMLTreasureMediator.cs:113-138,161-174` 对同类 quest 奖励表合计 ratio，再显示总权重/条目权重；
   因此不能把 ratio=10 直接解释成 10%。结合确定事件及单候选，本组件限定发 1 个；
   这是有客户端展示语义支持的有限解释，不是通用服务端抽样算法。
   战斗奖励 `quest_1_0000_06_0001` 的 C 组同时有 10/15/20 数量候选，明确不取最低值、不全发。
4. 同服别、邻近时期的 [2014-04-22 台服邀请实测](https://lbear.pixnet.net/blog/posts/5057011406)
   记录独立物语新手教学、途中得到角色、任务报酬与城镇教学报酬分开。它支持流程，不能证明网络字段或掉率。
   [2014-07-15 中文 FAQ](https://gwz.yeyou.com/news/07152014/144412723.shtml) 的一般物语步进描述可交叉核对；
   其“恶鬼挑战消耗物语点”与原 `raidBoss.costBp/costBpFriend` 和 `RaidBossTableAccessor.cs:77-94` 冲突，未采纳。
5. Raid 原表链：`raidBossEncount_1_0001` 的四个候选、各权重 25，只是候选表；
   `RaidBoss.cs:122-145` 分别读取 ownerInfo/raidBossInfo/entry，并按 own/friend 读取两种 BP 费用。
   `raidBoss1_00001_01` 中自身/援助 BP 为 20/10，技能引用 `mskill1_00003_01`。
   `raidBossLevel` 是倍率表，`raidBossBattle` 的示例行只是 suffix，不能据名称把它当战斗算法。
   [2014-02-06 Capcom 公告转载](https://www.4gamer.net/games/150/G015000/20140206069/)
   明确活动日期和怪物技能/掉落关联；未将日服旧排期用于台服或 2026 年。
6. `QuestDataCache.cs:743-765` 是队伍预览属性求和；`BattleParameters` 是数值容器；
   `BattleLogManager.cs:3250-3312` 按服务端 process 的数字键排序并消费战斗事件。
   编队顺序、预览总和、建议战力不等于先手、技能触发或伤害公式。
7. `battle/getVsBattleLogs` 仍归 B：原 `getStrategyBattleLogs(string force,...)`
   在 `WebApiClient.cs:3894-3901` 调用此路由。真实记录尚未生产，不从库存或教程遭遇推导 PvP 胜负。

原文件散列见 `original-source-proof.json`，原表定位/样例见 `table-findings.json`，
逐来源版本、访问失败和采用范围见 `external-evidence.json`。没有将 403 搜索摘要当全文。

## 实现及限制

- `app/business/adventure_events.py:66`：显式 story 开放；缺档创建五章旗标和首区域零进度。
  `adventureV1` 已存在时不清空、不迁移、不重发。其他类型没有活动授权，拒绝开放。
- `app/business/adventure_events.py:137`：内部 `StepIntent(player_id, operation_id, expected_step)`；
  操作标识和预期步数双重约束。一次保存包含 MP、奖励实例、收集旗标、进度、事件和永久收据。
  重试返回 `errorReason`，不重放 `rewardInfo`；原 `RewardProcessor` 会增量增加角色计数。
- `app/business/adventure_events.py:254`：只接受上述两条单候选奖励；拒绝变动数量、第二候选、
  不明物品、背包溢出和随机事件。角色使用既有一级初始实例结构，数值从原 character 行读取；
  一级/一阶、零附加/经验、无技能是**本服兼容初始化策略**，未声称原服生成技能已恢复。
- `app/business/adventure_battles.py:17`：从真实 pending 遭遇与本人 quest 编队准备内部输入，
  保留保存的属性和技能，验证位置、归属、重复卡及非空编队；未解析的装备/兵法修正拒绝。
  不注册 executeBattle、不输出战斗日志、不扣 BP、不调用通用发奖函数。
- `AdventureServices` 的四项查询继续只读，并新增注册白名单参数。障碍模块未改，
  `clearObstacle` 已解除重试拒绝、不给第二次 uses 的修复保留。

没有修改初始 5000 金钱/其他资源 0、MP/PP/BP 初始规则，不在读档时补满。
收集标记来自本次步骤发放记录；不由当前库存倒推，也不因卖掉奖励卡而删除历史。

## 接入与验收口径

`integration.patch` 仅交付公共接入变更，未应用：补原怪物表清单，并将 13 个未就绪 B 写入/结算占位
改成明确失败。它们仍计为占位，不能把拒绝 handler 统计成玩法恢复。
当前普通占位会返回空成功，本分支没有掩盖这个基线事实。具体接入前提见 `integration-notes.md`。

35 项端点全部在 `endpoints.tsv`。本轮 12 项有新的证据或组件增量（另 2 项障碍保留既有修复）；
这不表示 12 项的全部规则补齐。可接入完整章节闭环 **0**，可测试内部操作片段 **1**，
正式注册减少 **0**，Unity 验收 **0**。支城完成事件给 A、真实战斗/击杀给 G 的生产条件仍未达到。

测试命令与最终数量见 `validation.json`；包含原表完整目录内存 smoke、并发、CAS、重复回调、
资源不足/容量/坏引用不半写、重登回读、归属验证，以及接入 patch 的内存应用验证。
没有真实 MySQL 多进程验收。下一步的单客户端采集步骤见 `capture-plan.md`。
