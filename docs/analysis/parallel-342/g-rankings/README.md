# G：排行、献纳与国力统计

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`；51 个入口逐行见 `reviewed-endpoints.tsv`。
本批交付 **2 个未挂载的石高快照查询处理器**，不是 51 项玩法完成，也不减少全局占位计数。
其余入口保留待证状态；没有修改公共派发器、旧处理器或服务器。

## 已落地范围

`RankingsServices` 沿用 `PlayerServices.call`、玩家锁和现有读档/保存机制。
`getRankersInKokudaka` 对完整国家快照排序、分页并计算当前认证玩家的位置；
`getBriefOfKokudaka` 从同一快照对取得本期分数、本期名次和上期名次。
请求中的 playerId/country 不会改变认证归属。空榜与未提供快照严格区分；缺期次不复制当前榜。
不会扫描既有玩家等级当分数，不把旧存档未经验证的 kokudaka 自动认定为可信来源。

`ScoreRecord/Snapshot/SnapshotPair` 都是**本服务内部接口**。
排序采用分数降序、同分共名次（1/1/3）、同分按 playerId 字符串排序，这是兼容决策，原服同分规则未证实。
每页最多 100 条是与客户端最多遍历 100 条相容的服务限制，不是原服限额证据。
没有自动刷新日期、历史周期、奖励或发放逻辑。真实数据提供器、数据库快照事务和历史迁移仍由总集成完成。
注入测试分数只验证代码，不作为原版协议或玩法证据。

## 协议形状与来源指标矩阵

| 家族 | 来源指标与分组 | 已核对消费链 / 差异 |
| --- | --- | --- |
| 石高 | A 的已验证城市石高；本国玩家；current/last | WebApiClient:3021,3051 → HTMLRankingMediator_Kokudaka:17,43 → HTMLRankingMediator:commonOutput/send；brief 经 mypageRankingWindow:497,787。 |
| Battle / Daily | B 的战斗结算；常规/日榜不同 | HTMLRankingMediator_Battle 调用不同入口，共用玩家条目。不能以等级或次数代替得分公式。 |
| 国家 Battle | 国家胜败、胜率；非玩家榜 | HTMLRankingMediator_Country:49,94,117 根 `countries`，条目 `countryId/rank/score`，显示 score×100；CountryRanking:105-148 消费 `won/lost/rank/timestamp/neighboring`。 |
| RaidBoss / Daily / National | B 的恶鬼结算；日、国家指标分别待证 | HTMLRankingMediator_RaidBoss 与 National 系列；National 请求结束键为 `stopIndex`，不能全改成 endIndex。 |
| Gigantic / MaxDamage / Countries | B/F 的巨恶鬼贡献、最大伤害、国家贡献 | HTMLRankingMediator_GiganticRaidBoss/GiganticMaxDamage/GiganticPoint；国家贡献条目 countryId，不能套玩家字段。Daily 包装器没有找到直接消费点。 |
| Dedication / Monthly | 真实献纳账本；月榜独立 | HTMLRankingMediator_Delivery；月榜 Around 使用 monthly brief，但 getCurRank 的 monthly 分支仍指普通献纳接口（原客户端现象，不能据此合并账本）。 |
| NationalPower | 国家国力聚合 | HTMLRankingMediator_NationalPower:send 使用 rankers 内 countryId，非 username/playerId。国家聚合周期尚未知。 |
| NationalRanking | rankingGroup 指定全国指标；all/weekly | WebApiClient:3095-3118：weekly 包装器没有发送 week；两种包装器均发 stopIndex、rankingPeriod。ranking 表中的开关不证明历史活动当前开放。 |
| Brawn / RandomQuest | B 的对应战绩指标 | 对应 HTML mediator 与 mypageRankingWindow 消费，不能从榜名反推完整计算或结算规则。 |
| Siege | F 的角色 role 分组结算 | 请求携带 role；不能把攻击、防御排行榜合并。 |
| Strategy / Mypage / Pie | F 的 battlefield/team/action 指标 | Mypage 不发 battlefield/team/term；Pie 是国家条目、整数 score，不是国家 Battle 的百分比。 |
| TurfWar / Daily / Around / Top / MyRank | F 的战场、阵营、胜点 | 常规分页走 HTMLRankingMediator_Tenka；Top 经过 TurfWarBriefCache:422-449。包装器 Top 的 index、DailyAround 的 team 未发送。若只有包装器，TSV 明确标注未证回调，不能套通用形状宣称完成。 |

普通玩家榜：根 `entries/myRecord/rankers`，`rankers` 是从 `0` 起的当前页条目映射；
条目 `rank/score/username/playerId/country`；个人记录 `rank/score`。
`HTMLRankingMediator.cs:calcRankRange` 的 `endRank=topRank+rankNum-1` 证明闭区间；
`convToTurnStr` 把 HTML latest/pre 转为请求 current/last。
`createMyRankHash` 把缺个人记录或 rank=-1 当未上榜；不是固定名次 0/1。
时间戳、nextswitch 有缺省分支，本批省略，避免编造排期。
奖励预览另经 HTMLRewardMediator:407-425,484-501 读取 brief.rank/brief.rankingId/brief.nextswitch；这里的 nextswitch 位于 brief 内，不能与列表根时间字段混淆。
`mypageRankingWindow.cs:787-797` 的 brief 使用 score/rank/lastRank，rankingId 有空串缺省。
所有表只提供配置/显示/奖励规则片段，不提供在线排行榜。

## 献纳追踪与保留边界

- `WebApiClient.cs:596-643`：category 为 character/building/tactics/equip/gold；article 前三种实例数组或战术数量表，金币为 `{"item11_0000101": count}`。包装器没有可用业务幂等键。
- `MightOfNationDialog.cs:8,235-271`：金币 UI 步长 1000，预览按金币整数除 1000 增加贡献并检查 limit。`onDedicate:324-355` 成功才本地扣金币、累加 gainPoint 至国力/变化量。这证明成本与预览，不证明活动奖励倍率、服务端溢出/舍入规则或周期。
- `DefinesTableAccessor.cs:225-229` 与原 defines 行给出 scale_kokudaka_for_dedication=10；`UserStatus.cs:795-802` 用 max(石高×10,已有limit)，不能简单把上限每次重置为石高×10。
- Character/Buildings/Equip/TacticsTableAccessor 各自读取 dedication；这些是卡片/建筑的基础预览值。没有据此猜测 bonus、生效日期或资产可献纳资格。
- `DedicateOfMaterialsDialog.cs:145-155,190-225`：gainPoint<0 为失败；成功还读 bonus、myRank.rank/countryRank，更新 dedication 和建筑总计。`UserStatus.cs:458-495` 的 dedication 是嵌套 point/limit/rank。
- `common/getBriefOfNationalPower` 经 MightOfNation→MightOfNationDialog:128-219：dedication **是根数值**，还需 dedicationRanking.prev/current、battleRanking.prev/current、nationalPowerRanking.current、rank 字符串、change、nationalPower、kokudaka。不可复用献纳回包或 ranking 同名摘要。

未实现献纳写入：资产保护/编队/部署状态、时效倍率、国家聚合与奖励、周期、重复提交语义和跨账号事务尚不完整。
不扣费后返回伪造名次，也不把没有账本称为 stub has no assets。
已有表缺行是引用完整性问题；只有实际资源/表文件缺失才使用 stub has no assets。

## 取证与验证

`evidence.json` 分开记录原源码 SHA-256/方法/调用行号、原表来源散列与服务兼容选择。
`rankings_review.py` 可从只读原始目录重建 51 行清单与 7 个小型样本；词法直接引用只是定位线索，不是结算证明。
无直接引用的包装器不等于不可达（还可能有委托/反射），因此只写“未找到直接调用”，不写“废弃”。

命令（G 工作树根目录）：

```text
python -m unittest tests.test_rankings_services -v
python -m unittest discover -s tests
python docs/analysis/parallel-342/g-rankings/rankings_review.py
```

2026-11-15：新增 9 项通过；完整回归 235 项通过，无可选依赖跳过。
覆盖真实输入分数排序、闭区间分页、页外个人名次、current/last、缺数据与空榜区分、认证/国家隔离、非法参数、同分策略、重复与并发读、重建服务后读档不变、快照一次读取和响应隔离。
只读模块不扣费、不交易，无新增写事务；未声称已验证快照提供器的跨进程事务/持久化。
公共测试原有 ResourceWarning 已观察到，不在本分支修改。
