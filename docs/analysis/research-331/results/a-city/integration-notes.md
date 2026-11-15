# A 组集成边界与字段来源

本轮只交组件；正常注册器必须维持 71 专用 / 331 占位。
`integration.patch` 仅为基于固定起点生成的 docs/api_schema.md 字段溯源补丁，**不开放入口**。
没有完成以下依赖前，不能把测试注册代码复制到 GameplayService。

## 生产（共享 completeTasks 由总集成修改）

- `ManualProductionServices` 的 start/bulk 使用同一 `_guard`/`PlayerServices.call`/CAS 保存路径。
  接入白名单候选恰为 `politic/task/submitProduceTask`、`politic/task/submitBulkProduceTasks`。
- productId/createdTime/dueTime 沿用当前 `player.produce` 存档，不引入新网络参数；
  `PoliticBuildingParameter.cs:191-199`、`PoliticMap.cs:242-263` 为重登消费者。
- 单体 dueTime/now：`StateManualProduce.cs:51-66`；批量 producings：
  `PoliticFSMCollectiveProduce.cs:95-127`。now 是本服注入时钟的整数秒。
- 共享 completeTasks 当前主动拒绝生产；本组件没有更改此逻辑。必须先解决道路/奖励/经验
  再同时接开工与收获。不能仅因开工测试通过而让用户消耗 PP。
- 当前内部任务不加 generation 字段。未来结算需要新的内部任务代次与收据，勿把内部字段
  自动摊入 getMapData.producings。原请求无 nonce：自动续产或新一轮开工后，延迟旧收获
  可能误结算新任务，不能简单用 buildingId 去重；也不能回放客户端奖励增量。
- 初始金币/MP/PP/BP 未改；读档不补资源。生产到期只由时间判断，不做“后台发奖”。
- I：操作集合为校验归属/空闲/表版本→扣资源/PP→写 produce/status→revision CAS；
  单玩家锁即可隔离本进程，但真实数据库并发仍需 I 验收。不可在 CAS 冲突后盲重试发奖。
- E/I：好友助产还缺 E 的访问资格、I 的双账号事务以及 A 的奖励/配额规则；没有注册好友入口。

## 支城与背景

候选白名单：`politic/map/getBackgrounds`、`politic/map/setBackground`、
`politic/shop/getBackgroundItems`、`politic/shop/buyBackgroundItem`，统一由 CityBackgroundServices 管理。
旧 CityProductionServices 的 bool 门禁仅保留兼容旧测试/出售注册，**新接入不得使用它开城**。

`acquire_facts(player)` 不是 HTTP 参数；必须在该玩家锁内、从与 candidate 相同 revision 的状态
读取以下内容，不得调用远程无版本快照，不得写固定 True 或固定7500：

| 依赖 | 接入方义务 |
| --- | --- |
| B | 第 2 篇第 5 话真实完成标志，数值0/1；不是最后 area/step、奖励已领、测试 completeFlags |
| G | 当前权威总石高；原 POM_MES_000281_03_005 明确主城+支城；不从未验证旧 kokudaka 字段直接开城 |
| 总集成任务状态 | 原任务 index306 真正 C；原奖励同事务发放，不能仅 OR unlockBits；accept/finish 的组锁存另须接任务公共模块 |
| 总集成地图生产者 | 已存在的 map1，40×40、原未开拓地块、名称来源；不能返回新造空白全开图 |

准入同时检查当前条件是**保守兼容策略**；原客户端可能分时锁存条件。如果历史条件已满足但
现石高下降且没有本服准入收据，不自动承认。需任务证明或可信迁移；不能读任意旧 missionChecks
充当认证。首次收据存下当时等级/完成/石高；后续保留开放，不重新按当前石高撤销。
这不是原服字段或签名系统，只在受信任服务端状态中有效。

`citySubcityAccessV1` 是内部存档。旧档没有它不会免费开放或给背景；非法/异账号收据明确失败。
`items` 是 A/D 已统一的归属，`mapBackgrounds["1"]` 保存选择。D 的原购买实现只读复用，
`static_background_sales=True` 须由总集成明确采用本服静态销售政策，不能解释成原服运营排期。
库存 near/far 两类未齐时选择器拒绝，避免原 UI 空数组索引；未恢复原默认背景，不填免费物品。

`map_profile(player)` 提供 `getMapData.mapProfiles["1"]` 的 name/nearGround/farGround，
字段来源 `UserStatus.cs:1322-1340`。当前主城协议固定 currentMapId=0，此 helper 尚未挂接。
总集成应在统一 snapshot 内投影并保存可能产生的准入收据；物理地图切换、占格和任务按地图过滤
必须一起验收，不能把主城建筑或 mapBackgrounds["1"] 投到主城 map。

## 可复现检查

```powershell
python -m unittest tests.test_research331_a_city -v
python -W ignore::ResourceWarning -m unittest discover -s tests -q
python docs/analysis/research-331/results/a-city/verify_evidence.py
git apply --check docs/analysis/research-331/results/a-city/integration.patch
git diff --check
```

证据核验脚本只读取原目录，不写 D:/onisoul 或客户端。31 行原表不包含人工账号；
人工隔离状态只在 tests/test_research331_a_city.py 中构造。HTTP、Unity、MySQL多进程均另验，
本次单元测试不等同于这些验收。
