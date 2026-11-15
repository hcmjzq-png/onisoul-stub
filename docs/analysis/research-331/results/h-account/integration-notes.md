# H 接入说明（公共文件未改）

## 交付补丁

`integration.patch` 针对固定基线 `8023c3f` 的 `app/business/gameplay.py`，新增可选 `login_stamp_plan` / `login_stamp_clock` 构造参数、两个条件注册入口，以及 `getPlayerParams` 的日期投影。测试将补丁应用到内存中的基线源码，未覆盖任何公共工作文件。

白名单精确为 `common/getLoginStampSheet`、`common/stampLoginSheet`。无 plan 时不注册，保持正常 402/71/331；不要求修改 `response_shapes.py`（两个接口是命名根字段），不改首档成就白名单。不能把测试 `synthetic_plan()` 导入生产，也不能因有 `evidence_ref` 就认定运营排期已验证。当前没有台服完整排期可注入，**补丁只是待审核接线，不是上线授权或完整原版恢复**。

`getPlayerParams.loginStamp.nextStampDate` 是实际触发源；现有同名根字段一起保持一致。没有发现签到要求新增 periodicInquiry 通知字段，本补丁不添加虚构周期字段。跨日后原 FSM 何时重进仍须按 capture-plan 串行验证；不能仅凭服务器算出日期宣称在线跨日 UI 已通过。

生产 clock 必须与 `common/getServerTime.now` 同为服务器 Unix 时间；测试注入的虚拟时钟仅用于隔离单测，不改全局游戏时钟。原 `SceneResources.cs:114-117` 设置 ClockTimer，`ClockTimer.cs:23-48` 的 Date 不加时区而显示属性另加八小时，故本组件输出 UTC 字面时间，不把服务器本地时区写进 +0000。

## 字段溯源（供合并 docs/api_schema.md）

| 字段 | 来源 | 实现 / 限制 |
| --- | --- | --- |
| 请求 token | bundle：WebApiClient.cs:671-684 | 原请求无日期、奖励、campaign、nonce；新增控制参数一律拒绝 |
| startDate/endDate | bundle：LoginBounusMenu.cs:270-288 | 字符串 `yyyy-MM-ddTH:mm:ss+0000`；endDate 为排他上界，原 UI 减一秒显示 |
| stampCount/loginSheet.dayN.itemId/amount/anniversary | bundle：LoginBounusMenu.cs:210-216,290-332；UserStatus.cs:1799-1818 | count 数字；每格单奖品；gold/silver 为本服限定外观输入；不能虚构奖励目录 |
| nextStampDate | bundle：UserStatus.cs:777-788,1791-1797；Politic.cs:116-124 | 未领时为本日有效窗口开始，已领为下一窗口/排期结束；日期投影算法为 compatibility-policy |
| item11_0000101/201/301/401 → gold/wood/food/iron | bundle：RewardProcessor.cs:25-70,239-245；item11 四条原行 | 原客户端按增量加资源，非设置成目标余额；代码用完整 ID，禁用付费货币映射 |
| item08_* | bundle：RewardProcessor 的 jewel 分支；原 item08 表 | 仅 enable=true 且 category=jewel；原表缺文件为 stub has no assets，坏 ID/类别为 no stub response |
| 重试 errorReason | bundle：GameRestarter.cs:60-92；WebApiClient.cs:324-337；compatibility-policy | 拦截重复增量，首次成功丢失则重登读取；不声称恢复了原服重复领取回包 |
| accountProgress.loginStampV1 | compatibility-policy；不在网络协议暴露 | 每 campaign 的配置 SHA-256、起止时间和有序 at/day/ordinal 收据，与资产同存 |

## 状态生产、迁移与事务

资格来自真实认证、已创建角色和服务器时间；`PoliticFSMLogin` 的正常 stamp 请求即登记事件，不用插件诊断日志或客户端计数生产资格。浏览只投影。无排期、过期、未知奖励时拒绝，不生成空成功或自动新周期。

本服未曾发放该类签到，缺失 `loginStampV1` 才可视为空；原服历史存档、旧实验服曾发过签到的档案必须显式迁移真实收据。已存在错型、空 campaign 记录、非递增日、未来收据、同 ID 改排期/奖励、重叠新 ID 均拒绝。历史 receipt 保留，不通过删除旧 campaign 实现换期。只允许互不重叠的新计划；没有公开管理路由。

I 组适配需求：

1. 操作集合是一个玩家资源或 items 数量增量，以及同玩家 `accountProgress.loginStampV1` 整体更新；两者不能拆成两次提交。
2. 锁顺序：现有 `_guard` 玩家锁→读取带 revision 的存档→复制校验/组装→同一 CAS 保存。没有跨账号锁。DB save 必须全有或全无；异常不得已经提交一半。
3. 跨进程用 revision 条件更新；冲突回失败，不盲重放成功 delta。重试重新读取服务端时间和 receipt，同日不能再发；掉电/提交后断线需要权威重读。
4. 未扩展公共 state/DB 接口；现有真实 DB 的多进程与耐久性留给 I 验收。测试只有隔离内存 CAS，不把进程内锁当数据库保证。

明确兼容选择：固定 UTC 偏移而非主机时区，时间秒数向下取整；排期 [start,end)，最多 366 天 / 14 格；不补漏日，完成不循环；容量不足整笔拒绝。原台服日界线及断签保留/归零仍 unsupported，必须明确审核后注入。

原请求无日期或 nonce，跨日迟到重试与当天新签到无法在 wire 层区分。本组件保证每服务端日最多一次，**不提供跨日请求身份去重**。同一 campaign 使用期间所有进程须配置一致；换版停写并迁移，不能滚动部署两个不同账本策略后由失败回包猜迁移。

原 `getRevisions` 仍需真实部署版本清单；`plugin/setPluginData` 仍缺可信权益生产者。收藏、迁国、日志与兑换码按 endpoints.tsv 保留关闭。无部署、hosts、proxy80 或 config.ini 变更。
