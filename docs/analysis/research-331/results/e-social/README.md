# E：好友、访问、邮件、收件箱与社区（331 第二阶段）

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`；分支 `feature/research331-e-social-20261115`。
仅修改 E 授权文件。41 个入口全部见 [endpoints.tsv](endpoints.tsv)。

本轮完成 **2 个可接入的限定闭环，涉及已有 9 个候选入口**：好友生命周期，以及受控管理员发行的四资源收件箱。
另交 `periodicInquiry` 通知接入补丁。公共文件没有直接修改，正常注册仍为 **71 专用 / 331 占位**；不是已上线。

## 新证据及排除的猜测

1. [2014-07-20 国服试玩](https://news.17173.com/content/2014-07-20/20140720144944141_all.shtml) 的好友段明确描述申请后等待对方确认，与原 `FriendConfirmationWindow.cs:195-258` 一致。这是大陆 PC 服作者实测，安装包原缓存亦指向 86joy；不能将该资料误标台服或将日服/台服时期规则整体移植。
2. 原 `FriendConfirmationWindow.cs:168-187` 的 `remove` 只判断目标键存在；`UserStatus.cs:148-164` 对 `friendOffer/inboxParcel` 直接赋值。已实现绝对计数，不发增量 badge；删除原因文字和通知保留仍标本服策略。
3. 重新读原 `defines` 和 `playerLevel`，逐字段核对已有小样本：发送/接收上限各 10、期限表值 604800、Lv1/Lv2 好友容量 50/51。只有数值为原表证据；秒制截止边界、请求时惰性清理不是原服务器实测。
4. 重新校验原安装包提取的 `app.js` 散列并扫描 **159 条原缓存**。确认 BBS、mail、mailbox、reward 的父页面路径及桥接；四个 iframe 正文未出现在这份缓存中。`HTMLMailCore.cs:30-149` 邮件参数没有奖励附件，`InboxReader` 的奖励包裹是另一条链路。没有用旧 AI 网页填补缺口。

逐条外站访问状态/时期/服别/采用条件见 [external-evidence.json](external-evidence.json)，本地散列与行号见 [source-proof.json](source-proof.json)。
S4、台湾朋友树新闻及旧官方手册未取得可读正文；搜索命中没有算全文验证。日本 Wiki 只用于定位手册，未引入数值。

## 已实现的闭环

### 好友

`sendFriendOffer → receive/send 列表 → feedback(ok/excuse) → 双边 friends → 取消/解除/过期 → remove/count → periodicInquiry`。

- E 业务层显式接收 **I 的 `state.atomic_players`**，真实 MySQL 适配已执行；不再把测试 `AtomicMemory` 当生产前提。
- 预读仅发现锁集合；正式事务内重读并校验，若新增关联超出已锁集合则整笔回滚、重新发现，最多 4 次。所有进程内锁按 ID 排序，之后进入 I 同一数据库事务；禁止外层单 actor `_guard`。
- 任一方相关过期申请与其对端在同一事务删除；随后发新申请不被已过期容量卡住。接受恰好过期的目标返回 `result=false`，同时提交双边清理。坏时间戳、错配双方、重叠关系都拒绝，不自动修坏档。
- 取消、拒绝、解除、过期写双方 `socialRemovals`；`updateFriendData` 重试/服务重建不吞通知。成功取得新列表清掉过时通知，成功读新 profile 只清该目标；新申请清双方旧通知。这是本服的 UI 刷新确认策略，多个窗口/会话之间不保证原服相同的通知时序，写操作仍重验真实关系。
- 请求没有周期 ID，无法辨认“取消后新申请”周期中的旧确认重放；只保证同一关系周期内即时重试和并发不会单边写入，不声称严格跨周期去重。
- 向 A 提供 `pair_status(actor,target,left,right)`：只能在 A 同一事务读取；`ok` 才是双方接受。原 `PoliticFSMFriendMap.cs:62-78` 有非好友分支，因此该结果**不是 can_visit/can_assist 授权**；访问地图和助产结算仍待 A/总集成补足。

### 收件箱

受控主机管理员 `issue_parcel.py --apply → stage_parcel → socialInbox + socialInboxIssuances → getParcels → resolveParcels → resources/resolved → periodicInquiry.inboxParcel`。

- CLI 默认仅预览；`--apply` 要求 I 真实事务和现存已创建角色。执行权限来自主机管理权限，`operator` 是审计文字，不是从客户端相信的管理员凭证。**没有开放 `admin/inbox/present` 或任何新 HTTP 发奖入口**。
- 发行动作 ID 与收件人共同生成稳定包裹 ID；来源、奖励和首次创建时间永久保存在发行收据。重试验证内容一致，领取后不复活包裹；同 ID 改来源/奖励明确失败。
- 当前仅支持原 `RewardProcessor` 已核实的 gold/wood/food/iron，数量由可信发行方确定。普通领取参数只认本账号包裹 ID，客户端不能指定奖励。
- 发奖、pending 删除、resolved 墓碑同一玩家 CAS 保存；满容量整包保留待领，其他合法包裹可成功。消费重试回空 rewards，避免客户端重复加显示余额；丢失首次响应仍须读取权威资源快照或重登。
- 此发行子集**明确无自动过期**，不等同原服包裹无期限。含未知期限/条件的旧 parcel schema 继续拒绝；不迁入争议旧 inbox/mailbox 数据，不重放旧活动。

## 验证和交付边界

- 组件/边界：原 22 项社交测试及新增 10 项闭环测试；共享补丁另 4 项测试。
- I 真实 MySQL **8.4.13，6 项通过、0 跳过**：双边保存/重建回读、无变更重试不增加 revision、第二次 UPDATE 故障、提交前故障、两个服务实例竞争接受、旧单玩家快照 CAS、包裹领取提交回滚、12 路并发领取及重登 badge。
- 使用 I 专用本地测试实例 `127.0.0.1:33361`，E 自己新建随机 `oni_e_test_<uuid>` 数据库，结束后删除；没有访问 I 的玩家测试库或生产数据库。结果与适配器指纹见 [mysql-validation.json](mysql-validation.json)。此 E 测试是两个服务实例/多个连接竞争，未声称 E 自己做过多进程测试；I 的多进程结果归 I 报告。
- SQLite 可重复契约测试保留为无 MySQL 时的补充，明确不替代 InnoDB 行锁验收。
- 全量回归、补丁检查及精确测试数见 [test-results.txt](test-results.txt)。未部署、未操作 Unity、hosts、proxy80、config.ini 或已有玩家。

资料补齐计数按上述 **4 条新增证据结论**计，不将 41 条包装器复抄当新增完整规则；可接入闭环 **2**；正式注册减少 **0**；Unity 验收 **0**。
合入 I 并应用本补丁后候选注册数为 80/322，仍不等于完整 80 项玩法或真机验收。

邮件 4 项、社区 17 项、搜索/自动申请、访城地图与奖励、邀请码等剩余 32 项没有本轮可运行实现。它们目前仍由基线占位承接，**占位不等同已关闭或真实成功**。
原页面/场景资源失败记 `stub has no assets`；规则/权限/状态未实现或坏引用记 `no stub response`。

总集成步骤、字段溯源、迁移与权限边界见 [integration-notes.md](integration-notes.md)；串行真机验收见 [capture-plan.md](capture-plan.md)。
