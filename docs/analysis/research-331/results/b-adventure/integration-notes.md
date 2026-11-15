# 总集成说明

基于 `8023c3f`，本目录 integration.patch **未应用到公共文件**。
可执行 `git apply --check docs/analysis/research-331/results/b-adventure/integration.patch`。
补丁只变更 `app/business/placeholders.py` 与 `docs/analysis/server_tables.tsv`：
13 个未完成 B 写入/结算保持占位但明确 errorReason；声明 monster_story_1，完整文件仍须受控提取发布。
默认总入口 402、专用 71、占位 331 不变，不把拒绝请求计作完成。

## 原表发布

原表证据：`table-findings.json` 的 monster_story_1；容器 SHA、TextAsset 名称/偏移/长度/原字节散列必须全匹配。
可以调用现有 `tools.extract_tables_from_bundle.extract_assets` 提取并验证，不改共享提取器。
不能把本分支两行怪物 fixture 当运行完整表。原始目录读取 smoke 仅在内存从容器加载该完整表。
文件/解析/未声明表失败报 `stub has no assets`；已有表中行 ID 无效报 `no stub response`。
不能以外部攻略替代外观或脚本 AssetBundle；本轮未证明那些资源全可加载。

## 注册白名单与启动顺序

候选六个可读/开放入口：

```python
AdventureEvents(service).register(registry, apis=frozenset({
    "quest/openQuest", "quest/getQuestProgress", "quest/getChapterData",
    "quest/getQuestCompleteFlags", "quest/getQuestRewardOpenFlags", "quest/getQuestEncount",
}))
```

当前不把上述调用加进正常 GameplayService.register；全链路尚不可玩。
`QuestDataCache.cs:654-674` 先取 progress，再有开放请求，所以总集成须在**新角色创建的同一次保存**中
调用 `open_story(player, {"questType": "story"})`，并核实教学进入条件。查询本身不得负责重置/补档。
候选 openQuest 只接受 story；必须保留活动、幻梦及已禁用项目的拒绝，不因表里有行自动开放。

executeQuestEx 不注册。内部接入调用：

```python
events.execute_trusted(original_params, authenticated_session,
    StepIntent(authenticated_player_id, stable_logical_action_id, expected_step))
```

三个值必须由拥有逻辑用户动作身份的适配层提供；不是从 HTTP params 新增的“原协议字段”。
原客户端没有该身份，现有服务端也没有该适配层；禁止从每次请求随机生成、从当前存档生成 expected_step，
或以相同请求体哈希去重。前两种不能防串行重试，后一种会永久阻止下一步。
安全方案需要客户端/受信任桥接在一次用户操作开始时创建身份，整个重试周期保留；
如果不改传输，不能同时保证正常连续步进与任意延迟重试不重复扣点。
这项限制不需要“原服抓包”才能证明，但解决方案需要单独实现并验收。

首次响应丢失：收据拦截重试，不再送奖励增量；重新读取权威人物/资源/物语状态。
旧脚本或插件不能直接对保存的 response 再跑 RewardProcessor；记录 response 仅供内部审计。
普通敌兵重登剧情恢复尚未证实，getQuestEncount 的已知消费者主要恢复 boss；不承诺第 5 步可自动重播。

## 内部数据与兼容决策

`adventureV1.storyLifecycle`、producer、events、receipts、operationId、sourceDigest、grants、
encounter 内 monster/winRewardId/lossRewardId/overKillRewardId、sourceRevision 都是**服务端内部**。
它们不加入原客户端回包。调用方只能以认证会话选账号，不能让 params 选玩家、奖励或胜负。

缺 adventureV1 的已有 stub 账号可以显式 open，含义为“本模拟服尚未运行新生产者”；
原服导入账号或已有人工快照不得按这个假设处理。现存 adventureV1 无 producer 则拒绝，交人工证据迁移。
任何读查询不建立章节、不发奖。已有 producer 的状态/收据异常同样拒绝，不按空档恢复。

新角色位置 0/1/1/0、五章初始 0/false、一次教程不重跑，是本服明确初始化/重试策略。
两个单候选奖励的 ID/数量来自原表；不是测试快照赠送。
grade=1/level=1/零附加/空技能沿用基线初始角色 schema，原服技能生成未证，属于限定兼容策略。
集成 C 的共享武将发行器后，应替换本地 grant_direct 的角色创建，保留同一事务与收据；
不能退回 items 中只计角色 item 而不生成可查询的武将实例。角色 ID 当前避开背包和仓库已有 ID；
统一发号/所有出售锁接入归 C/I，未来循环玩法需永久发号策略。

## I / A / G 交接

- I：操作读集合为账号、adventureV1、MP、items、characters/storedCharacters、容量、原表；
  写集合为 MP、实例/计数、items、进度/收集旗标、事件/收据。使用同一账号锁和一次 revision CAS。
  遭遇、扣点、奖励及收据不能分次保存；CAS 失败不向客户端返回成功或任何已授予增量。
  测试验证两个独立 service 锁下的隔离 CAS，未声称真实数据库部署验收。
- A：目前完成旗标全部保持 0；**没有** chapterCompleted 事件。不能用 step=5、开启记录或持有武将解锁支城。
  后续真正完成时需以 `playerId + questType + questId + chapterId + completionOrdinal`
  作为内部去重身份，将末首领已解决、奖励收据和旗标一并提交；该身份不是新增网络字段。
- G：step 事件和 pending encounter 不是战斗/击杀历史。当前真实战斗事件数量 0。
  后续 resolver 必须同一提交保存来源 encounter、双方、结果、伤害、结算和过程记录，G 只消费提交后事件。
  不从当前角色/库存/插件诊断日志推胜场；battle/getVsBattleLogs 在 B，F 供 strategy 对应真实记录。
- Raid：ownerId/index 对应共享实例，HP、参与者、救援资格与领取账本涉及多人。
  不能复用本轮单玩家 save 冒充跨账号原子性；共享事务/锁顺序交 I，求解及权限归 B。

## docs/api_schema.md 待合入条目

| 字段 | 来源 | 原消费者/限定语义 |
| --- | --- | --- |
| openQuest.addWork | bundle | QuestDataCache.cs:431-474；本服首次创建 story 工作为 true，重复 false，不代表活动解锁。 |
| executeInfo.step/missionPoint/now | bundle | QuestScriptCommand.cs:762-785；步数和余额是绝对值，时间为服务端 Unix 秒。 |
| eventInfo.eventType/eventScript | bundle | QuestScriptCommand.cs:749-759，QuestAreaTableAccessor.cs:190-203；本轮 1/2/3/6。 |
| eventInfo.encountInfo.monsterId/encountId | bundle | QuestScriptCommand.cs:616-627；本服每账号教程仅一次，ID 为已提交步序 5。 |
| rewardInfo、bonusInfo | bundle | QuestScriptCommand.cs:490-517；PluginQuestStepHelper.cs:28-53；物品→数值增量，重复成功不可回放。 |
| getQuestEncount.story.questId/chapter/area/step | bundle | QuestScriptCommand.cs:299-329；questId 为 quest_1_0000 字符串，不是数值0。普通敌兵自动恢复待验收。 |
| areaN.itemN.open | bundle + compatibility-policy | QuestStoryAreaSelector.cs:75-95；本服只由真实步骤奖励置1，不由现库存推导。 |

没有给 executeQuestEx2、getAutoStep、useSoulToStep 猜响应字段。
