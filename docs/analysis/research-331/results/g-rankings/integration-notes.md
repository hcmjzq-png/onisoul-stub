# G 接入契约（基线 8023c3f）

公共改动仅作为 integration.patch 交付：为 GameplayService 增加默认 None 的 rankings_read_view；
非 None 时才挂载 LedgerRankingsServices 的明确 8 项 APIS。默认 402/71/331 不变。
旧 SnapshotPair 接口保留供历史测试，新增生产链不接受人工 ScoreRecord/SnapshotPair 作为输入。

## I：必须实现的事务与读适配

`RankingStore.transact(player_id, transition)` 输入/输出为服务端内部字典：

1. 沿既有 guard 取得玩家锁，再取得全局排行账本锁/行锁；必须与 D 的 player→shared 顺序一致。
2. 同一数据库事务读最新玩家 revision 和账本 revision。调用 transition(player, ledger)；
   RankingTransactions 在锁内取得服务端时间，不接受客户端 timestamp/score/period/operation ID。
3. transition 返回 `(new_player,new_ledger,payload)` 后，玩家和账本一次 CAS 提交；任何失败全部回滚。
   UNIQUE(realm,operationId) 及全局 sequence；多国同时献纳也共用账本序列。不能先 save 玩家再发消息。
4. 持久提交成功后才返回 payload。CAS 冲突重新读并重算，沿用原可信操作 ID；已提交操作返回失败，
   不重放增量成功。数据库异常返回现有失败信封，不允许成功响应先于提交。
5. `read_view()` 在相同共享锁下读取完整账本，取得服务器 now，执行并保存 `seal_through(ledger,now)`，
   返回隔离副本与 now。切期不能修改此前 plans/事件。计划过期明确失败；新计划只能经审阅追加未来连续区间。
   单次请求只调用一次；跨请求允许换代。读操作可以推进账本水位，不修改玩家资源。

注意：服务端时间采用整秒；同一秒内按 sequence 排序。JSON 的键排序不得改变事件顺序。
当前实现以完整账本扫描为清晰可测试参考，生产大服须在不改变语义的情况下建立索引/物化投影；
不能删除去重收据或未保留等价历史的旧事件。测试 JSON oracle 的进程内 RLock 不算生产事务实现。

## A：城市来源与支城

将实际成功的建造完成、等级变化、部署、入库、出售/移除等**所有会影响基础石高的命令**，在保存前
接 `RankingTransactions.city(player_id, action, operation_id=trusted_id)`。不能仅在 query/login 扫库存后写历史。
失败命令不生成事件。测试已调用 `_build_from_draft`、CityServices.upgrade/store_buildings/deploy；
公共 HTTP 全路径尚未替换。首次新角色可在创建事务内记录“当下空城/当下真实城市”观察，不能倒填上期。

city_source 返回总分、eachKokudaka.0、实例→buildingTypeId/level/score/tableSha256。
基于原 helper 的主城基础求和是显式兼容政策，不是假称完整加成规则；任何内政武将和支城明确失败。
A 在确认技能触发、倍率、邻接、叠加和取整后应扩展同一来源，再把可追溯当前事件供支城条件使用。
本轮不凭这个受限总分自动开放支城，也不修改 A 文件。
实体已支持状态列表为 none/waiting；生产中状态待 A 证明石高不变后扩展，不能忽略有状态建筑造成全榜漏计。

## 金币 HTTP 和重登刷新

common/dedicate 原请求只有 category/article/token，无业务 nonce。内部 gold 方法不是 HTTP 已完成。
只有请求层可证明跨网络重发仍是同一操作时才准调用；随机新 ID、参数 hash、短时间去重均不能替代该证明。
不同操作可以献纳同额；同 ID 不扣第二次且不返回第二个增量成功。不能把测试 op 字符串复制到生产。
当前可复现原回调：gainPoint、bonus={}、dedication.point/limit/rank、myRank.rank/countryRank、nationalPower。
这些字段见补丁 docs/api_schema.md 溯源；bonus 空表只代表明确没有启用倍率的限定政策。

重登/getPlayerParams/periodicInquiry 所需 dedication 必须在当期共享视图中算 point/rank，limit 取最近城市事件。
不要把旧个人存档中的 point/rank 当权威；代码故意不写过期敏感的旧档字段。失回包后刷新余额和献纳状态，
不能通过重放成功回包让 MightOfNationDialog 再减 goldValue。common 国力对话框还缺 F 战绩，继续关闭。
本轮没有新增周期通知字段；不能捏造提示或奖励资格。

## D：国力商店

仅显式金币/无战争新服，调用 `national_context_data(ledger,country,now)` 得 `(global_period,power)`。
用 D 已有 NationalShopContext(country,period,power) 包装，且共享账本锁要覆盖 D 的校验、扣费、配额保存。
国家不是请求参数；从认证玩家取。realm+period 不随 country 改变，避免转国重复配额。
进服未发生金币献纳时，覆盖范围内国力 0 可证明；缺 ledger 不能替换成空账本或 0。
若 F 战争开启、物品献纳启用或旧服已有历史，goldOnlyNoWar 必须为 false，拒绝这个不完整统计口径。

## 旧档与资源

没有自动迁移。new_ledger 仅由明确的新服初始化调用，不可在文件不存在/读取异常时自动调用。
旧玩家历史分数、献纳、国力、额度都不能靠现有库存重建；需已验证的历史事件导入方案另行评审。
只读原 building/defines 使用正常 TableCatalog；本组小样本不替代完整运行表。
表文件不存在/不可加载→stub has no assets；已加载表缺被引用行、未支持状态/规则/周期→no stub response。

## 尚未验收

MySQL 跨进程故障恢复、正常 HTTP 注册后的客户端往返、原版领奖资格/奖励发放、日/周/月服别时刻、
全量 A 技能、F 国力转移/衰减、物品献纳、common 国力摘要。不得把 8 个 handler 计为完整原版玩法。
