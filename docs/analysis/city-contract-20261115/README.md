# 城市接口、道路与生产依赖复核

基线是 PR #37 合并后的 `f28b871`：402 个入口中 51 个有专用处理器，351 个占位。
本批检查其中 28 个城市入口的工作状态，新增 **8 个限定范围的处理器**，专用入口 59 个、剩余占位 **343** 个。
28 项并非全部深入还原：逐条状态见 [reviewed-endpoints.tsv](reviewed-endpoints.tsv)，标为 indexed_only/wrapper_only 的入口仍只完成索引检查。

## 道路证据与纠正

用户提醒田地会受道路加成。重新检查原表容器，在教程 `POM_MES_000006_03_001` 找到明确说明：

> 邻接道路的建筑物拥有提高生产量的效果……建筑道路并不会消耗金钱和内政点数。

原文、容器 SHA-256 与字节偏移见 [source-proof.json](source-proof.json)。它来自原安装包，不采用旧 AI 客户端内容。
三个道路类型 building200_051/052/053 对应 draft2000051/52/53，原表 size=[1,1]、costTypes/costAmounts=[]、
isConsume=false、immediateBuild=true、continueBuild=true、progressCount=0。
`PoliticBuilding.cs:1239-1275,2350-2387` 的即时建造分支不扣内政点，证据与教程一致。

因此修正旧服务端所有建造一律扣 1 PP 的错误：即时装饰物按原标记不扣 PP；普通建造缺 PP 则拒绝，不能把负余额截到 0 后仍建造。
本批补通免费道路批量/连续建造，其他批量建筑仍明确失败，避免臆测数量费用、自动生产及奖励。

**13～17 粮食只是原 reward01_politic 中的数量边界，不能据此断定随机，更不能擅自设等概率。**
道路加成系数、接触边/角的条件、连接城堡是否必要、多个道路是否叠加，以及开工还是收获时取布局，都还未证实。
`PoliticRoadChecker`/`PoliticConnectBase` 找到的是道路贴图连接/桥梁标记逻辑，没有发现与收益相连的算式；不能把贴图的八方向邻接直接当作收益规则。
本批不写生产发奖公式，也不根据 countMin/countMax 猜道路加成。

## 已落实的 8 个入口

实现位于 `app/business/city_services.py`；认证玩家、玩家锁、存档 revision 检查沿用现有事务层。
任一校验失败均不保存本次修改。批量全有或全无是本模拟服的兼容策略，不声称原服部分失败时也这样处理。

| 入口 | 本批范围与证据 |
| --- | --- |
| `politic/task/submitBulkBuildAndComplete` | 只接受原版三种免费道路。`PoliticFSMConstruction.cs:472-532` 读 buildings、autoProducings、originCoords；坐标实际是 originCoords.<实例ID>."0"/"1"，不是根 0/1。返回按实例 ID 索引的原建筑记录。 |
| `politic/task/submitSerialBuildAndComplete` | 同一道路范围。`PoliticBuilding.cs:2402-2478` 循环 0..Count-3，读数字根行的 x/y/buildingId/building，另有 autoProducings。成功回包为 N 行 + autoProducings + now，省去 succeeded 以满足 Count-2。第二个元数据名选用现有 now 是兼容选择，原服原始包仍待验证。失败保留 succeeded=false。 |
| `politic/map/relocateEnded` | 原请求是完整的 `x<number>y<number> → buildingId` 布局，见 PoliticBuilding.getPositionJSON 与 PoliticBuildingList.getBuildingPositionHashtable4Relocate。先验证完整归属、尺寸、边界和最终布局重叠，再整体更新；支持交换位置，不因旧位置挡住新位置。只支持主城；移动中的建筑须空闲。 |
| `politic/building/putInBuildings` | 原 PoliticMap 通过 deployedMapKey="none" 识别库存中的建筑。保留实例、等级、经验，移除占地；重复收纳不复制。只支持空闲 none/manual/single 类型且 connectChipType=none。道路/护城河的移除不是普通入库，自动生产与活动建筑未接入。 |
| `politic/building/deployBuilding` | 原 PoliticBuilding.deployInventory 要求数值 buildingId、building、autoProducings；按已有实例再部署，检查 map0、边界和占地，不创建新实例或重新扣图纸。只支持上述库存范围；同位置重复请求不产生额外状态。 |
| `politic/building/levelUpBuilding` | 返回 building；依据当前级别行扣 needExp、建筑基础成本 × needCostRatio，以及 1 PP。经验不足/零 needExp 满级/费用不足/非空闲均失败。 |
| `politic/building/levelUpBuildings` | 每个唯一实例升一级，原批量消费者读 output_buildings。整组先校验并在一次玩家事务保存，防止部分扣费。 |
| `politic/building/levelUpBuildingCollectively` | levelUpTimes 是升级次数。逐级扣经验及对应费用，返回 resultBuildings、totalUsedPoint、restResources；后三者的嵌套层级按 PoliticFSMProduct.cs:1086-1124 修正。 |

升级证据：`LevelUpTableAccessor.cs:29-32` 拼接 levelUpTypeId+(grade*1000+level)；
`PoliticBuilding.cs:271-285` 判断 needExp，`1925-1948` 把 float32 比例乘 1000 后取整，再乘基础费用并整数除 1000；
`2258-2332` 的连续升级算法逐级扣 needExp 和 politic_expend_point。
与玩家累计经验不同，建筑经验是**逐级消耗**。原田地从 1→2→3 级消耗 20+100 建筑经验、100+140 金钱和 2 PP。
本批不生成建筑经验；测试中的经验只注入隔离测试账号。
升级请求本身没有请求 ID；如果再次请求仍有足够经验和费用，它代表下一次付费升级，不宣称请求级去重。

其他边界：收获/生产中的建筑拒绝移动、收纳和升级，以免在加成结算时点不明时改变计费或收益条件。
石高更新、支城、活动贡献及排行联动仍未还原；新城市接口省略可选 kokudaka 字段，保留现有存档值。
`UserStatus.cs:1820-1830` 在字段存在时才更新石高。不能据此把这 8 个入口标为全部玩法完成。

## 生产链发现与待办

原表连接检查见 [table-audit.json](table-audit.json) 与 [product-dependencies.tsv](product-dependencies.tsv)：

- 1343 个建筑、1288 个生产项、2183 个建筑等级行、837 个图纸逐项连接。
- 588 个生产项的奖励数量上下界不同，625 个需要进一步核实选择规则；这两组可重叠，均不能直接解释为随机。
- 8 个生产项引用的奖励行不在原 reward01_politic 表中，3 个建筑缺少初始等级行；这是静态行引用问题，未证明客户端实际触发，不计为新的资源文件缺失。
- 建筑 products 引用均能找到对应生产项。

`submitProduceTask` 的 StateManualProduce 回调调用 updateTask，实际读取根 dueTime 与 now，旧报告的“无字段”遗漏了这个辅助函数。
`submitBulkProduceTasks` 返回 producings.<建筑ID>.productId/createdTime/dueTime。
`completeTasks` 的生产分支读 producings.<建筑ID>.reward/building/collaborator，与开工时同名 producings 不是同一种记录。
已有 completeTasks 只处理建造完成，本批没有把生产结算伪装为已实现。

`getProductsByBuilding` 消费 products 的键；生产许可、openLevel 对应哪个等级、openMission 条件仍需核对。
开工费用还依赖 building_level.costRatio，生产耗时/收益可能依赖建筑等级、道路及协作者。
收获幂等、取消/退款、加速、耐久、自动循环和任务计数必须与同一生产记录一起实现，当前保留待办。

## 新玩家初始资源纠正

用户补充的首次进游戏截图显示：金钱 5000，粮食/木材/铁矿/点券为 0；物语点 25、内政点 25、战斗点 100，等级 1/5。
原 beginning_equipment.common 的资源值、playerLevel 第 1 行的 MP/PP/BP 与截图一致；47 个国家行的五种资源均为 0。
原代码主动忽略 common.gold，注释将这笔初始金钱解释成任务 1 奖励；该判断现已纠正。

仅在 _create_player 创建角色时按 common 行设置资源，不在 _default_state 的读档合并路径发放。
重复 createPlayer、重登、读取旧零余额都不会再领 5000。原任务奖励和教程奖励仍按各自原表及领取记录独立结算，不能用初始金钱抵扣它们。
截图文件散列、逐项读数与原表散列记录在 source-proof.json 的 new_player_baseline；图片本体不入库。
新增回归验证及 HTTP 临时新号验证均在任何任务/教程领奖之前检查上述资源与点数。

## 验证与运行状态

- 本机 218 项测试通过，覆盖原道路免费规则、坐标与整片占地、整笔失败、库存实例持久化、逐级费用/经验、三种升级回包、并发不能重复消费同一份经验。
- 原表 gameplay/progression 冒烟检查保留；新增 HTTP 城市检查在随机临时账号运行并清理。
- 服务端部署结果见 deployment.json；原有玩家存档、现有 mission_chain 补丁和资源表须按部署记录核对。
- Unity 真机画面与流程尚未验收。对本 stub 跑客户端只能确认协议兼容，不能证明自写收益公式就是原服公式。
- 原先 10 个资源文件和 combo/strategy_battlefield 两张表未由本批修复；`stub has no assets` 与 `no stub response` 继续区分。

复现：`python tools/audit_city_tables.py --table-dir <原表目录>`；
`python tools/endpoint_progress.py --out docs/analysis/city-contract-20261115`。
后续优先补查原版道路收益说明/脚本与生产结算调用，按有路/无路、移动道路、不同建筑等级分组采集证据，不能先以随机数填平缺口。
