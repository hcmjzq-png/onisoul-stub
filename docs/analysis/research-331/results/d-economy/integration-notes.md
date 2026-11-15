# D 集成说明

## 本轮补丁

`integration.patch` 以固定基线生成，只涉及 `server_tables.tsv` 的 27 张漏导出原表声明、
资源 Browse/Search 裸映射形态以及 `docs/api_schema.md` 字段溯源。
补丁不注册写处理器，不添加生产规则，不复制任何完整原表。
总集成先复核源包散列，再在自己的隔离目录使用公共提取器导出这些声明表。

## 旅交易

候选白名单仅 `politic/errantry/send3/getStatus3/receive3`，不能调用模块 register 后误算正式完成。
必须先补齐：

1. `DeparturePlan` 可信生产者：真实 `totalIntelligence`、效果/国技/国力奖金、结果抽样。
   `PoliticDeckTableAccessor.cs:87-113,178-185` 总智略由服务端传入，不等于客户端求和。
   结果表有阈值并不证明抽样算法。不得注入测试 planner 或统一失败/成功结果。
   planner 只返回槽位/本人的实例 ID/智略/resultId，奖励数量必须由模块按原奖励行重新验证。
2. A/共享写接口使用 `assert_errantry_unlocked`：在已持有玩家锁的建筑收回、出售、进化、升级、
   移图操作前检查 building_id；主城内政队变化前检查 politic_deck=True。
   派遣期间也不得通过其他成长/出售路径删除这些成员。仅冻结实例 ID 不恢复属性快照规则；
   本模块到期时再次比对卡槽，拒绝不一致，但不能替代统一写路径锁。
3. `getStatus3` 同一回包同时输入两个消费者（`PoliticMissionProgressList.cs:316-321`、
   `PluginPoliticDataManager.cs:157-162`），必须包含 `<mapId>.politicDeck/totalIntelligence`。
   本轮已补完整字段并要求 `deck_provider` 提供可信计算；该 provider 无权写存档或选择奖励。
   `status` 校验武将 baseId/voice/grade 与本人卡一致，校验槽位与实际编成一致。
   不存在本轮另造的 getPoliticDeck 接口。periodic/登录刷新应复用一致状态来源，不能免费补点。
4. 现有单玩家 `_guard` + revision CAS 同次保存记录/PP/gold/奖励。生产数据库按其实际 CAS 验收；
   本模块在可变副本上工作，失败不调用 `_save`，成功在保存后才回包。
5. `economyErrantryV1` 是内部字段，不是原网络协议。仅 absent 表示从未开始，坏档拒绝覆盖；
   完成后保留 phase=received、results、dueTime、evidence。旧存档不补造历史旅次，不自动开新一期。
   首趟限制不能在集成时随手删除：原 wire 没有旅次 ID，跨趟重放必须先解决。

固定奖励范围只支持独立 group、ratioMin=ratioMax=1、countMin=countMax 的紫魂/技宝珠；
额外概率奖励、角色/家宝/图纸/随机国别交付直接失败，且必须在扣费前失败。
`call3` 未实现：取消退款/计数/召回边界缺证据，不能从回调“不读余额”推出“不退款”。

## 资源拍卖与 I

只读参考 `D:/onisoul-worktrees/research-331-i-infrastructure/app/state/transactions.py` 工作草稿的
`atomic(player_ids=..., shared_keys=...) -> UnitOfWork.players/records`。
未复制、修改或依赖其未提交代码。总集成应固定 I 最终提交后跑适配测试。

内部共享键 `('economy', 'resource-market-v1')`；schema=1、listings、receipts。
这是本服粗粒度市场存储，原子性优先；吞吐、容量和收据保留/分片尚未生产验收。
不能删除收据/已成交墓碑以复用 ID。I 管理 `_revision`，D 不修改它。

| 操作 | 玩家锁 | 共享锁 | 同事务变化 |
| --- | --- | --- | --- |
| post | 卖家 | market | 资源/金币扣除、托管挂牌、操作收据 |
| buy | 买家与卖家 ASCII 排序 | market | 买家扣 credit/入资源、卖家收益、挂牌 sold、收据 |
| off_shelf | 卖家 | market | 入资源、挂牌 returned、收据；手续费不返还是兼容策略 |
| selling | 卖家 | market | 无写入；包括过期未取回挂牌 |

buy 预读卖家仅用于确定锁集合，入锁后重新校验 owner/phase/expiry。
所有玩家锁必须先于共享记录锁；不得持有 market 锁再补拿玩家锁，不得在事务内调用 `_save`。
异常、死锁、提交错误必须整笔回滚；需要重试时重新读锁，沿用可信操作 ID。
本组 `MemoryAtomic` 只位于 tests，不能当生产适配器。

集成构造 `ResourceMarket(atomic=I.atomic, read_market=<一致只读查询>, rules=<经核实配置>)`；
`EconomyServices(service, resource_snapshot=market.snapshot)` 可复用 Browse/Search。
`read_market` 必须返回从共享记录库单次一致读取的副本；缺记录失败，不把固定空快照当市场。
首次 post 会生成真实 market 记录。read_market 的 SQL/索引与 I 确定。

HTTP 写适配器尚未提供，理由：原 OnShelf 没有操作标识，`slot_id` 会复用，
不能把 actor+slot+参数的哈希当永久请求键，也不能每次重试生成新 UUID。
`operation` 是可信传输/业务层提供的稳定内部身份，**不是新增客户端字段**。
因此目前 post/buy/off_shelf 是可测试组件 API，不是已挂载 handler。
售出和撤回唯一挂牌 ID 足够防止二次交割，但新上架仍须解决旧请求与新意图的区分。

`ResourceMarketRules` 所有字段必须显式传入，没有默认值。
base_tax/amount_multiplier/seller_ratio 要核实原服手续费及成交扣税；minimum_level/slot_count
要核实本安装包 prefab 与台服更新；periods 的 8/12/24 小时有 UI 候选，600 秒按钮是否上线未知。
`delivery='direct-refuse-overflow'` 是限定兼容策略：原客户端有双方邮箱满的错误，尚不能宣称恢复邮箱交割。
测试的 1000、0.001、1、20、3 都是合成配置，禁止复制到生产。

武将拍卖仍需 C 的禁售/保护/编队/仓库/锁定适配、实体转移及新实例 ID 分配；没有只扣钱不交卡的处理器。

## G / 国家商城与国技

`economy_shop_services.py` 完全保持 #50 状态；背景两个接口归 A，不能注册本类整张表接管背景。
国家商城仅候选 getShopItemsFromNationalPower/buyShopItemFromNationalPower。
`NationalShopContext.country/period/power` 必须来自 G 的真实统计及明确周期并锁至保存完成。
period 全局唯一且不可按国家独立重置；外站“每月末维护”不是本服排期来源。
仍为 27/38 个限购一次的 gold 图纸套装，已有代码并非本轮新增完成项。
国技 `selfPoint/levelRate/kokugiPoint` 和 develop 的 `usedPoint/point` 要接真实献纳生产者、国家共享点数
及周期倍率。`addPoint` 只有包装器证据，不开放任意增点。
get/buyShopItemCredit 无原调用者；Npoint 无认证网吧时长/兑换规则；均保留关闭。

## 原字段溯源（供公共 api_schema 合并）

- bundle：WebApiClient.cs:3480-3514，send3 mapId/buildingId/errantryId；receive3 mapId；getStatus3 token。
- bundle：UserStatus.cs:603-624，send 的 isActive(bool)/dueTime(number)/errantryId(string)/buildingId(number)。
- bundle：UserStatus.cs:1765-1786，getStatus3 的 `<mapId>.errantry`，未出发只投影 isActive=false 为本服兼容策略。
- bundle：PoliticMissionProgressList.cs:316-321、PluginPoliticDataManager.cs:157-162 同时调用
  UserStatus.updateErrantry 与 PoliticDeckTableAccessor.update；后者 :87-113 无条件读取
  `<mapId>.totalIntelligence(number)/politicDeck.<slot>`。成员 :28-52 读取 int/intAdd/grade(number)、baseId/voice(string)。
- bundle：PoliticFSMErrantryReward.cs:26-82、PoliticScriptCommand.cs:1129-1186，
  receive3 的 catalog/errantryId/results.<slot>.resultId/reward.<itemId>；数值奖励，原消费者增量。
- bundle：WebApiClient.cs:4467-4489、AuctionSellResourcePage.cs:341-367、AuctionResourceSellSlot.cs:108-185，
  资源上/下架 result=1 / item_sn / resources；购买 SingleAuctionResource.cs:215-235 result/resources。
- bundle：AuctionDataManager.cs:843-877,1070-1121，卖家裸槽位映射+params.base/amount_mul，
  公共 Browse/Search 裸显示槽位映射；item_sn 才是挂牌标识。
- 兼容策略：内部记录结构、冻结结果、墓碑、失败重试、直接交付、精确十进制手续费；不伪称原服务端数据。
