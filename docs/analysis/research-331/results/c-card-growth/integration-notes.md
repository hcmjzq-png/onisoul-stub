# C 接入边界：事务、客户端显示和字段溯源

基线 8023c3f。只提交自有模块；`integration.patch` **仅追加 docs/api_schema.md 的字段来源**，
不自动开放端点。正常 GameplayService 白名单不变。统一注册人审查可信身份适配后，
才可调用 `CardGrowthServices(service).register_mutations(registry, operation_context=provider)`。
不得用 `lambda: True`、随机每 HTTP 请求 ID、请求内容哈希、token 或秒桶替代 provider。

## 可信身份的具体契约

原客户端 `WebApiClient.sendRequest:190-217` 对同一 form 最多重试 10 次；
`_httpCall:247-273` 的 httpCallId 不上网，而且不应在未核实并发递增语义时直接作唯一值。
原请求完全没有 nonce。这意味着：只看 HTTP body，无法分辨合法的第二次相同操作和重试。
**当前主仓库没有满足条件的生产身份提供者**，本轮不申请直接开放给未经适配的旧客户端。

建议总集成选择显式客户端传输适配（例如经审核的 Mono/Frida 包装，另立客户端任务）：

1. 在一次 `_httpCall` 用户意图建立时生成身份，放入发送上下文；在 sendRequest 的
   十次网络尝试前固定，不能每次 WWW/HTTP 请求重新生成。
2. 身份包括持久的安装/会话 epoch 与单调意图序号或一次意图 UUID；重启不得复用。
   身份必须随重试保留，不能仅由服务器收到的顺序猜测。
3. 网关验真实会话，将身份绑定玩家/API/原始参数摘要，以请求局部上下文提供
   `OperationContext`。业务 JSON 保持原字段，不从客户端 body 读取 operation_id。
   provider 须请求隔离（ContextVar 或等价）；不得存在共享全局“最后一个身份”。
4. 相同身份不同 body/API/玩家明确拒绝。客户端重登只改变 token、不改变先前已提交意图；
   摘要排除 token，账本按玩家持久化。相同参数的新操作分配新身份。
5. 未适配客户端保持关闭。网关不宣称“自己随机造 ID”已经识别原意图。

这只是待落实的传输契约；没有执行注入或修改客户端。服务端模块与隔离测试已验证该契约
下的结算，不声称该契约已具备生产实现。零成本请求重放也不是安全替代。

## 单玩家事务 / I 组适配要求

读认证玩家最新 revision → 玩家锁 → 验证 context/账本 → 验证全部引用/库存/上限 →
在副本执行全部变更 → 收据与状态同次 CAS 保存 → 仅保存成功后返回成功。

| 操作 | 同一次保存的集合 | 失败与重试 |
| --- | --- | --- |
| useDopingItem | items[itemID]、characters[id]三种总值/Add、cardGrowthOperations[identity hash] | 越 cap/缺数/错误引用整笔不写；旧提交拒绝 |
| useDopingRemoveItem | 消费铃、所有返还石库存、characters[id]、同上收据 | 有余数或任一返还溢出整笔不写；旧提交拒绝 |
| sellTactics | tactics.amount、resources.gold.amount、既有 cardGrowthTacticSales；新适配另同存 cardGrowthOperations | 新/旧账本都禁止成功增量重放；余额刷新后新身份可再次出售 |

不要求跨账号锁。未来 D 拍卖/挂牌须共用库存占用验证，不能只依赖编队检查。
多进程必须使用 I 的 revision/CAS 适配；本组测试是隔离内存 CAS，未验 MySQL。
存储异常在持久提交前失败应不写入；提交成功但响应丢失，重试读取收据后失败且不再结算。
禁止自动“冲突后随机生成新身份再执行”。

`cardGrowthOperations` 是本服内部字段。无此字段的 stub 旧档视为未运行过本组新道具操作；
不是导入原服历史。错误类型拒绝，不清洗成空账本。旧 `cardGrowthTacticSales` 完整保留，
其 payload 保留审计用途但不再返回；账本满 1024 不淘汰、需 I 做持久归档索引。

## 客户端一致性

`DeckSale_Tactics.cs:337-361` 每次成功加 sellPrice 并减 tactics；旧“重放成功”虽服务器
只扣一次，却会令客户端显示二次结算。现在已提交重试通过 errorReason 拒绝。
`GameRestarter.cs:70-95,111-126` 检出该字段后停止 RPC 队列；
`WebApiClient.cs:324-337` 不再调用成功消费者；错误框回调 reload/backLogin
(`GameRestarter.cs:16-44`)。因此不附成功数据补偿，也不能回传过期武将快照。

丢首次响应的玩家需要重开页面/重登，查询 common/getCharacters、getPotions、
common/getTactics 和 common/getPlayerParams。不是无感恢复；真机必须验错误框及重登。
原 getPotions 对零库存省略记录，使用/拆除响应则必须含刚变零的 `.amount=0`，
否则原 PotionHash 无法更新。完整原表 smoke 已覆盖这个差异。

## 字段溯源（交 docs/api_schema.md）

| 字段 | 来源 | 消费者和语义 |
| --- | --- | --- |
| useDopingItem.potion.<potionId>.amount | bundle | DeckUseItem_confimation.cs:187-203，替换余额，不是消费量 |
| useDopingItem.character | bundle | 同文件:204,232；DeckUseItem_ItemView.cs:176-195，整体刷新武将 |
| useDopingRemoveItem.addItems.<potionId> | bundle | DeckUseItem_confimation.cs:167-182；DeckUseItem_result.cs:150-174，**返还数量** |
| useDopingRemoveItem.changeItems.<potionId>.amount | bundle | 同文件:168-180，直接替换 PotionHash 记录；包含消耗至零的铃 |
| useDopingRemoveItem.character | bundle | DeckUseItem_ItemView.cs:167-173，整体刷新；Add 清零的有限实现见原预览与商城描述 |
| stat/对应 statAdd | bundle | CharacterStatus.cs:176-182；两者必须一起更新，总值含石头增加值 |
| cardGrowthOperations / OperationContext | compatibility-policy | 仅内部状态/上下文；不加入原请求/响应 |
| duplicate errorReason | bundle field / compatibility-policy use | GameRestarter.cs:70-95；这里的英文原因由模拟服定义 |

## 九宫格资格、存档与重试设计（尚未实现）

三项必须同批集成，不单开 claimReward。需要以下生产者及 I 的原子边界：

- 不可变活动版本 identity、有效期、九个真实 item_id、全部费用索引、奖励定义；
  不能复用 GenFake 数据、2013 年额外运营奖或当前日期造活动。
- 获卡事件带唯一来源身份/渠道/获得时间/基础物品；按核实过的渠道政策记 collection
  权益。当前库存不足以恢复历史渠道，禁止旧档扫描自动发资格。
- 内部活动存档需要版本 identity、九格已授权 flags、played count、已保存抽取结果/操作
  收据、已领奖 reward ID 集合。字段名尚未形成协议，不在本轮伪造玩家九宫格档。
- play：同一原子保存校验有效期/次数/费用/来源、保存一次抽取结果、扣款、授予已证
  获卡权益/生成真实实例；随机生产者缺失时拒绝，不能把动画 Random 当抽样引擎。
- claim：以服务端 line count 对比该版本配置 condition，再按 `(event identity,reward ID)`
  永久收据加奖励。原请求只有 reward，不能让旧请求在新活动轮回后领取同 ID 新奖励；
  因此同样需要可信传输绑定活动意图，或明确禁止活动轮换前公开。
- 同版本重复 claim 不重复发奖、不回放客户端新增奖励；领奖失败不能半写 claimed。
  扣款/物品/实例/领奖记录必须同事务；缺入箱实现则容量不够整笔拒绝，不能伪造 toInbox。
- getInfo 只投影可信活动/保存状态，不能以查询制造权益。缺活动配置是 no stub response；
  不称表资源永久缺失。没有原服字段能承载上述内部 version/nonce，就不添加新网络字段。

公开放行条件：真实来源事件与当前活动配置、可审核抽样算法、I 的原子适配、串行 Unity
验收全部完成。本轮仅八线几何可复用，不把这份设计记为已实现抽取或发奖。
