# 总集成与 D/E/F/G 事务契约

基线 8023c3fee8e525040d101fee8bf843b48b3256d3。公共文件没有被编辑。

## 公共补丁

`integration.patch` 只在 `app/business/registry.py` 已知路由派发前调用本组 `denial(api)`。
这保护 HTTP 之外的直调；HTTP 原链路已经调用 auth.check，因此本组 auth 修改会先于 handler 拒绝。
补丁不改变 402/71/331 的计数，不添加管理员开关，不改变普通 handler 的响应。
`tests/test_research331_i_integration.py` 在内存重建该单 hunk 并测试 32 项拒绝；
`git apply --check` 验证以固定基线可应用，总集成再实际应用和验收。

本轮没有 gameplay 注册白名单新增，没有 periodicInquiry 通知字段新增，没有配置开关新增。
不要直接把所有 SocialServices/InboxServices 注册到生产：其他 E 阻塞仍存在。

## 数据库与迁移

- 新库 `db/schema.sql` 增加 shared_records；旧库在独立维护连接运行
  `db/migrations/research331_i_shared_records.sql`。不自动在请求中执行 DDL，DDL 有隐式提交。
- players 不重写、不拆表、不重新初始化资源。缺少 revision 可读为 0；坏 revision 失败，不能猜成 0。
- shared_records 主键 `(namespace VARBINARY(64), record_key VARBINARY(128))` 大小写精确、无折叠；
  payload JSON 中 `_revision` 与 BIGINT revision 必须一致。NULL/revision=0 仅表示已保留键的空槽。
  首次读取不存在共享键会保留空槽；它不是已发布业务记录，调用者看到 None。
- 非空共享记录不允许删成 None；失效/售出/已消费都用持久 tombstone，保留操作身份，避免重复发放。
  namespace/keys/payload 为本服内部方案，绝非恢复出的原服字段。

## 调用、锁顺序、失败

```python
from app import state

# E 现有依赖协议直接兼容；此行仅构造组件，不注册生产路由。
social = SocialServices(gameplay, atomic_players=state.atomic_players)

# D/F/G 示例结构，key/数据由可信业务生产者选定，不来自玩家奖励参数。
with state.atomic(player_ids=(buyer_id, seller_id),
                  shared_keys=(listing_key, receipt_key),
                  expected_players={buyer_id: previously_read_revision}) as unit:
    buyer = unit.players[buyer_id]
    seller = unit.players[seller_id]
    listing = unit.records[listing_key]  # None means unavailable, not an empty valid listing.
    receipt = unit.records[receipt_key]
    # 在这里验证真实挂牌/所有权/资格/余额/容量/操作身份，然后一起修改 dict。
    # 已有收据先比较请求意图；相同则按业务重试政策返回，冲突则拒绝。
# 退出且提交成功后才组装成功回包。
```

所有键必须进入前声明，最多 256；玩家只能是已存在的规范小写 ASCII ID（现有会话生成 p_<hex>）。
不隐式创建缺失玩家，不允许变更键集合或 playerId/revision。旧非规范 ID 必须先审核迁移。
锁顺序：所有玩家排序→所有共享键排序。历史 D 文档“先挂牌锁后玩家锁”的写法须按这个顺序统一；
不能在同一个事务外先锁某个 listing/actor，再扩展锁集。E 已有按玩家排序的进程锁可保留。
若读取共享记录才能知道玩家集合，先只读探测，再开启完整键集事务并重新核对记录身份/版本。

业务层只改提供的 dict；不得调用 GameplayService._save、state.save/load、其他 atomic、外部 HTTP、
发通知或 DDL。嵌套 DB 连接会失败并回滚外层。通知/响应只在提交后发布，需要可靠通知时由业务层
在相同事务记录 outbox，再由独立消费者发送；本轮没有实现 outbox dispatcher。
新接口只更新变化的行，JSON 数值与布尔类型变化也算变更。

锁超时 1205/死锁 1213 在连接整体 rollback 后转换为 RetryableTransactionError（继承 StateConflictError）。
调用者必须丢弃所有临时对象、重新读档、重新检查资格，才可有界重试；库不自动执行用户函数。
连接断开/COMMIT 确认丢失保持原异常，结果可能已提交，必须先查持久收据。无稳定操作身份就拒绝
自动重试。已有单写 save 的数据库异常仍由原调用层处理；CAS 冲突统一是 StateConflictError。
所有组件必须返回新的资源快照或按原客户端增量语义去重，不能直接重放奖励增量。

## 分组适配边界

| 组 | 可使用的能力 | 本轮没有提供的东西 |
| --- | --- | --- |
| D | 买卖双方 + 共享挂牌/收据；国家购买 + 配额同提交 | 市场来源、税率、周期生产、无 nonce 请求幂等语义；旧 PlayerServices.call 中的独立 save 必须替换为同一 UoW |
| E | atomic_players 满足原 AtomicPlayers；已用真实 DB 验证关系闭环 | 过期清理/通知；管理员身份与包裹发行；旧包裹迁移 |
| F | 多账号 + 活动/结算共享记录同提交 | 战争开启授权、战况观察、胜负/奖励生产者 |
| G | 同事务更新 current/last 指针和不可变记录，可锁定一致读取 | 权威全玩家石高聚合；256 行上限不可当作全服快照扫描方案；跨两 HTTP 请求版本固定 |

## docs/api_schema.md 待合并字段溯源

- bundle：WebApiClient.cs:3470-3477 已有 admin 请求 playerIds/text/rewards；缺 token 不证明免认证。
- bundle：WebApiClient.cs:456-470 已有 debugLoginCog loginId/password 和 token 回调，不开放登录实现。
- bundle：GameRestarter.cs:79-99 消费根 errorReason；本组关闭响应沿用信封并含该根键。
- compatibility-policy：关闭文案、UNAUTHORIZED、32 项类别、锁顺序、record namespace/key、revision、
  256 记录上限、坏档拒绝和保留收据都属本服策略；没有新增原客户端奖励/资源/活动字段。
