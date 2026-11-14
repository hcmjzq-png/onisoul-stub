# A 组：城市、生产与好友助产

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`。28 个入口逐项记录于
`reviewed-endpoints.tsv`，原路径、SHA-256、方法/行号、包装器调用点见 `evidence.json`。
只用原反编译及原表；没有使用旧 E 盘实现，没有启动客户端、改配置或部署服务器。

## 可集成代码的实际范围

`app/business/city_production_services.py` 新增三个入口，**均未挂载到 GameplayService**。

| 入口 | 支持范围 | 明确限制 |
| --- | --- | --- |
| sellBuildings | 当前账号空闲库存建筑；逐件原价求和、删库存、入金钱一次保存 | 不出售已部署/活动建筑；超容量整批拒绝；重试缺失实例失败，不再发钱 |
| getBackgrounds | 读取内部已有归属，返回 nearGround/farGround 的物品键 | 不赠送；仅原 shop_item_bg 启用行；归属未迁移/任一类别空时明确失败 |
| setBackground | mapId=0，已有归属的近景/远景同时选择并保存 | 不创建支城；重登回显需要总集成挂接 getMapData，当前仅提供投影 helper |

出售证据：InventoryUpdateSaleBuild 从库存建立列表，通过 building.itemId 调
ItemIdToShopIdTableAccessor.getPrice；InventorySaleList.update 直接求和，未乘建筑等级。
InventoryItemSaleBuild 的 `SellPrice == -1` 禁用按钮。原建筑样本田地价格为 50；
本次未在建筑关联价格中找到 -1，所以该测试明确使用人工变异，并未伪装为原建筑行。
回调读 buildings.Keys、gainGold、buildingCount；buildings 的值沿用售出记录属于兼容选择。
费用不足不适用于出售和选择；对应测试覆盖入金溢出，未宣称验证生产费用。

背景证据：mypageBgItemSelect.init 只枚举键；值 `{}` 是兼容选择。
原启用目录提供两近景、两远景，禁用的部分远景行却引用近景物品，本批不启用它们。
没有把 isEnable 当作所有权。backgroundOwnership、mapBackgrounds 是本服务内部提案，
前者由 D 的购买事务或有证据的迁移写入，A 只读；后者只存选择。
空列表会使 SelectItemCode 索引越界，所以不以空成功掩盖未迁移归属。

## 生产完整链路静态结果

1. 开工：WebApiClient.cs:897-915 的单体 buildingId/productId 与批量 buildingIds/productIds。
   StateManualProduce.cs:51-66 读根 dueTime/now；批量消费者读 producings.<id>。
   ProductsTableAccessor.getCost/getDueInterval/getRewardId 确认原成本、显示秒数和奖励引用。
   **显示时长不证明道路/技能后的服务端实际时长**。
2. 计时与重登：PoliticBuildingParameter.cs:172-199 分别读 task 与 produce；
   PoliticMap.cs:242-263 从 getMapData.tasks.buildings/producings 恢复。
   StateManualProduce.reset 根据 productId 恢复计时；不能只持久化 dueTime。
3. 收获：StateAutoProduce.cs:401-430 必读 producings.<id>.reward/building/collaborator，
   collaborator.<id>.exp 是其他建筑的经验值。StateManualProduce.onComplite 随后清除 productId。
   自动生产还读 autoProducings，按 durability 决定续产或死亡（:475-507）。
   显示预览第一奖励槽并不证明最终所有槽、道路、技能、协作经验与耐久扣减。
4. 重试：包装器没有操作幂等键；收获按 buildingIds 请求。未来需内部任务代次/结算记录，
   与扣费、收获、资源上限、等级经验一次事务提交。客户端加法奖励重放也需验证。
   当前 completeTasks 建造行为必须保留，不能被 A 的生产分支覆盖。
5. 取消：PoliticBuilding.cs:1137-1151 回调只清本地状态；没有退款规则证据。
6. 加速：accelerate_produce_task 的 time/credit 和客户端 credit*count 有证据；
   dueTime 下限、重复请求、提前完成后再点、最大次数仍不明确。
7. 好友：completeFriendTasks 是单数 buildingId（字符串），加速是数值 buildingId，
   两者有 friendPlayerId/mapId；回调还读 completecount/acceleratecount/errno。
   不能照自身批量接口复制。权限依 E，奖励归属/每日重置与双方事务均未完成。

因此未替换四个带 errorReason 的生产占位入口，未实现好友助产结算。
不把拒绝、包装器、查到字段算作完成，不声称全局占位数减少。

## 其他入口与支城

getMap/getBuildings/getTasksInCurrentMap/getBuildingLevels/getHarvestCounts/getBuildingFabrics、
setMapName 字符串重载、submitSerialBuildTask、好友配方与诏令 setWorkingValue
本轮仅定位包装器（调用点扫描有重载歧义，见 evidence.json），不能挪用 getMapData 的响应作为证据。
getBuildingLevels 请求的键是单数 buildingId，值为数组。
诏令的 missions、状态、timestamp/expirationTime 及 changeState 奖励嵌套已追到消费者；
触发抽样、期限、费用与服务端条件校验仍需独立完成，不信任客户端工作量。
conflateBuilding 回调证明 buildingId/building，但不能据此猜升级规则。
resolveBuildingEvent 缺省 demolished 会使客户端走拆除；空成功并不安全。
fixMapProduct 位于调试菜单，cleanup 位于标题恢复流程，不是普通生产接口。

支城没有实现：switchMap 回调只是触发重新加载，不证明拥有、解锁和城地图存档规则。
mypageBgSelectWindow.cs:135 硬编码 mapId=1，而列表使用 no_；本批明确拒绝 1，
不能为了该调用伪造支城。map001 是现服务内部主城键，不宣称原协议地图键已证实。

## 验证

在独立工作树运行：

```powershell
python -m unittest tests.test_city_production_services -v
python -m unittest discover -s tests -v
```

新增 12 项、全量 238 项通过，0 skipped；日志见 regression.txt。小样本逐行等于原表，
并记录原表与样本散列。测试覆盖认证、跨账号、批量原子拒绝、资源溢出、重复请求、
并发入账一次、保存 revision 冲突、重登、背景成对写入和缺表/缺行不同诊断。
这是内存状态验证，未进行真实数据库故障注入、Unity 回调或服务器部署验收。
已有玩家锁负责进程内串行化，数据库 revision 负责跨进程冲突；不是跨账号事务方案。

此前 10 个请求资源和两张表的缺失未由本组解决。原表引用异常不计作新增资源文件缺失。
