# I：事务基础设施与 debug/admin 审核

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`，分支
`feature/research331-i-infrastructure-20261115`，研究日期 2026-11-15。
仅修改任务授权路径；未部署、未改 hosts/proxy80/config.ini，未访问生产数据库或启动 Unity。

## 结论与新证据

- 32 项全部核对原包装和可找到的调用者，分类为受控管理 1、测试辅助 21、保留关闭 10；
  **三类当前都关闭**，测试辅助也不提供 HTTP 开关。逐项见 [endpoints.tsv](endpoints.tsv)。
- 原 `WebApiClient.cs:3470-3477` 的 `forcePresents` 传 `playerIds/text/rewards`，没有 token；
  `debugLoginCog:456-470` 是取 token 前的包装。包装存在不代表管理员身份或登录安全得到证明。
  本轮删除 `debugLoginCog` 的 pre-auth 豁免，不实现赠送发行、不导入旧包裹。
- `GameRestarter.cs:79-99` 根据 `errorReason` 截断成功回调，因此关闭响应同时含该字段，
  不只返回 `succeeded=false`。错误文本是本服兼容政策，非原服错误码。
- [client-evidence.json](client-evidence.json) 记录原 DLL 指纹链、文件哈希、32 个包装及词法调用点。
  `audit_client.py` 首先校验 WebApiClient 原文件哈希。词法命中不冒充实际 UI 可达性。
- 旧 parallel-342 汇总明确保留这 32 项，没有旧 I 组业务报告可继承。E 的旧内存事务验收
  不能证明 MySQL 原子性；本轮新增真实 InnoDB 验证。数据库依据是 MySQL 官方文档，
  详见 [external-evidence.json](external-evidence.json)，不寻找 Wiki 为内部事务背书。

## 已实现的小闭环

`app/state/transactions.py` 提供 `atomic_players(ids)` 和 `atomic(player_ids=..., shared_keys=...)`：

1. 同一数据库连接，先按 ASCII 玩家 ID 顺序锁定已有玩家，再按 namespace/key 顺序锁定共享记录。
2. 复用 players 中 `_revision` CAS；只变更被修改的行，兼容旧 `state.save()` 的悲观锁内版本检查。
3. 一次提交多账号余额/关系和共享收据/配额/快照指针；唯一二进制主键处理不存在的共享键争抢。
4. 业务异常、序列化失败、SQL 中途失败、已知锁超时均整体回滚。禁止嵌套独立 DB 事务。
5. 真实 MySQL 下验证 E 的申请→双方记录→接受→新连接读档→解除；不改 E 模块，适配器直接满足其协议。

单写同时修复：已不存在的玩家不能用旧非零 revision 快照复活；损坏 revision 不再静默归零。
旧档缺少 `_revision` 仍按 0 兼容，非整数/负值需人工审核迁移，不自动覆盖坏档。

**提交确认丢失不能保证回滚。** 测试专门模拟真实 COMMIT 后抛连接错误，证明不会自动再执行。
有稳定业务身份的调用者在新事务读取持久收据判定结果；无原请求幂等身份的赠送/献纳/上架不能
随意用参数哈希或随机 request ID 实现去重。失败后丢弃事务块内的临时 dict，重新读档。

## 验证

- 官方 ZIP MySQL **8.4.13**，MD5 与官方下载页一致；独立 datadir，监听 `127.0.0.1:33361`。
  每轮创建新的 `oni_i_test_<uuid>`，结束只删除本轮创建的数据库；没有使用默认 `game_db`。
- [mysql-validation.json](mysql-validation.json)：**15 项真实数据库测试通过、0 跳过**。
  4 个 spawn 独立进程、48 次双账号/共享计数事务；48 次相同收据竞争只执行一次。
  覆盖 SQL 首次写入后失败、提交前失败、锁超时、提交确认丢失、旧单写竞争、重新读档和双方关系。
- HTTP 权限测试对 32 项逐一发 GET/POST，普通有效会话不能到达 handler；策略测试覆盖无会话、
  伪管理员会话和 strict/observe。另验证未应用的 registry 补丁能拒绝进程内直调。
- 全量回归结果和计数见 [validation.json](validation.json)。默认全量发现会明确跳过 15 项
  opt-in DB 测试；其真实数据库结果另列，绝不把跳过/内存测试当真实 DB 通过。

复现（新建独立的本机 MySQL 测试实例，非默认端口；可使用已准备的忽略目录 `.runtime`）：

```powershell
python -m pip install pymysql
# 如测试实例要求密码，只设置 ONI_I_TEST_USER / ONI_I_TEST_PASSWORD，勿使用生产凭据。
python docs/analysis/research-331/results/i-infrastructure/run_mysql_validation.py --port 33361
python -W ignore::ResourceWarning -m unittest discover -s tests -q
git apply --check docs/analysis/research-331/results/i-infrastructure/integration.patch
```

运行器覆盖 ONI_DB_* 为隔离库配置；拒绝非回环地址和 3306，使用 CREATE DATABASE（非 IF NOT EXISTS）
避免意外认领已有库。退出清理仅允许其内存记录中的 UUID 库名。二进制、数据和依赖均不入 Git。
测试支持 MySQL 8.x/InnoDB；本次只实测上述 8.4.13，不声称已验证生产版本或 MariaDB。

## 接入与剩余边界

见 [integration-notes.md](integration-notes.md) 与 [integration.patch](integration.patch)。
HTTP 已调用本组拥有的 `auth.check`，无需改共享 HTTP 文件；补丁仅给共享 Registry 增加同样拒绝，
不注册新 handler、不开放任何业务。D/F/G 可消费共享事务，但数据生产、规则和权限仍由各组落实。
E 仍需过期清理、通知、可信包裹发行及客户端增量恢复；本轮只移除其真实数据库适配器缺口。

`admin/inbox/present` 未实现发行。未来必须有独立可信管理员身份、发行授权和稳定发行 ID，
并在同一事务保存发行记录与包裹，E 才可消费；普通请求的 rewards 永远不是可信来源。
`debug/devLogin`、`debug/debugLogin` 不在本轮 32 项范围，维持现有本地启动兼容策略，
不能因此宣称整个旧登录系统已经完成安全审计。

本组资料/权限判定覆盖 **32/32**；可接入基础设施闭环 **1**（E 双账号事务适配，不等同完整好友玩法）；
正式注册减少 **0**，正常注册仍 **402 / 71 专用 / 331 占位**；Unity 验收 **0**。
这里的关闭属于 `no stub response`（无获准实现/授权），不属于 `stub has no assets`。
