# D 组：交易、商城、游历与水运静态复核

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`，独立分支
`parallel/342-d-economy-20261115`。用户明确指定 D 组，因此采用同目录
`D-economy.txt` 的 39 个入口；未接管 A 文件的城市生产任务。

本批交付 **2 个未挂载的资源拍卖只读处理器**，覆盖有实际挂牌快照时的资源类别、
价格/数量区间筛选、排序、分页、过期过滤。另 37 项未实现，细分为回调/辅助函数已追踪、
只有包装器证据、非普通运营功能等，见 `reviewed-endpoints.tsv`。这不是 39 项玩法完成，
也不改变全局 342 个占位入口的计数。

## 确认的协议与问题

- `auctionResourceBrowse/Search`：`WebApiClient.cs:4423-4456` 请求分页和区间均用十进制字符串。
  `AuctionDataManager.cs:775-807,1070-1121` 逐项枚举根表，再读
  `price/num/period/remain_time/resource_type/item_sn`。成功根不能混入 `now/succeeded`。
  `item_sn` 是购买时提交的挂牌标识，根键被尝试解析为显示槽号，二者不能混用。
- 排序的请求名是 `credit/amount/remain_time`，对应挂牌的 `price/num/剩余时间`，
  不是按单位资源价格排序。见 `AuctionDataManager.SortAuctionResourceMap/GetSortString`。
  价格下拉 1–99、100–999、1000–9999；数量下拉边界也连续，支持包含端点的兼容实现。
  原服对边界和分页的响应仍需抓包。
- 武将拍卖 `CreateStatus` 要求根级 `price` 和 `remain_time` 映射，再将其他根值转为武将表。
  当前共享响应形态清单未覆盖这些浏览/搜索入口；这里只提交修正建议。
- `auctionCardSale/ResourceSale` 的 `params` 分别提供 `base/grade_mul/level_mul` 和
  `base/amount_mul`。源码证明税系数字段存在，不证明其原服数值。
- 背景商品 `shop_item_bg` 共 8 行，4 行 enabled，价格均为 168 credit；
  回调查询只读 `shopItems` 的键，购买成功删除该商品并更新可选 `resources`。
  `itemIds` 指向 item13/item14；选择页也按物品 ID 枚举。期限、初始归属和原服上架条件
  尚未证实，**未扣款、未生成永久背景归属**。本次 662 表提取目录没有 item13/item14，
  不能据此断言原客户端缺少资源文件。
- 国家商城读取 `state/remain`，原表包含 `goal/limitPerPerson`；整套购买发送 `index=-1`，
  不能直接套用普通商城的非负 index 校验。国家目标开放、限额重置周期未证实。
- `getShopItemsCredit/buyShopItemCredit` 和 `kokugi/addPoint` 在该反编译树仅找到包装器；
  不能因命名相似就别名到已有普通商店或允许客户端任意加点。
- 国技 `getStatus` 读 `selfPoint/levelRate/kokugiPoint`，`develop` 读 `usedPoint/point`。
  `levelRate` 来自响应；不能填常量 1 再声称复原国技。
- 游历状态位于 `<mapId>.errantry`；水运状态是裸 `<mapId>.trade.<buildingId>`，
  发船后还读 `catalog/tradeId/createdTime/dueTime/deck`。两种领奖都聚合
  `results.<event>.reward.<itemId>`，不是根 reward。动态结果表、随机规则、取消退款、
  船队技能和好友收益尚未闭环，未开放发送或领奖。
- netCafe 兑换读 `npoint/yellowSoul` 下的 `prev/current`；这是运营功能，
  不伪造活动、资格或兑换比例。

原路径、文件 SHA-256、包装器行号、回调方法行号与表行数在 `evidence.json`。
`build_evidence.py` 可在原始只读资料存在时重建证据清单；只提交两个小型原表样本，
没有提交反编译源码、完整原表或客户端资源。`resource_snapshot.json` 明确标记为合成测试数据。

## 实现范围及验证

`EconomyServices` 沿用 `PlayerServices` 的服务对象和玩家锁，但只读查询不加载/补齐/保存玩家。
通过构造参数注入一次一致读取的 `ResourceSnapshot`，没有 provider 时返回带 `errorReason`
的 `no stub response`，不会把“尚未接入市场”伪装成空市场，也不报 `stub has no assets`。
Snapshot 类、过期计算、300 条页上限、相同排序值按挂牌 ID 决定顺序、根显示槽编号以及
十进制字符串输出都是本模拟服兼容设计，**不是原服存储协议**。

只读处理器不提供买卖事务保证。生产适配器、拍卖生命周期和共享响应清单尚未接入。
即使测试注入了非空快照，也不能据此开放客户端拍卖购买按钮或宣称拍卖交易可用。

在此工作树运行：

```powershell
python -m unittest tests.test_economy_services -v
python -m unittest discover -s tests -v
python docs/analysis/parallel-342/d-economy/build_evidence.py
```

2026-11-15 本地结果：专项 10 项通过；完整回归 236 项通过，无跳过、无缺少可选依赖。
测试覆盖非空快照、筛选端点、排序后分页、过期、格式错误、认证、其他账号参数、
读后修改响应隔离、重复请求、重建服务、32 次并发读取及账号存档完全不变。
没有写操作，因此没有声称完成费用不足、扣款回滚或双账号事务测试。
未访问/部署服务器，未改 hosts/proxy80/config.ini，未启动共享客户端。
