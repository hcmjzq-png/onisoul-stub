# E：好友、信箱、收件箱与社区

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`；工作树 `D:\onisoul-worktrees\parallel-342-e-social`；分支 `parallel/342-e-social-20261115`。
任务引用 A 文件但明确指定 E，故采用同目录 E-social.txt 的 41 个入口与允许文件范围。

交付 **7 个限定范围、未生产挂载的处理器**：好友发送/接受或拒绝/取消/解除、列表、计数、Unity 公开资料。不是完整社交系统；没有减少全局占位数量。
`reviewed-endpoints.tsv` 逐项覆盖 41 个入口；`evidence.json` 保存原 C# / 原表路径、SHA-256、方法或行号，并分开列出兼容决策。

## 原版证据与实现范围

- WebApiClient.cs:2604-2655：好友参数 `friendPlayerId`、`reply`、`option`。FriendConfirmationWindow.cs:127-154,195-299 消费 `result` 和 `detail.0`，明确传 `ok` / `excuse`。失败保留 `result=false` 供接受/拒绝回调恢复提前扣除的计数；detail 诊断文字除两个容量短语外为本模拟服选择。
- FriendListWindow.cs:38-116 → FriendData.cs:40-94 → HashAccessor.cs:34,70,79,97：列表裸 playerId 映射、数值字段、公开资料嵌套介绍与三个习惯槽。`isFirst` 可省略；未证访城首次记录，不伪造该值。forHTML=true 经 HTMLUtil 做国家/官阶本地化，尚未完整验证，拒绝该模式。
- FriendSpecWindow.cs:102-174 / PlayerLevelTableAccessor.getMaxFriend：双方已接受好友容量读 `playerLevel.<level>.friend`，原表 Lv1=50，Lv2=51。DefinesTableAccessor.cs:175-190：申请上限读 `friendoffer_send_max` / `friendoffer_receive_max`，原表均 10。小样本保留原行，非完整表。
- `friendoffer_expire_time=604800` 只有表值，清理触发时点/删除原因尚未证明；代码只用于拒绝过期记录，不冒充过期清理。任何相关玩家存在过期申请时，本批受影响请求明确失败，生产接入前必须解决。
- `friends` 仅保存已接受 ID，`socialOffers` 保存待处理 ID/status/createdAt；**本服务内部状态设计**。不生成奖励、不扣资源是本批兼容策略，非原服费用复原。无持久化去重请求 ID：即时重复发送/接受/取消/解除不重复修改；重复拒绝返回失败；跨取消后重新申请等周期的延迟重放仍无法区分。
- 接受时双方容量在同一事务内重新检查；发送方才能取消，接收方才能确认/拒绝；错方向、未知角色、本人、非法 reply 和不一致双边记录全部拒绝。

## 访城与 A 的边界

PoliticUserInfo.cs 两个好友构造方法仅以 `status==ok` 设置 IsFriend；PoliticFSMFriendMap.cs:62-78 明确有好友与非好友两条脚本；Politic.cs:312-352 先 Data2 后 visit。因此不能把所有访城都限制为已接受好友。
PoliticBuilding.cs:209 的 IsFriendBuilding 是建筑分类，不能误认为账号关系；其生产菜单另见 :600-608,:1652，好友助产仍归 A。
本组不提供笼统 can_visit/can_assist=True，不实现访城发奖，不把 getFriends 中出现的 send/receive 当作已接受好友。

## 信箱与社区静态边界

HTMLMailCore.cs:30-149 已追 Unity→原 HTML 桥接：邮件请求只有 to/subject/body，未发现附件参数。邮箱和 inbox 是不同路径，不能将旧密书箱直接作为附件收件箱实现。
InboxReader.cs:92-177 消费 parcels/totalCount，InboxResolveWorker.cs:11-105 消费 successful.<id>.rewards 与 failed；makeDummy 仅客户端调试函数，**不是原服奖励证据**。奖励原子消费需 C 的库存/容量规则，尚未实现领取。
HTMLBbsMediator.cs:318-667 展示 sess_key、commit、原始文本转义和 HTML 转发。guid 为客户端追加；listThread/listComment 的 list 与 infoThread.thread/infoComment.comment 是嵌套响应，不能按接口名推平。关闭/删除/提交权限以及原 pcweb 最终字段消费尚缺证据。
在原客户端安装目录的文件名搜索未发现可直接核验的 pcweb/bbs/mail/inbox 源文件；未扫描解码全部缓存，不宣称这些资源不存在。`D:\onisoul\work\pcweb` 的来源链未核实，本批不用其内容替代原版证据。

`stub has no assets` 只用于 TableCatalog 的表加载失败；已有表缺行、无头像记录、过期业务未实现用 `no stub response`。没有声称补齐此前 10 项资源或两张表。

## 验证

在本工作树执行：

```powershell
python -m unittest tests.test_social_services -v
python -m unittest discover -s tests -v
```

本组 11 项；完整回归 237 项通过，0 跳过。详见 test-results.txt。包括双边生命周期、容量、无费用副作用、越权、即时重试、20 路重复操作、反向申请不死锁、竞争接受不超容量、提交故障回滚和服务重建后读取。
持久化验证使用同一个隔离内存存储重建服务，不是 MySQL 崩溃恢复或真实 Unity 验收。
原子适配器只在测试中提供；生产存储适配/迁移、鉴权边界、过期机制与动态验证是明确集成前置条件。未部署、未操作真实账号、未修改 hosts/proxy80/config.ini 或共享客户端。
