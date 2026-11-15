# 生产收获深入复核（PR #40 追加）

本次从原 C#、662 张原表及原 tableAssets.bin 继续取证。源路径、散列、方法/行号、
原文本字节偏移和完整计数见 harvest-evidence.json。只新增纯规则函数及离线审计脚本；
**未启用开工/收获/取消/加速 HTTP 入口，未改 completeTasks 建造功能，未部署。**

## 奖励：三类经验/报酬不能混为一笔

田地首配方 product060_023_01_01_1_1 的原记录是：

| 来源 | 原值 | 可证明的含义 |
| --- | --- | --- |
| reward01_01_00001_01 槽 1 | A；ratio=1..1；food item11_0000301；count=13..17 | 原奖励槽元数据；菜单按建筑 grade/level 插值，不能当最终粮食结算 |
| 同奖励槽 2 | B；ratio=1..1；item11_0000501；count=2..2 | StateAutoProduce.payout → PoliticGainResourceExp.getGainResource → UserStatus.addExpValue：玩家经验 |
| product.buildingExp | 10 | 原表存在；未找到客户端读取该字段并计算收获建筑经验的逻辑，不能仅凭名字执行 exp += 10 |
| 回包 producings.<id>.building.exp | 绝对数值 | PoliticBuildingParameter.set 覆盖建筑经验，不是增量 |
| 回包 producings.<id>.collaborator.<id>.exp | 绝对数值 | StateAutoProduce:419-430 覆盖协作者建筑经验；不是好友玩家经验 |

原教程 POM_MES_000033_01_001 说明收获积累建筑经验；POM_MES_000089_03_002 和
POM_MES_000220_01_001 说明城的收获给农家/长屋/商家积累经验，与 collaborator 机制相符。
它们不提供分配比例、适用建筑范围或技能叠加次序。

RewardTableAccessor.getReward 是**读取器**，不是抽样器。ratioMin/ratioMax 为非数字时按 0，
两个 ratio 都为 0 时槽不生效，即使该槽还有 item/count。不能从字符串 "1" 强制转换出有效奖励。
读取 group A/B 不证明“每组随机一个”，固定 ratio 1..1 也不能直接当 100% 发放证明。
HTMLTreasureMediator 的比值只用于宝箱展示，不是生产结算算法。

对 1,288 个配方逐行检查：

- 1,280 个能解析原奖励引用；另 8 个都引用同一缺行 reward01_02_00027_01，**不是 8 个资源文件缺失**。
- 625 个有同组多个有效槽；588 个数量上下界不同；304 个 ratio 上下界不同（计数可重叠）。
- 已解析配方中 599 个含玩家经验物品；1,280 个有 buildingExp 字段。
- 1,288 个配方无 gainTypes/gainAmounts。ProductsTableAccessor.getGain 无外部文本调用，
  不能调用它并将缺字段解释为“没有奖励”。

## 耐久：无限标记已证实，有限次数的提交时点未证实

defines.infinite_building_durability.value=10001；PoliticBuildingParameter.IsInfiniteDurability
做的是**相等**比较，IsDead 是 <=0。PopUpBuildingIcon 用此判断显示无限还是剩余次数。
原 1,343 建筑中 797 行为无限；546 行有限（主要为 3 次，另有 1/2/4/5/6/10/20/30/40/100）。
田地为 10001，金山 building200_031_01_01_1_1 为 10。

教程 POM_MES_000273_03_001/002 明确有限/无限两种类型、田地可持续生产、金山只能收获数次、
剩余 0 时自动消失。**仍未证明耐久在开工、到时或收获事务中哪个时点递减，以及取消是否扣次。**
因此函数只识别 finite/infinite/dead，不做 `durability -= 1`，也不把客户端默认 10001 补入缺失存档。

完整回调链：StateAutoProduce.onComplite 先检查 autoProducings（此时还是旧耐久），再调用
onCompliteProducings，用 building 更新新耐久；最后按新耐久决定状态。
PoliticBuilding.processDead:549-568 在奖励动画结束后清格子并移除建筑。
未来最后一次收获不能只发 reward 而漏掉 building.durability=0；存档删除建筑、清占格、
不续产、计数更新与奖励必须同一次提交。此处是集成要求，不是本次已实现的状态事务。

## 道路：显示连接不是收益邻接

追到 PoliticRoadChecker → PoliticConnectBase.addRoad/getChipId/searchRoad：八方向位标记
用于道路贴图连接、桥方向和行人路径。调用方是 PoliticFields/PoliticPeople 等显示组件。
未找到它们进入奖励或生产数量计算的调用链。因此不能照搬“八邻接”给生产加成。

原教程与 TIPS_MSG_17 仍只证明邻接道路会增产。除已有 5%..50% 技能外，本轮还定位
SKILL_MSG_1_11058_01_DESC（道路影响+50%，额外兵法书机率+50%）及
SKILL_MSG_1_11064_01_DESC（道路影响+10%，额外兵法书机率+20%）。
同一技能可同时改变道路影响和额外奖励，不能把最终差额全部归因于道路。
skill 行只提供描述键、发动条件/组等；未证明基础倍率、贴边/贴角、连城堡要求、多路叠加、
取样时点和乘加/舍入顺序。没有实现任何道路倍率，也未用“无路”假设绕过其他结算缺口。

## 可落实的计算及新的数值风险

app/business/city_production_rules.py 的函数均无存档写入、无接口注册：

- production_costs：原 PoliticBuilding.getProductCosts 与 PluginPoliticDataReader 同为
  float32(amount) × float32(costRatio)，结果再截断。不能复用建筑升级费用的千分位舍入函数。
  **原案例** building200_036_02_01_1_1、Lv3、product_store2003：3800 × 1.015，
  客户端 float32 得 3857；直接 Python float64 再 int 得 3856，会少扣 1。已加原样本回归。
- preview_amount：复制 UserStatus.calcAmount 的逐步 float32 运算，只供普通数量预览；
  不支持 item15 的伤害值分支，不称为最终发放数。
- reward_slot：读取有效槽元数据，保留原 group/ratio/count，不抽样也不发奖。
- durability_kind：精确识别无限标记和死亡边界，不递减次数。
- harvest_display_point_cost：自动收获与原包插件的成功回调一致：单个 1 PP，多于一个取
  politic_auto_harvest_point=10，非“每栋 1 PP”或“每栋 10 PP”。只提取显示扣减规则，
  不用于建造混合批次；未处理服务器余额不足策略，不接入共享 completeTasks。

2,183 行 building_level 的 intervalRatio 全为 1，但 LevelUpTableAccessor.getIntervalRatio
读取的是大写 IntervalRatio；getGainRatio 读取的 gainRatio 在这 2,183 行也均不存在。
两方法未找到外部文本调用。**不能靠这些死访问器虚构时长/收益修正。**
costRatio 则有实际调用，102 行不是 1。

## 验证和下一份必要证据

9 项新规则测试通过；加上原 A 组 12 项共 21 项；完整回归 247 项通过、0 跳过。
审计脚本逐行校验小样本等于原表，并重建本报告的计数，未修改任何输入文件：

```powershell
python -m unittest tests.test_city_production_rules tests.test_city_production_services -v
python -m unittest discover -s tests -v
python docs/analysis/parallel-342/a-city-production/city_production_audit.py --source C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115 --tables D:\onisoul\work\quest-contract-20261115\all-tables --container D:\onisoul\work\quest-contract-20261115\tableAssets.bin --output docs/analysis/parallel-342/a-city-production/harvest-evidence.json
```

总集成的独占取证优先抓完整原始回包与前后存档：

1. 无路无技能田地 Lv1，开工→到时→收获→重登，分别核对粮食、玩家 exp、building.exp、
   durability、PP、collaborator；同配方 Lv10 区分预览与实际结算。
2. 金山 10→9 与最后 1→0；开工后取消、到时但未收获时重登，确定扣次时点及删除事务。
3. 固定同建筑等级、技能编队、配方、布局采样时点，仅改变无路/贴边/贴角/多路/道路连城堡；
   再单独加道路技能。每次记录所有 reward 槽，不只看主资源。
4. 自动续产收获响应丢失后重试，以及紧接下一代任务已到时的延迟重试。
   buildingIds 无代次参数，不能简单按 ID 删除当前任务或重放旧奖励造成重复客户端加法。

只有可信原服/归档或可验证原结算实现能证明这些规则；本模拟服自产回包不能反证原规则。
