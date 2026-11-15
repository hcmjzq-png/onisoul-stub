# 新手初始化与解锁修复

基于 #64 / `4ceef1783fdba4b38e457ac43917967534dc83a7`。本次修改运行代码；未部署，未修改线上角色。
前序诊断见 [新角色复核](new-player-followup-20261115.md)。

## 行为变化

- 新角色只初始化系统任务 `0:C`，不再提前写入任务 1 的 `O`。原客户端按表判断资格、唤醒任务，
  然后正常提交 `changeState`；服务端仍校验前置、完成条件和奖励。`entity.created` 不代表完成新手。
- 活跃任务摘要 `O/A/F` 必须有相同状态的 `missionProgress`；明细也必须对应摘要。
  不一致时返回明确错误，不凭空生成时间、进度或完成证明。正常状态更新仍同时保存摘要和明细。
- 系统任务 `work0` 从默认开放位、已接受/完成任务和已证实等级条件计算。
  旧 `unlockBits` 仅为派生缓存，不能继续作为权限来源；客户端上报全部开放位会被拒绝。
- 原客户端 `phaseOpened` 先排队 `setWorkingValue`，稍后才在状态批次中提交任务。
  因此允许确认符合前置的任务接受开放位，但此时不持久化该位、不启动任务；真正接受后才持久化。
- 已完成任务重复领奖仍返回空奖励，不重复发放。未实现条件仍失败。

没有新增协议字段，也没有新增处理器：仍为 402 路由、80 专用处理器、322 占位。
本次不声称所有业务写接口都已加上功能准入校验，也不声称好友、邮件等玩法完成。

## 原版证据

来源是同一原始 DLL，SHA-256
`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`。

| 结论 | 原版消费点 |
| --- | --- |
| 摘要恢复、明细恢复、只唤醒未出现或 L 的任务 | `PoliticMissionProgressList.cs:738,1074,907,1181` |
| 空进度设置自动开始，opened 阶段继续处理 | `PoliticMissionProgressStatus.cs:217,304` |
| 先上报接受开放位，再排队任务状态更新 | `PoliticMissionProgressStatus.cs:432`、`PoliticMissionProgressList.cs:389,1200` |
| 默认且出现在发送映射中的 auction、presentBox、batchUpgrade | `PoliticButtonManager.cs:440,754` 和 `unlockList_`，位合计 `0x10120000` |
| 10 级开放截图 | `PoliticButtonManager.cs:694`，位 `0x02000000` |
| `all` 枚举不含 batchUpgrade，但客户端确实会发送后者 | `flagBtnUnlock.cs`、`PoliticButtonManager.calcNowUnlock`；合法传输位范围使用 `0x1fffffff`，不是把该范围全部授予玩家 |
| 任务 2 接受开放建设、完成开放拆除 | 原始 `politicMission.po_mission_00002` |

无映射的默认按钮不新增协议位；specialButton 的枚举值也不等于发送资格。
`lockStatus` 与剧情临时 `systemStatus` 仍是两层状态，不直接替客户端解除剧情操作锁。

进一步查找本地缓存后，找到了非空的新手脚本包，更新 #64 的“尚未取得脚本原文”状态：

| 原包 | 本地文件名 | SHA-256 |
| --- | --- | --- |
| scr1_000001，1785 字节 | `5d7056ff4b24ade99d4b7c78ddc79db3.unity3d` | `04346e21a0a2037a4379fd6142fc68cb2de2964fb9151a72470224ad8722109d` |
| scr1_000002，1970 字节 | `5a126726b7cc08e422e04a44f96d020b.unity3d` | `cbd2ab2d00ee142969b91dc3fbf5783795ac173559ca0cf629ea7c43f532631d` |

位于本机 `D:\onisoul\assets\pc\bundles\scr`；UnityWeb 解压可见非空 XML、对话和任务命令。
这证明资源存在，不等于已在真机播放通过，也不等于生产服务器已有对应资源。
普通进城 `scr2_000001` 的缺失/空候选结论没有改变，不能用空包代替原版流程。

## 旧档精确修复与上线次序

`tools/repair_initial_mission.py` 默认只读；线上执行预览得到 `scanned=6, eligible=2`。
候选必须同时满足：created；任务恰为 `0:C/1:O`；missionProgress、missionRewards、missionChecks 均空；
原表任务 1 的 index=1、isAutoStart=TRUE、bootCheckFunc=none。
只删除多出的 `1:O` 标记；资源、武将、建筑、姓名和其他键不变。正常提交会递增 revision。
进度更复杂的旧档不自动重置；已完成、已领或有明细的角色不在候选中。

由部署环境注入数据库与表配置，不把生产密码写入命令或报告：

```sh
python3 tools/repair_initial_mission.py --report /private/new-player-plan.json
python3 tools/repair_initial_mission.py --apply --plan /private/new-player-plan.json --backup-file /private/new-player-before.json
```

报告/备份拒绝覆盖已有文件，备份文件权限 0600。apply 在同一数据库事务中锁住所有指定角色，
核对前后哈希，备份完整旧档，再统一提交；预览后发生变化则拒绝，需重新预览。
失败留下的备份应保留；重新操作必须使用新的备份路径。

上线必须一起处理代码与已确认旧档，避免旧档被一致性检查拦住：

1. owner 合并后，在维护窗口备份代码、配置、SQL，并确认恢复路径。
2. 备份并移除服务器 `mission_chain.py` 的旧自动 O 补丁。只接受本次核对的旧补丁文件指纹
   `17d9614b6365c1c784fecc87f9cc342f27a3f9f95e182607da132ebf9f24abda`；不同则重新审核，不能覆盖未知改动。
3. 部署合并后的修复代码，使用最新预览计划应用这两份精确候选；对比其他字段及非候选档案。
4. 正常请求会把 unlockBits 更新为派生缓存。应先保留旧值并审核差异，不能把旧上报缓存称为合法授权。
5. 重启并沿真实域名链路验收新号、旧号恢复；出现未知状态时停止扩展迁移，不批量清空任务。

本轮仅把预览工具放在服务器 `/tmp` 并执行 dry-run，没有运行 apply、没有重启生产服务。

## 验证与尚未通过的真机验收

- 隔离 MySQL 8.4.13，127.0.0.1:33365，测试自建 UUID 数据库。完整测试发现 616 项：
  613 通过、3 项因该虚拟环境缺 IL 分析依赖跳过；这 3 项在系统分析环境单独执行并全部通过。
- 新增 8 项内存测试与 4 项真实 MySQL 测试，覆盖正常 HTTP 注册/登录/创建、任务接受/完成后的重登恢复、
  重复领奖不增发、未达条件的位不落库、批量修复第二次 UPDATE 失败及 COMMIT 失败的回滚。
- 历史 G/H 候选测试改用唯一上下文应用补丁，避免新导入使固定行号偏移。候选补丁内容没有修改。
- 真机使用独立账号、独立数据库、已核对的原版 app.unity3d，保持原窗口尺寸。网页从测试端口成功加载，
  但 Unity 没有请求该端口；首次出现“联机中断(1)”，重试仍未进入新手对话。
- 已查明 `Configs.setup`（1282–1289）不接受任意 host:port：未知地址退回固定正式域名。
  `login.js.getHost` 包含测试端口并不足以改变这个行为。本机 80 代理实际进程与旧记录不一致，未替换该未知进程。
- 测试客户端已关闭，config.ini 按字节恢复（SHA-256
  `1db6e36bf219e8ac5711d62729ed74dca9e375c97de257a67e44e646c39bc52f`）；hosts 和已有 80 代理均未修改。

因此**新手对话、真实领奖画面、建设解锁及界面重登续接尚未验收**。下一次需先核对并可恢复地切换
现有域名/80 代理到隔离服务，或在合并部署后用正常线上测试角色验收，不能用绕过任务或伪造脚本代替。
该阻塞是测试路由问题；资源缺失用 `stub has no assets`，接口无实现用 `no stub response`，不得混为一类。
