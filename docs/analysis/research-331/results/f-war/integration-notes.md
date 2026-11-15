# 汇总组／I／B／G 接入交接

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`。本提交不改公共文件，不挂默认注册器。
`integration.patch` 只是可审查接线和 docs/api_schema 来源追加；不能当作完整上线补丁。
补丁在 Git 中为 LF；Windows 若经 core.autocrlf 转成 CRLF，针对原始 LF blob 应先转换补丁换行为 LF。
集成测试在临时目录做此规范化、取固定基线原文并真实 git apply，公共工作树文件不被写入。

## 精确白名单与不可替代的条件

候选白名单仅 `turfWar/entryWar`、`turfWar/entryBattlefield`。
共享 `turf_war.py` 的候选 `register_enrollment_components` 要显式传 event_id、atomic；
原 `register` 不调用它，正常 `build_registry()` 仍为 402/71/331。
该函数不开放 `getSelfRecord/getSelfSituation/moveBattlefield/receiveTurfWarReward/getTurfWarResultLog`。
不挂老 `strategy/isAlive`、siege pairings、strategy history，不修改 B 战斗路由。

汇总组只有在以下依赖具备后才调用候选接线：

1. I 提供下述真实原子存储；明确审核本服新事件的时间、国家分组、当前三槽引用。
2. 事件共同持久化，`common/getEventStatuses` 和 `getWarSituation` 从同一已声明事件读取，
   提供原 UI 必需的真实 global/battlefields/battleRules/bonus/time 等数据。
3. 完成原客户端第一次进场、失败恢复、重登的串行验证；不能把 `turf_enrollment` 的片段
   `update` 到旧 `turf_war.body()` 零分模板上伪装成真实战况。

现在不满足第 1—3 条，所以**可独立集成审查的组件 2 个；可直接向普通客户端开放 0 个**。
独立测试必须直接构造隔离注册器与隔离活动；不要在 common/getEventStatuses 填测试 True/open。

## I：持久化与事务要求

业务层不拼 SQL，不在 player 表里塞伪玩家当活动。活动记录需要 I 自己的命名空间或活动表。

- `declare_turf_war` 返回的文档必须在内部运营动作中以 eventId 唯一 insert-if-absent 落库；
  不提供 HTTP 创建/导入接口，不用初次查询补活动，不覆盖关闭的同 ID。authorizationRef 是审计引用，
  不是鉴权凭据或签名；调用者仍须是已授权的服务端运营/测试流程。本轮未声明生产事件。
- `AtomicWarEnrollment(event_id, player_id)` 产出独立 `{'event': ..., 'player': ...}` 草稿。
  汇总审核修正：服从 I 的统一锁序，所有玩家 ID 排序 → 所有共享活动键排序；两者必须在同一 I 事务内。
  进入前声明完整玩家/共享键集合，不能先锁活动再调用另一个玩家事务。原稿的相反锁序不适用。
  不先调用 GameplayService._guard 的玩家锁。转国流程也必须尊重同一锁序／版本检查。
- 事务内读玩家 created/playerId/country、事件定义及 journal；事件追加和版本递增一次提交。
  本轮不改玩家资源或账本；若任一对象版本变化则 `StateConflictError`，不得静默吞掉冲突。
  异常回滚；只有 context 正常退出并提交后才发成功包。禁止先写报名、后写选择或另外两次 _save。
- 同请求再次报名/同场选场没有日志追加、没有存档兼容补全、没有资源增量。
  并发不同场只有一个首次选择成功。提交后丢回包重试可以返回同绝对 team/空确认，
  `TurfWarBriefCache.cs:387` 赋值和 `TurfWarWorldMap.cs:319-328` 清缓存不会重复扣费。
- 时间在持锁后的业务调用中读取。有效区间 `[opensAt, closesAt)`，拒绝 NaN/bool/回退。
  内部 close 同锁执行，过期查询仅计算阶段，不追加日志。关期后任何报名重试都失败，不复活记录。
- 固定 event_id 绑定一套服务对象，不自动随日期切换。原协议没有 eventId/nonce；本实现未解决
  跨期迟到请求归属，生产自动轮换前需额外设计会话事件绑定与原客户端刷新策略。
- 重启回读完整 journal，拒绝坏序号、越界时间、重复报名/选场、关闭后追加、定义 checksum 不匹配。
  不自动修档，不把旧 `_warCampaigns.queries` 或 `_warCampaigns.strategy` 迁移成新报名。
- 大规模活动需要分表/索引和有版本的快照压缩。本轮整段回放是受限登记组件，未验收容量或性能。

测试 `DurableTestStore` 使用临时单文档原子替换和进程内锁，覆盖真实文件重开、并发服务对象、
故障前无提交、冲突与重试；不是 MySQL 实现，也不证明跨进程/断电耐久。I 应让同一测试场景运行
其隔离 DB 适配器，增加进程终止、网络故障、唯一键冲突和转国并发用例。

## 共享查询、通知、奖励与旧档

`turf_enrollment(event, authenticated_player_id, now)` 仅返回以下原消费者已证片段：

```json
{"selfBelong":{"team":"east|west|none","battlefield":"catalogue ID|none"},"isMovable":false}
```

此 JSON 是格式说明而非可发送的字面值；只有真实已声明空 journal 的玩家才有 none。
完整 getWarSituation 还需要真战况。没有证据把片段映射到 getSelfSituation/getSelfRecord。
`team/battlefield` 根重复键不是新需求，暂不从片段扩张协议。

本轮不增加 periodicInquiry 通知字段；没有战绩和领奖通知可发。不能让内部 closed 标记点亮结果按钮。
B 应先交付以 eventId/playerId/field/canonical battle id 绑定的可信战斗事务；G 再从相同提交建立榜单。
必须在其事务范围内解决双方得分、全局/分场聚合及奖励 ledger 后，才开放结果/领奖接口。
不把报名日志当战斗日志，也不从参与人数导出国家分数、胜者、排名或红魂。

资源与规则错误保持分开：表本身缺失/加载失败用 `stub has no assets`；活动缺失、未知规则、
表中坏引用用 `no stub response`。本轮原表可读，不代表五个结果 iframe 或战斗 AssetBundle 已修复。
