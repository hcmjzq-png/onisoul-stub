# H：签到、日常任务、收藏与账号活动

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`（#50）；分支 `feature/research331-h-account-20261115`。
工作树 `D:/onisoul-worktrees/research-331-h-account`。仅修改本组授权路径，未应用公共补丁、部署、改生产存档或操作 Unity。

## 本轮结果

| 项目 | 数量与含义 |
| --- | --- |
| 归属复核 | 29 个，完整清单见 [endpoints.tsv](endpoints.tsv)；复用旧协议证据，不冒称全部新发现 |
| 资料补齐 | 6 个：签到 2 项的实际触发/重试消费者；每日任务 4 项的台服上线时间与奖励目录变化证据 |
| 可测试候选闭环 | 1 个，签到查询→正常 stamp 请求→资产与收据同存→重登回读；20 项新增测试 |
| 可立即开放的原版闭环 | 0；台服日界线、断签、完整奖励排期仍不足，默认没有启用计划 |
| 正式注册减少 | 0；正常注册器仍为 402 总数 / 71 专用 / 331 占位 |
| Unity 验收 | 0；串行验收计划见 [capture-plan.md](capture-plan.md) |

## 新证据与排除的猜测

1. [2014-01-28 台服厂商资料](https://gnn.gamer.com.tw/detail.php?sn=92387)正文可读：每日任务由完成指定任务取得活跃点数，兑换内容不定期更新。原 `daily_mission` 的 85 行仅 `id/missionName`，`DailyMissionScene.cs:136-192` 从网络读取门槛、进度、积分与奖品。不能把任务名、春节赠礼或商城 `getPoint` 当成永久任务目录。
2. [2012-11-15 日服 CAPCOM 发布稿](https://www.4gamer.net/games/150/G015000/20121115062/)正文可读，提到每日登录和 11 月 16 日零时开始的十四日奖励。只证明该日服活动；不能证明 2014 国际中文版是 UTC 零点、当地零点或断签归零。搜索到的 PS3 奖杯说明、论坛“十四日更新”未作为业务常量。
3. `Politic.cs:116-124` 用 `UserStatus.IsNeedLoginStamp` 设置登录 FSM；`UserStatus.cs:777-788` 比较服务器时钟与 `nextStampDate`；`PoliticFSMLogin.cs:48-69` 才发送无日期/无奖励参数的 `stampLoginSheet`。基线 `gameplay.py:675` 每次返回明天，无法触发已到期的签到。本轮提供**未应用**的 [integration.patch](integration.patch)，仅在显式注入排期时用持久账本计算日期。
4. `LoginBounusMenu.cs:175-180` / `UserStatus.cs:1799-1818` 将 `stampCount` 对应的奖品加到本地资源。重复成功响应会重复加显示值。`GameRestarter.cs:60-92` 与 `WebApiClient.cs:324-337` 会拦截含 `errorReason` 的回包，因此同日重试明确失败、不重放成功包。首次响应丢失后应重登/重读权威资源；这是本服策略，会经过原客户端错误恢复界面，尚未完成 Unity 体验验收。
5. 收藏显示并非库存直传：`mypageCollectionSeriesParam.cs:48-89` 将剩余物品数加上 `payableCount` 折算量。原表存在不代表旧收藏实现正确。家宝、宝玉领奖、武将历史收藏本轮均未启用。迁国原表 `migrate_0001` 有 interval=2592000、credit=480、upperRankAllowable=0，不能据此推导费用优先级、首次资格或资产保留清单。

来源访问状态、时期、服别、可信度、实现位置均见 [external-evidence.json](external-evidence.json)。S4/S5 返回 403，官方旧站超时；没有将搜索摘要当全文。原容器校验与 13 个源文件散列见 [source-proof.json](source-proof.json)；8 条原表小样本位于 `tests/fixtures/research331/h-account/`。

时区补证：`SceneResources.cs:114-117` 用 getServerTime.now 设置 ClockTimer；`ClockTimer.cs:23-48` 的 Date 为 Unix epoch 加秒，Hour/Day/Month 才加八小时。`UserStatus.IsNeedLoginStamp` 比较的是 Date。这支持 UTC 时间字符串投影，**显示加八小时仍不能证明签到在当地零时重置**。

## 代码范围

- `app/business/account_progress_daily.py:59`：不可变排期输入，要求版本指纹、来源引用、明确起止时间、UTC 日界偏移和断签策略。没有内置日期或免费奖励目录；来源引用仅用于审阅追溯，不会自动证明排期真实性。
- `app/business/account_progress_daily.py:189`：只读签到时间投影；查询不补资源、不补签、不写入历史。
- `app/business/account_progress_daily.py:218`：仅四资源及已启用宝玉；检查容量，奖励与内部 `accountProgress.loginStampV1` 同次 CAS 保存。同日最多一笔、整张领完不循环，缺表/坏引用分别报错。
- `app/business/account_progress_daily.py:251`：只接受认证会话和原 token 参数；不能由客户端选时间、奖励、进度、目标账号或排期。
- `tests/test_research331_h_login_stamp.py:300` 起：在内存应用基线补丁，验证 `getPlayerParams` 到期→原签到请求→重登→次日；共享 `gameplay.py` 未改。

`preserve/reset` 是**显式配置的本服兼容策略**，不是两种已恢复的原服规则。测试使用 2026 年合成排期、100 金钱等样例数值，仅检验事务与协议；不在生产模块、配置或补丁中提供启用值。没有恢复每日任务真实进度生产者，所以不注册每日任务四接口。

## 验证

```powershell
python docs/analysis/research-331/results/h-account/verify_sources.py
python -m unittest tests.test_research331_h_login_stamp tests.test_account_progress_services -q
python -W ignore::ResourceWarning -m unittest discover -s tests -q
git apply --check docs/analysis/research-331/results/h-account/integration.patch
git diff --check
```

本轮完整 **437 项通过，0 跳过**；其中 H 共 51 项，保留 #50 三个正常挂载首档 trophy 路由及其回归。测试覆盖同日/跨日/断签、完成封顶、版本冲突、坏账本、越权、容量、缺表/坏引用、保存失败、并发、独立实例 CAS、重登与增量消费。CAS 为隔离内存实现，未验收真实 MySQL 多进程或掉电耐久性。

剩余项按 [integration-notes.md](integration-notes.md) 交总集成：排期发行与旧档迁移、原客户端错误恢复和日期解释、I 组数据库事务适配；未支持库存溢出转信箱、角色/装备/付费货币签到奖励、自动换期、跨日迟到重试区分、兑换码发行及付费挂机权益。首档 trophy 没有计入本轮 331 的减少，九宫格 `claimReward` 保持 C 组归属。
