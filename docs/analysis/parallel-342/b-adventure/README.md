# B 组：物语、战斗与巨大战静态复核

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`；分支
`parallel/342-b-adventure-20261115`。仅处理任务指定的 35 个入口。
没有部署、修改共享客户端或其他工作树。

## 可集成实现及边界

新增 `app/business/adventure_services.py`，显式注册四个查询：
`getQuestProgress`、`getChapterData`、`getQuestCompleteFlags`、`getQuestRewardOpenFlags`。
**未挂载生产路由；需要可信存档生产者/迁移。不能据此宣称新角色可以进入或通关物语。**

- 进度按原索引验证关卡、章节、区域、步数；仅投影保存的 last/current。
- 章节 maxStep 取原索引 areaStepN；完成状态、clearCount、步数和可选 itemN.open 取存档。
- 完成标记为裸 `quest_<type>_<id:D4>.chapter1..5` 数值；奖励开启标记是布尔值，两者独立。
- 原始客户端 `PluginQuestDataManager.cs:135-139` 无条件读五章，故要求存档明确提供五项，
  不靠省略字段或默认 false 蒙混过去。0/1、启用且客户端可见的索引是本实现支持子集。
- 未知初始位置、缺失存档、损坏记录明确失败；不会生成教程位置、补发资源、奖励或战绩。
- 继承 PlayerServices 的认证/存档调用，经 GameplayService 玩家锁执行；不新增写入玩法。
  基线状态标准化可能保存既有通用默认字段，adventureV1 不由查询创建或更新。

`adventureV1` 是**本服务内部建议结构，不是原协议**。其中 version=1，progress 保存按类型的定位；
quests 以原关卡名为键，保存 completeFlags、rewardOpenFlags、chapters。
chapters 的字符串章号对应 complete/clearCount/areas；areas 的字符串区域号对应
complete/step/items，items 的 1..4 对应数值开启标记。完整测试示例见
`tests/test_adventure_services.py:snapshot`，其中步数/clearCount/开启标记都是合成测试数据，
不是原版初始存档证据，也不可直接迁移到实际账号。

## 证据链与未决部分

`reviewed-endpoints.tsv` 一入口一行，共 35 行，分别标注限定查询、只有包装器、消费者部分证据、
非普通玩法；不是 35 个完整玩法实现。`evidence.json` 记录原始路径、SHA-256、包装方法、参数、
直接调用位置、手工回调/辅助方法证据和兼容决策。直接调用扫描只提供索引，不宣称覆盖反射调用。

原包程序集指纹与既有 source-proof 一致；没有使用旧 E 盘实现。
`table-audit.json` 本次重新解析六张索引和新手区域/奖励表并记录散列。
`tests/fixtures/adventure` 仅收录七条原索引行和来源散列，没有上传整表包或原客户端源码。

索引 `0_1` 确认为一地区、10 步。原区域 `1_1_5.event1` 的事件类型为 6，
`1_1_10.event1` 为 7，末段 stepCount=-1；前批 QuestAreaTableAccessor / QuestScriptCommand
链路分别指向敌兵和首领。空 cost、ratio 和终段标记不能证明服务端费用、概率或胜负。
所以推进、开箱、完成结算、战斗尚不实现，未注册任何空成功/拒绝处理器来冒充业务覆盖。

遭遇恢复的新增证据：getQuestEncount 的 `<type>.questId` 是字符串关卡名，而非数值 questId；
同层 chapter/area/step 为数值，根 entry 非空阻止首领恢复。getQuestEncountWorks 的
obstacle.<type> 另读 amount/needAmount/category/type。余额与实例生命周期未闭环，继续待办。

战斗结果需 log/information/process/result 共用树；回放必须读取真实已保存过程，不能重发奖励。
巨大战四入口属于活动报名/阶段信息/战斗追加结果/活动历史结果，排期和多人阶段事务未复原。
五项目前仅发现包装器证据：getTurfWarReplayData、getVsCountryRecords、executeQuestEx2、
getAutoStep、useSoulToStep；未从名称推断响应或玩法。

## 验证

在 B 工作树执行：

```powershell
python -m unittest discover -s tests -p test_adventure_services.py -v
python -m unittest discover -s tests -q
```

12 项独立测试覆盖真实索引步数、裸根/布尔类型、重登持久化、认证/账号隔离、无初始赠送、
缺表与缺行区分、非法请求/损坏记录、并发重试、响应副本隔离、基线保存冲突与未挂载范围。
测试使用内存状态和隔离账号，不涉及共享数据库。没有扣费/跨账号写入业务，故费用不足、
奖励回滚和跨账号事务不是本次测试可证明的功能。
完整回归结果记录于 validation.json；既有测试产生 ResourceWarning，无需为本组修改公共测试。
尚未做 Unity 动态验收；最小取证步骤与具体集成建议见 integration-notes.txt。
