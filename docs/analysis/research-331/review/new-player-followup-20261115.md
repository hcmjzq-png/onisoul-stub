# 新角色、新手任务与按钮解锁复核

2026-11-15，针对用户指出“新手任务逐步解锁功能”重新核查 #62 运行代码与原客户端。
本次仅只读线上数据、在内存复现及修正审核结论；尚未修改生产角色或运行代码。

## 两种锁与两类脚本

- `PoliticButtonManager.cs:808–815` 的最终可操作状态同时受 buttonStatus、lockStatus、systemStatus、charaOverStatus 约束。
  `lockStatus` 是功能开放状态；`PoliticMissionProgressStatus.cs:432–477` 按任务接受/完成解锁位更新。
- `PoliticOperator.cs:754–769` 的 lockOperate/unlockOperate 改 systemStatus、镜头与任务图标，是流程中的临时操作锁。
  解除这一层不等于完成新手，也不等于任务功能全开。
- 上次提到的 `scr2_000001` 是普通进城启动流程使用的 AssetBundle，其中预期脚本为 `scr2_000001_01`。
  它不是服务器启动命令，也不是“把新手任务做完”的开关；现有脚本候选为空的判断仍成立。
- 原表第一项任务 `po_mission_00001` 的 enterScript 为 `scr1_000001_01`，exitScript 为 `scr1_000001_03`。
  `PoliticFSMUpdater.cs:329–350` 明确先检查自动开始任务，有任务就走任务流程，无任务才走普通 Startup。
  没有取得脚本原文，不能编造它们的对话和执行内容。
- 用户所述逐步解锁有原表支持：任务 2 接受时开放建设、完成时开放拆除；任务 269 接受时开放好友；
  任务 13 完成时开放多项功能及 mailBox。编号不等于连续游玩顺序，依赖须按 bootCheckData。
- `presentBox`（InboxReader 收件箱）与 `mailBox` 不是同一入口。
  `PoliticButtonManager.cs:450` 默认开放 presentBox，`PoliticMissionProgressList.cs:1564` 也把它纳入默认开放位。
  不能把本次收件箱与好友点击无请求都解释成同一个新手门槛。

## 已确认的问题一：第一项任务“有摘要、无明细”

`app/business/gameplay.py:328` 在加载/创建时调用 seed_auto，将任务 1 写成 O（opened）；
但没有同步生成 missionProgress。`getMissionsInProgress`（同文件 804）只遍历 missionProgress。

实际 16:08:46 验收回包（已移除身份和时间字段）为：

```json
{"states":{"0":"C","1":"O"}}
```

```json
{"missions":{"po_mission_00000":{"state":"closed","work0":65536}}}
```

原客户端的消费顺序：

1. `PoliticMissionProgressList.cs:738` resetList 根据 states 保存任务摘要。
2. 同文件 1074 的 restoreMissions 只用进行中明细创建任务实例，此处缺任务 1。
3. 同文件 907 的 wakeupMission 仅唤醒 locked/摘要中未出现的任务（1181）；任务 1 已为 O，因而跳过。
4. 没有第一项任务实例，就不会设置 AutoStartMission，随后进入普通 Startup 分支并请求缺失的 scr2_000001。

因此上次把资源当成最先应修的根因不完整：**新手引导在服务端任务投影处已经断开**。
只补普通启动脚本并不会补回漏掉的第一项任务。

已用正常 GameplayService + 现有原表测试样本在内存复现：states 为 0:C/1:O，明细只有系统任务；
客户端的 restore 条件和 wakeup 条件都不包含任务 1。没有修改原客户端或线上存档。
只读检查线上 6 份档案，其中 4 份已创建角色，2 份原始存档存在任务 1 为 O 而无对应 missionProgress。
其他两份未出现此特征，不代表完成了全部角色流程审核。

服务器保留的 mission_chain.py 旧补丁还在 baseline_states 中提前生成同样的 O 状态。
主分支自己的 seed_auto 已能复现，因此不能只删除服务器补丁就宣称修复。

## 已确认的问题二：解锁位未经任务资格约束

`app/business/gameplay.py:827` 的 set_working_value 接受系统任务 work0 并直接按位 OR 到 unlockBits；
同文件 796 的 _unlock_bits 又永久合并 reported 位。内存新角色上报 0x0fffffff 后，服务端保存了全开位。
这与任务逐步开放的目标不符；现有 test_client_unlock_bits_survive_reload 只验证保留，没验证资格。
线上只读检查未发现 unlockBits 已是全开掩码，不能声称真实玩家已利用该问题。

后续修复必须识别原客户端默认开放位、任务合法开放位和其他已证实条件，并保留合法重登状态；
不能把任意上报原样接受，也不能用全清零处理旧档。原客户端中 presentBox 默认开放，尤其不能误锁。

## 对“角色体系”的判断与修复顺序

现有证据指向角色初始化、任务状态保存/恢复和功能开放的一致性问题，不能据此判断账号 ID、国家选择、
武将实例等整个模型都错误。entity.created 表示角色已建立，不表示新手任务已完成；创建后重登也必须能继续引导。

1. 定义同一任务的摘要与进行中明细一致性，修复新号初始化；回归客户端唤醒、接受、完成、领奖和重登恢复。
2. 对旧 O/无明细档案做带备份、精确条件和预览的修复，保留金币、武将、建筑、已完成任务及奖励记录。
3. 审核客户端默认位及任务开放位后，限制 work0 的可接受范围；不一次性开放全部功能。
4. 按真实新手路径定位缺失脚本/资源，再在达到条件的角色上验收好友、收件箱等。

此次修正诊断不改变 80 个专用处理器、322 个占位的计数。
