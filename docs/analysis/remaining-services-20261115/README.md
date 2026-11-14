# 357 个剩余接口：证据索引与成长流程复核

基线为 PR #36 合并后的 `9f16ee3`：402 个注册入口中，45 个有专用处理器，357 个仍走占位分发。
本批为全部 357 个建立原客户端入口索引，深入复核其中 11 个；新增 6 个专用处理器后，剩余占位入口为 **351**。
专用处理器计数表示分发覆盖，不表示完整玩法还原。尤其教程奖励与升级只实现下述已核实范围。

## 证据与索引范围

- 原安装包 `OniSoul_Setup_20140712.exe`，SHA-256：`ad34a14e3dd67b30c59d5abd9ed2a82b2ab53161e24f3be654a63175e6d890ad`。
- 重新解出的原版 Assembly-CSharp.dll，SHA-256：`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`。
- 原表包来源与提取方法沿用 [上一批证据](../quest-contract-20261115/source-proof.json)。没有采用旧 AI 修改的脚本或界面作为原版证据。
- [all-357-evidence.tsv](all-357-evidence.tsv)：每个入口的封装方法、源码行、IL 直接调用点、请求候选字段、旧响应候选字段、调用文件中的表访问器线索。
- [reviewed-endpoints.tsv](reviewed-endpoints.tsv)：11 个深入复核入口的证据、实现范围和阻塞条件；[lesson-support.tsv](lesson-support.tsv) 逐项列出 24 个教程奖励的支持状态。
- [index-summary.json](index-summary.json) 与 [review-source-proof.json](review-source-proof.json) 记录原始反编译文件散列。

357 个入口全部找到 WebApiClient 封装；52 个没有直接 IL 引用，184 个在旧 IL 汇总中没有带类型的响应字段，12 个封装存在请求分支。
**没有直接引用不等于无用，没有响应字段不等于可以返回空表。** 回调、HTML 桥接及运行路径还需逐个追踪。
索引中的表名是整个调用文件的线索，不能直接当作该接口的已证实依赖；旧响应字段仍可能有层级错误。
184 是旧 IL 汇总的历史统计，不随本批修正的契约字段自动变化。

## 已落实的服务端行为

实现位于 `app/business/progression.py`，注册与读取时的容量修正在 `app/business/gameplay.py`。

| 入口 | 本批行为 | 尚未复原部分 |
| --- | --- | --- |
| `politic/mypage/takeLesson` | 按 lesson.triggerMissions 检查任务为 C；按 reward14_lesson 发确定数量的资源/经验；一次领取，重复或并发不重复发放 | 武将/战术交付、资源溢出进收件箱、随机奖励；24 项中 19 项支持，5 项明确失败且不改档 |
| `common/solvePlayerLevelCap` | 按 requirementForNext 的首个未关闭任务和 defines.level_limit 计算 cap | 不代替任务完成，不开放超过原客户端全局限制的等级 |
| `common/increasePlayerLevel` | 由累计经验计算可达等级，受 cap 限制，重算持有容量；重复调用幂等 | 升级赠品、点数补充、战斗/活动触发规则未证实；本批保留已有点数，不声称此部分已还原 |
| `common/getPlayerEntity` | 返回当前认证玩家的 playerId，满足已找到的 debugCreateQuestEncount 消费者 | 未找到的额外字段不扩写 |
| `common/getServerTime` | 返回现有信封的 now 时间戳 | 不改变原有认证策略 |
| `auth/keepAliveContainer` | 返回确认信封；HTTP 会话解析层已刷新有效 token 的存活时间 | 不生成旧错误契约中的 guestLogin 字段 |

### 教程与等级证据

`LessonMissionSimpleStatus.cs:81-100` 要求前置任务状态 closed，finished 不够；
`LessonScriptCommand.cs:139-187` 读取 reward/toInbox，空奖励会结束领取流程。
奖励先整体验证，再同一玩家事务写入，只有成功才记录 lessonsDone。
原表 lesson_00001 为 5000 金钱，lesson_00023/24 包含 50 经验。
`RewardProcessor.cs` 将 item11_0000501 当累计经验增量，不能存成普通库存道具。

5 项暂不发放：lesson_00008、00018、00020、00021 包含尚未实现交付的武将/战术；
lesson_00022 的原始金钱 count1min=1500、count1max=1000，自相矛盾，不能擅自修成任一数值。
资源达到容量上限时，本批也明确拒绝，尚未复原溢出邮件事务。

原 playerLevel 虽有 100 行，但原 defines.level_limit=15；5 级需要 po_mission_07000（索引 69）关闭，
10 级需要 po_mission_07001（索引 147）关闭。新玩家 cap 应为 5，不能因表有 100 行就开放到 100。
`UserStatus.cs:1247-1286` 同时检查全局等级限制、累计经验及任务门槛；
`PoliticMissionManager.cs:461-496` 的解锁回调读取 cap。
`UserStatus.ExperienceEntry` 与 `PlayerLevelTableAccessor.getNeedLevelUpExp` 证明经验为累计值：例如 200 升 2 级，500 升 3 级，不能每次升级扣除前一阈值。
一次调用推进至已满足门槛的等级是本模拟服的幂等处理策略；原服多级升级动画/逐级调用时序仍需客户端验收。
已有高等级账号不降级，也不批量重置存档。

另修正读取时的点数截断：`UserStatus.cs:861-890` 允许点数超过 maxPoint（UI 上限为 999）；
旧 `_apply_limits` 每次读取都取 min(point,maxPoint)，会损失已存的超额点数。本批保留它们；这不代表已确定药水溢出规则。

## 深入复核但仍保留待办的 5 个接口

### 用药

`WebApiClient.cs:2129-2136` 请求 potionId/quantity；`PoliticItemInventory.cs:107-145` 读取
`result.<pointKind>.point`，`SimpleInventoryDialog.cs:250-267` 与 RewardProcessor 确认该值是使用后的绝对点数，非恢复增量。
原 potion 表与本地化文本能确认半回复/全回复等用途，但没有证明奇数容量的取整、溢出上限、连续多瓶和自然恢复时间戳的服务端规则。
`initialAmount` 也不能当免费发放数量。`politic/support_item/usePotions` 不计入本批已实现入口。

### 日常任务

`DailyMissionScene.cs:104-195` 遍历根层每个值为 Hashtable，其中 point、mission、reward、exchange、item 各有自己的层级。
mission 行读 curCount/totalCount/getPoint，奖励行读 itemId/amount/state（及可选 point）。
根层键名不能由该遍历推断，也不能把这些字段平铺。

- `dailymission/getPoint`：`DailyMissionScene.cs:560-568` 读取大写 Result 的数值。
- `dailymission/getDailyMissionReward`：`DailyMissionScene.cs:385-403` 读取 Result 为领取索引，缺值表示领取失败。
- `dailymission/exchangeDailyMissionItem`：`DailyMissionScene.cs:351-378` 读取 Result 内的兑换索引 → 剩余活跃点。
- 两个写入口都传 rewardIndex，见 `WebApiClient.cs:4528-4543`。

原 daily_mission 表只有 id/missionName，不能提供目标次数、积分、奖励目录和每日重置规则。
这 4 个接口还需找到对应活动配置、计数来源和日界线，不能先返回全完成或虚构奖励。

## 验证与下一步

- `python -W ignore::ResourceWarning -m unittest discover -s tests -q`：200 项通过。
- `tools/progression_smoke.py --table-dir <原表目录>`：内存玩家跑完原版 24 项教程，19 项成功且不可重复领取，5 项失败前后状态不变；不写数据库。
- `tools/gameplay_smoke.py` 检查初始 cap 与原表约束。
- `tools/http_smoke.py --create-test-account` 新增时钟/心跳/自身标识、教程重复领取、前置任务、升级容量与重试验证；只改动并清理本次新建的随机测试账号。
- 服务端部署结果另见 deployment.json；本机原 Unity 画面、升级动画与完整教程流程尚未验收。

后续按真实客户端调用顺序处理城市建造/生产与关卡执行，优先闭合共享状态，再实现写入口。
静态证据不足时跑客户端检查协议消费与实际调用；**客户端连本 stub 的日志只能验证兼容性，不能反证自写公式就是原服算法。**
用户指出的支城、密书箱、收件箱、国战、城战、公会战、排行榜、收藏品、武具强化仍排除旧 AI 实现作为证据。
本批没有补回先前缺失的 10 个资源或 combo/strategy_battlefield 两张表；`stub has no assets` 与 `no stub response` 继续分别统计。
