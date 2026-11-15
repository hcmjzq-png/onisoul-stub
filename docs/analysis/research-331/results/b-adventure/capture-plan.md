# 单客户端采集计划（交总集成串行执行）

本组未操作共享 Unity、hosts、proxy80 或生产账号。使用独立测试账号、原尺寸游戏窗口；
监控面板与游戏等大对齐。本机和局域网分别记录客户端→hosts→proxy80→stub，不混用配置结论。

1. 新角色教学入口：先记录 getQuestProgress/openQuest/getChapterData 的实际顺序、任务状态和点击点。
   核实新角色创建时初始化 story 的位置，不能将页面能解析当作原服奖励证明。
2. 适配层逻辑步身份实验：同一动作正常返回、服务端已提交但丢回包、两次用户点击、跨重登迟到重试。
   捕获脱敏原表单、稳定动作身份、expected_step、revision、收据键、MP 和奖励前后值。
   预期旧动作不推进；新动作恰推进一步。原始无标识表单无法区分，应保持拒绝。
3. 原表步骤 1→5：期望两个剧情事件、一名 item01_0032401、一枚 item08_0102701、敌兵 q_mons_0000_01。
   捕获 executeInfo/eventInfo/rewardInfo/bonusInfo、角色查询与收集图标；重点核对角色初阶技能实际形态。
   当前角色初阶策略是模拟服兼容选择，不能用模拟服自身输出反证原服相同。
4. 第 5 步重登：观察 getQuestEncount 是否被普通敌兵路径请求、EncountId 如何恢复、是否走 boss-only 分支。
   已知静态消费者以 getBossEventParameter 为前提；未证实普通敌兵恢复，不能直接复播带增量的旧 response。
5. 战斗/失败/完成：需要原始录像或原服响应实录，收集 battleInformation、双方 formation/skills、
   log/information/process/result、成功/失败/再战与 checkCompleteQuestEx 的先后。
   可区分“推荐属性=胜负算法”“按编队顺序=先手”“最低奖励=固定奖励”等假设；没有数据不实施这些假设。
6. Raid：分别本人和救援实例，捕获 entry.ownerId/index、ownerInfo、BP、共享 hp、limitDate、参与者伤害、
   SENDRESCUE 与确认完成。核对按所有者分账和失败重战；不在无授权排期时测试旧活动。

原表缺 monster_story_1 / 脚本或外观 AssetBundle 时记 `stub has no assets`；
缺操作身份、求解器、结算或错误引用记 `no stub response`。先分层定位，不混成“资源没有”。
