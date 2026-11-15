# E → 总集成 / I / A

基线：`8023c3fee8e525040d101fee8bf843b48b3256d3`。先合 I 的共享数据库改动，再合 E 独占模块，最后审核应用 [integration.patch](integration.patch)。
补丁仅改 `app/main.py`、`app/business/periodic.py` 及共享集成测试的白名单/计数断言，没有在本工作树应用。用 `build_integration_patch.py` 从固定提交可重建；`git apply --check` 已通过。

## 注册和通知

- main 保持同一个 GameplayService，构造 `SocialServices(gameplay, atomic_players=state.atomic_players)` 注册 7 个 friend 入口；`SocialInboxServices(gameplay)` 注册 2 个 inbox 入口。
- periodic 的 `notification_provider=social.notifications` 保留原 `gmMessage/show_off`，新增已认证角色的 `friendOffer/inboxParcel` 绝对数量。没有实现 mailbox，因此不发送伪造的 unreadMail。
- 无 session 不查数据库；损坏社交状态时保留 baseline 字段并回 errorReason，不将错误假装成零条通知。通知函数会清理双边过期，不能套单 actor 锁或处于另一个 DB transaction。
- 9 项白名单详见 endpoints.tsv 中 `组件完成/待总集成补丁`；其他 E 路由继续未实现。共享权限层应按总集成政策拒绝未实现写入，不把占位假成功计入闭环。
- 正常 main 不调用 `stage_parcel`。I 的 `admin/inbox/present` 继续禁用；E 的受控管理入口是主机 CLI，不能把 params/source/operator 当可信权限。

## 给 I 的操作集合/锁契约

1. 发现集合：actor，显式 friendPlayerId，以及这两个种子当前的 friends/socialOffers 对端。只在事务外预读以发现 ID，不用预读快照作授权。
2. 所有 E 进程内锁按 ID 排序；I `atomic_players(tuple(sorted(ids)))` 再按同序读取现有 players FOR UPDATE；业务不调用单独的 save，不发送网络请求。
3. 事务内检查种子关联仍在锁集合；变大即抛内部异常回滚，退出后重新发现，最多 4 次；已无用的额外锁无害。双方关系/申请时间对称性和容量在锁内检查。
4. 改动集合包括双方 friends/socialOffers/socialRemovals、过期的第三方对端；任一读/写/序列化/提交异常都回滚。只发布成功提交后的 payload，重试无变化不推进 revision。
5. I 的 MAX_RECORDS=256 是当前支持范围；组合过大明确失败，不能擅自截断好友列表或拆成几次提交。高等级大规模关系图可后续改为更窄的可验证集合。
6. 发行由调用者在同一个 I 单/多玩家事务内执行 `SocialInboxServices.stage_parcel(...)`；其他玩法若有奖励事件/费用账本，必须与该调用共事务。函数不自行 commit，无 DB/网络副作用。
7. E 已用 I 适配器实跑 MySQL 6 项（见 mysql-validation.json）；没有复制 I 文件或修改 I 工作树。当前指纹为结果文件所记版本，I 后续若改契约必须重跑。

## 内部状态与迁移

- `friends={peer:{}}` 仅双方已接受；`socialOffers={peer:{status:send|receive,createdAt:seconds}}` 只待处理；两者重叠拒绝。
- `socialRemovals={peer:expired|rejected|cancelled|dissolved}` 是本服通知。没有删改其他旧字段。没有社交字段的新账号按空关系读；旧双边不一致/非法时间/损坏字段拒绝，需独立备份修复，不在读取中猜修复方向。
- `socialInbox` 保持 v1：`pending` 的值只有 `createdTime/rewards`，`resolved` 永久 ID→true；未知键/期限条件不静默忽略。
- 新 `socialInboxIssuances={version:1,grants:{issuanceId:{parcelId,source,createdTime,rewards}}}` 为私有来源凭据；source 精确 kind/authority/reference。发行ID在同一收件人内唯一，hash还绑定playerId。无来源的原 v1 账本不伪造收据；已有有效 v1 可以读取/领取，但不能通过新增发行 ID 冒认已消耗 ID。
- 没有原 inbox/mailbox 或旧 AI 包裹的自动迁移。不得裁剪 resolved/grants 后复用 ID；审计收据不是网络响应字段。
- 领取跨服务实例沿用 I state.save 的 revision CAS；发生冲突时不发布成功 rewards。首次回包丢失的显示修复依赖已有 common/getPlayerParams 或重登，不自行加一个未证实响应字段。

## 给 A 的关系边界

`pair_status(actor,target,left,right)` 要求传入同一事务的双方行，校验双边，返回空/send/receive/ok。
这只说明关系，**没有断言访城或助产权限**。原 PoliticFSMFriendMap 有非好友访问分支；是否允许目标地图、首次奖励、朋友树分类/剩余次数、地图所属者与产物时效由 A 的已证规则在共事务内判断。
不传 `can_visit=True`，不把 pending 认成好友，不接管 A 的 friend/building 或 friend/task。

## 可并入 docs/api_schema.md 的字段溯源

| 字段 | 来源 | 原消费者与实现边界 |
| --- | --- | --- |
| friend mutations: result(bool), detail.0(string) | bundle / compatibility-policy | FriendConfirmationWindow.cs:127-154,195-299；result决定恢复乐观计数；诊断文案非原服错误码。 |
| getFriends: 裸 playerId→name/country/level/baseId/grade/status | bundle | FriendData.cs:40-59；option 为 ""/ok/send/receive；不添加 isFirst 伪访问记录。 |
| getFriendProfile Unity 投影及 selfIntroduction.habits.0/1/2 | bundle / compatibility-policy | FriendData.cs:61-94；forHTML=true拒绝；缺历史统计的0/空串为已有兼容策略。 |
| updateFriendData: count.ok/send/receive, remove.<peer> | bundle / compatibility-policy | FriendWindowControll.cs:118-127、FriendConfirmationWindow.cs:168-187；remove只读键，原因和保留/确认策略为本服实现。 |
| periodicInquiry.friendOffer/inboxParcel | bundle | UserStatus.cs:148-164 强转数字后赋绝对计数；不发送未实现的 unreadMail。 |
| getParcels: parcels.<id>.createdTime/rewards,totalCount | bundle / compatibility-policy | InboxReader.cs:92-177；ID/时间来源为发行记录；降序时间+ID和包含end为兼容分页。 |
| resolveParcels: successful.<id>.rewards,failed | bundle / compatibility-policy | InboxResolveWorker.cs:11-105、PluginRunner_DoReceiveMail.cs:12-66；failed只读Count，值用诊断串；消费重试空rewards避免重复客户端增量。 |
| 四资源 item11_0000101/201/301/401 | bundle | RewardProcessor.cs:51-73；完整ID见 SocialInboxServices.RESOURCES；不扩展小判/卡牌/随机奖。 |

## 可复现

```powershell
python -m unittest tests.test_social_services tests.test_research331_e_lifecycle tests.test_research331_e_integration -v
python docs/analysis/research-331/results/e-social/verify_i_adapter.py --infrastructure-root D:/onisoul-worktrees/research-331-i-infrastructure
# 在装有项目 pymysql 依赖的 Python 下，指定已准备好的独立本地 MySQL 端口：
python docs/analysis/research-331/results/e-social/verify_i_adapter.py --infrastructure-root D:/onisoul-worktrees/research-331-i-infrastructure --mysql-port 33361
git apply --check docs/analysis/research-331/results/e-social/integration.patch
```

CLI 例（默认不写、不查真实收件人）：

```powershell
python docs/analysis/research-331/results/e-social/issue_parcel.py --player-id isolated-example --issuance-id example-001 --operator local-admin --reference acceptance-example --resource gold --amount 7
```

只有实际管理员准备好明确目标、来源和数据库环境后才加 `--apply`；本任务只执行上面的预览，真实测试中的发行使用隔离数据库。
