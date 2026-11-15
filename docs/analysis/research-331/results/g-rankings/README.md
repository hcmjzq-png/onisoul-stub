# G：事件驱动的石高、献纳和限定国力

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`；分支
`feature/research331-g-rankings-20261115`。只修改 G 授权路径。

本轮完成 **1 条可集成组件闭环**：真实城市命令 → 原表单体石高 → 事件账本 →
金币扣费/献纳事件 → 个人、月期、国家聚合 → 排名、分页 → 上期查询。
提供 8 个未挂载查询投影和 1 个内部金币事务命令。**正式注册减少 0、Unity 验收 0**；
正常注册仍是 402 总数、71 专用、331 占位。原 51 项逐项状态见 [endpoints.tsv](endpoints.tsv)。
9 项有新增组件/数值边界记录，另外 42 项复用原协议证据并明确保留缺口；不能报成 51 项资料或玩法全部补齐。

## 新证据及采用范围

| 结论 | 判定 | 证据/限制 |
| --- | --- | --- |
| 单建筑石高在 grade×10 级内插值，逐步 float32，最后 Floor | verified-helper | `BuildingsTableAccessor.cs:637-642`。本次全文检索只发现 helper 定义，未找到直接调用；不能据此声称完整服务端汇总已复原。原 building 表田地 10→40、城 1280→2880、道路 0→0。 |
| 建筑发展提高石高 | verified-concept | [2012-08-24 Capcom 公告转载](https://www.4gamer.net/games/150/G015000/20120824048/) 的石高章节与客户端原表方向一致。日服测试期材料，只支持概念，不将其 1500 解锁门槛套到 2014 中文版。 |
| 金币预览按 1000 金一步、1 点贡献；成功 gainPoint 加到国力 | verified-client | `MightOfNationDialog.cs:235-271,334-355`；请求 `WebApiClient.cs:636-643`。生产仅实现显式无倍率、金币限定、无战争模拟服政策；未证明原服全部倍率。 |
| 献纳上限随石高更新不下调 | verified-client / compatibility-policy | `UserStatus.cs:795-802`；defines `scale_kokudaka_for_dedication.value=10`。组件只继承自己的事件上限，绝不信任旧档人工 kokudaka/limit。跨期仍保持高水位为本服政策，原服跨期上限重置未证。 |
| 国家合战榜为胜率指标 | verified-JP-concept | [2012-10-26 制作人访谈](https://www.gamer.ne.jp/news/201210260034/) 与 `HTMLRankingMediator_Country.cs:94-127` 的 score×100 显示一致；不等于个人合战积分，不使用献纳榜替代。 |
| 活动榜周期和奖励资格不能泛化 | verified-JP-event | [2014-01-23 公告](https://www.gamer.ne.jp/news/201401230027/) 的恶鬼全国榜为指定维护区间，且同国额外奖励要求参加排行。不能推成全部周榜规则或无条件给全国家发奖。 |

[external-evidence.json](external-evidence.json) 保存日期、服别、版本对应、访问状态、冲突及实际检索。
S4/S5 和相关巴哈楼层正文返回 403/不可访问，摘要仅保留线索。
“每月最后维护重置”和“台湾时间 23 点日结”**均未采用为生产排期**；观察者时区不等于台服。
同分原规则未找到可靠全文证据；周榜、日榜、月榜并非同一时钟的别名。
原源码散列、表行来源见 [source-proof.json](source-proof.json) 和测试小样本来源清单。

## 实现与边界

- `rankings_aggregation.py`：`RankingTransactions.city` 包装 A 的已验证命令，在同一次提交内
  生成 `record_city`；计算主城已完成、已部署、空闲建筑的基础石高，保存逐实例贡献、原表行散列。
  正在施工及库存建筑不计入是本服求和政策。任何内政武将、非主城或未支持建筑状态明确失败，
  不猜技能、道路石高倍率或支城石高。A 可复用 `building_kokudaka/city_source`，本轮没有另造技能公式。
- `RankingTransactions.gold` 实际校验余额、1000 步长、事件上限并扣金。必须已有与当前城市一致的
  事件，旧档人工分数不能授权献纳。回包是原字段；操作 ID 仅服务端内部，**common/dedicate 未挂载**。
  同一个操作重试失败并要求刷新，不重放会让原客户端再次扣钱/加 gainPoint 的成功响应；
  不同可信操作允许相同数量的合法连续献纳。
- `rankings_periods.py`：每个指标有独立显式 UTC `[start,end)` 区间和全局期次 ID，原日/周/月榜
  时刻不猜。`seal_through` 在共享事务内推进时间水位后才发布视图；旧时间写入拒绝。
  上期按事件时间重建；初始覆盖前的历史缺失明确失败。石高保留最近真实城市值，献纳按区间求和。
  零事件区间只有在账本覆盖范围内才是已知空榜；不能从当前建筑库存倒填历史。
- `LedgerRankingsServices` 批量生成石高、普通献纳、月献纳、国力的列表/摘要共 8 项。
  单次请求只读一次隔离账本；页内数字键从 0 重起、endIndex 为闭区间、最多 100 条；本人名次不受分页影响。
  同分采用 1/1/3，同分按身份字符串排序，明确是兼容政策。国家条目使用 countryId，不能混成玩家行。
  float32/Int32 不可精确显示的分数在写入/投影前拒绝，不舍入或夹紧权威分数。
- D 的 `national_context_data` 给出真实金币事件累计值与 realm+period 全局配额期次。
  仅 `goldOnlyNoWar=true` 的显式新服政策可用；若战争、物品献纳、国技等生效，应关闭这条限定国力路径，
  等 F 的真实转移/衰减等事件接入。它不是完整原版国力公式。

原请求没有快照版本。单次响应内 current/last 来自同一账本和同一服务器时间；相邻两个 HTTP
请求可以跨期。历史 Around 先读当前摘要名次再请求 last 的原客户端局限保留，不能改 brief.rank 含义。
奖励资格与发放均未实现；未伪造 rankingId、nextswitch、战绩、玩家或收益。

## 验证和交接

`python -m unittest tests.test_research331_g_rankings tests.test_research331_g_integration tests.test_rankings_services -q`：35 项通过。
`python -W ignore::ResourceWarning -m unittest discover -s tests -q`：437 项通过、0 跳过。
测试使用隔离临时 JSON 原子替换存储和真实 CityServices 命令；验证扣费、升级、入库/再部署、重建对象后回读、
同额合法重复、同操作并发只提交一次、保存失败不半写、切期、月期分离、国家隔离、原回调数值/层级及精度。
临时文件存储只是测试 oracle，**没有验证 MySQL 跨进程事务**。

[integration.patch](integration.patch) 以本轮基线生成并通过 `git apply --check`；只提供可选注册注入及字段溯源。
独立测试在内存应用实际补丁，验证只有显式注入才替换 8 项，common 两项仍未开放；公共文件没有被测试改写。
公共文件未应用补丁。I 的共享事务、A 的城市写路径、D 的国力锁和重登献纳刷新仍需按
[integration-notes.md](integration-notes.md) 接入；当前不能直接部署即宣称原服完整闭环。
原客户端操作交由总集成依 [capture-plan.md](capture-plan.md) 串行验收。

B/F 未提供真实战斗/恶鬼/城战/天下战等战绩的 41 个排名/统计入口继续关闭。
`common/getBriefOfNationalPower` 另外需要战斗历史、国家档位与城战变化，不能拿 ranking 同名摘要替代。
缺表文件为 `stub has no assets`；缺行、未知规则/账本/历史为 `no stub response`。
本轮没有修改 hosts/proxy80/config.ini、其他组工作树或生产玩家，没有部署或合并。
