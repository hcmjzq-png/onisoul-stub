# 申请过期与收件箱领取追加复核

范围：继续 E 独立工作树和 PR #42；原程序集/反编译来源不变。未部署、未改共享文件，也未启用原客户端。来源路径、SHA-256、行号和搜索边界补入 evidence.json.followup。

## 好友过期：确认到哪里

1. 原 `defines.friendoffer_expire_time.value=604800`。2,034 个原 C# 文件没有该键的直接字符串引用；DefinesTableAccessor 只找到发送/接收上限访问器。这个结果不排除动态键访问，更不能说明原服务器不做过期。
2. FriendConfirmationWindow.cs:168-187 在执行确认等动作前调用 updateFriendData；只要 `remove` 含目标玩家 ID 就不执行动作，并从 `count.ok/send/receive` 重设窗口计数。remove 的值仅 ToString，未用于区分过期、拒绝、解除或其他原因。
3. FriendWindowControll.cs:118-127 只消费 count；HTMLBbsMediator.cs:720-733 只转发，不补足服务端清理策略。不能证明 updateFriendData 必须同步清理、定时任务频率、比较边界、双方通知/保留时间，更不能推断原服原因字符串为 `expired`。

因此没有新增猜测的自动清理，也没有把空 remove 称为完整实现。此前按 Unix 秒计算的截止拒绝仍为保守模拟服策略，非原服完整过期规则。本批强化有限数值、非负、非未来及双边创建时间一致校验，防止 NaN/Infinity/布尔值或错配记录绕过保护。测试覆盖截止前一秒、恰好截止、双方不一致、坏时间戳；全部不清理、不接受、不保存。

最小补证：原始服务端过期回包/可信历史抓包，或总集成在独占原客户端环境观察同一申请接近截止时 getFriends/updateFriendData/feedback 的响应和双方结果。只改变模拟服时钟得到的日志不能证明原规则。

## 收件箱：请求、回调、奖励、重试

| 链路 | 原版证据 | 结论 |
| --- | --- | --- |
| WebApiClient.cs:3451-3468 | getParcels(start,end)；resolveParcels(responses) | 请求中没有待发奖励，也没有领取幂等键；服务端必须按自身保存记录取奖。 |
| InboxReader.cs:92-177 | parcels.<id>.createdTime/rewards、totalCount | 返回对象和数字值可确认；日期由客户端转显示文本。makeDummy 的 name/text 不当作原服字段证据。 |
| InboxResolveWorker.cs:11-37,49-105 | 先减请求数，再按 failed.Count 恢复；成功 rewards 交 RewardProcessor | `failed` 值类型/错误码没有读证据；仅靠 succeeded 无法表达逐包失败。 |
| PluginRunner_DoReceiveMail.cs:12-66 | 查询 0..499，整表 accept，一次提交，读取每个 successful.rewards | UI 的 30 条分批不是已证服务端上限。此插件也要求重复成功记录含 rewards 空表，不能省略键。 |
| RewardProcessor.cs:51-73,164-185,239-246 → UserStatus.cs:648-656,990 | 四个资源 ID 对应 gold/wood/food/iron；逐项加增量 | 重放原领取 rewards 会重复增加客户端显示。只支持这四类，未按名称猜其他物品规则。 |
| WebApiClient.cs:190-216,255-275 | 相同 WWWForm 网络失败最多尝试十次，间隔三秒；httpCallId 只在本地使用 | 不能用客户端的本地计数当服务端去重键。 |

增加 SocialInboxServices 两个**未挂载**处理器，支持已保存且数量确定的四资源包裹。使用现有 PlayerServices、玩家锁、整行 save/revision。没有包裹发行端点，不从不存在的奖励表/历史活动生成奖品，不迁入旧 inbox/mailbox 数据。

内部账本 `socialInbox={version:1,pending:{id:{createdTime,rewards}},resolved:{id:true}}` 为本服务设计。发放资源、移除 pending、写入永久已领取记录在同一份玩家快照的一次保存中完成。禁止重新使用 ID、禁止不经审查裁剪 resolved、禁止额外 expiresAt 等未支持条件被忽略。跨账号发包仍须共享事务方案，不能用此单玩家领取逻辑替代。

同一包裹全量校验后才发放；超容量或不支持的奖励保留待领，同批其他合法包裹可以成功。整批的所有成功项只保存一次；提交冲突时任何成功结果都不发布。逐包原子失败、满容量不裁剪奖励属于保守兼容选择，原服溢出分配尚待证。

已领取 ID 再请求返回 `successful[id].rewards={}`，不重复入账，也不重复增加客户端资源显示。这是明确的兼容决策，**不是已恢复的原服重试回包**。丢失首次回包时客户端仍可能暂时少显示奖励；需要重新读取权威资源快照或重登，不能声称做到客户端显示的严格 exactly-once。未知 ID 返回 failed，可能短暂恢复多余 badge，需 periodicInquiry.inboxParcel 校正。

查询只回已证实的 createdTime/rewards/totalCount。降序时间加 ID 排序、包含 end 的分页与 500 条批量支持范围都是模拟服选择；原 pcweb 标题/正文消费和最终页面尚未验收。`end=-1` 返回剩余全部，来自 InboxReader 调试调用的兼容支持。原客户端当前磁盘缓存扫描 164 个 URL 头未命中相关文本路径；不是完整安装包缓存扫描，也不等于 stub has no assets。

## 集成前置条件与验证

- 显式调用 `SocialInboxServices(gameplay).register(registry)`，不自动改变 GameplayService。好友 7 个加收件箱 2 个共 9 个限定范围处理器，全部未生产挂载，全局计数不变。
- 总集成必须确定包裹来源与上述内部账本迁移规则；旧字段不直接导入。C 的卡牌/道具/容量、D 的其他资源事务仍未接入。不要把 name/text 的调试字段当原协议补齐页面。
- UserStatus.SocialInformation.update:148-164 已证 `inboxParcel`、`friendOffer`、`unreadMail` 为 periodicInquiry 根键。总集成核对现有通知，收件箱数量取 pending，过期好友数量须待清理规则确定；不让本模块伪造 unreadMail。
- 保留生产数据库 revision 冲突检查；集成需真实隔离 DB 提交故障与跨进程竞争验证。本批仅使用隔离内存状态重建服务来验证重登语义。
- 本组 22 项、完整回归 248 项通过，0 跳过。重点覆盖 500 条整批、30 路重复领取、混合成功/失败、满容量后重试、并发防重复、保存冲突回滚、提交成功但回包失败后重试、重登和重复 ID；见 test-results.txt。

命令：`python -m unittest tests.test_social_services -v`；`python -m unittest discover -s tests -v`。
