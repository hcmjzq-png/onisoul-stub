# 生产链契约复核

基线：PR #38 合并后的 `9055fa4`，402 个入口、59 个专用处理器、343 个占位。
本批深入跟踪生产链 6 个入口（completeTasks 已有建造处理器），新增 **1 个配方查询处理器**。
现在 60 个专用入口、**342 个占位**；四个阻止假成功的入口仍计为占位。没有声称分析完全部 343 个接口。

## 新证据

- **配方解锁按玩家等级。** 原安装包 `PluginManualProduce.cs:105-113` 比较 product.openLevel 与 UserStatus.getLevelValue；`UserStatus.cs:1212-1215` 返回玩家等级。证据来自原包附带的自动操作插件，不是旧 AI 实现或原服抓包。原 1,288 条 product.openMission 全为字符串 `"null"`；非空任务门槛尚无行为证据。
- **菜单基础数量按建筑等级插值。** `ProductItem.cs:98-102` 将 grade、building level、第一奖励项 countMin/countMax 传入 `UserStatus.cs:1735-1740`：`floor(min + (level - 1) * (max - min) / (grade * 10 - 1))`，中间运算为 float32。G1 田地首配方预览，建筑 Lv1 为 13 粮食、Lv10 为 17；item15 类改用伤害值。这是菜单预览，不是完整服务端结算，不证明所有奖励槽/技能均用同一公式。
- **道路和技能另有影响。** 教程 POM_MES_000006_03_001、TIPS_MSG_17 确认邻接道路提高生产量；SKILL_MSG_1_10041..10050 描述道路影响提高 5%..50%，限城代/水上且不可重复发动。这些技能百分比不能作为无技能时的道路基础倍率。原文偏移与 SHA-256 见 source-proof.json。
- **失败需要 errorReason。** `GameRestarter.cs:61-94` 注册错误过滤器并检查 errorReason；`WebApiClient.cs:324-333` 过滤失败后不执行业务回调。只设 succeeded=false 仍可能运行成功回调。错误会进入通用错误/重连流程；尚未验收真实 Unity 表现，也未声称能就地回滚客户端提前扣减的显示值。

## 服务端改动

| 入口 | 本批范围 / 原消费者 |
| --- | --- |
| politic/building/getProductsByBuilding | 查询账号主城建筑的原 products，按玩家等级筛选，返回 products 的键。WebApiClient.cs:973-979 请求数值 buildingId；PoliticFSMProduct.cs:608-616,652-659、ProductUpdate.cs:121-144 消费。值用空对象是兼容选择，原服值未证实。level/buildingTypeId 由客户端 Add，服务端不预填。缺表/缺行报 stub has no assets；未知 openMission 拒绝。 |
| politic/task/submitProduceTask | 仍未实现；带 errorReason 明确失败，阻止虚假 dueTime 启动计时。StateManualProduce.cs:51-66 → PoliticBuildingParameter.cs:172-182。 |
| politic/task/submitBulkProduceTasks | 仍未实现；阻止空成功后客户端扣费用/更新任务。PoliticFSMCollectiveProduce.cs:98-125 读 producings.<buildingId>，含 productId/createdTime/dueTime。 |
| politic/task/cancelTasks | 仍未实现；取消、退款与耐久规则未知，明确失败，不触碰存档。 |
| politic/task/accelerateProduceTask | 仍未实现；PoliticBuilding.cs:702-730 读 producings.<id> 并更新任务，不能回空表假成功。 |
| politic/task/completeTasks | 保留建造完成；请求包含 produce 记录或 producing 建筑时整批先拒绝，避免混合批次部分完成。StateManualProduce.onComplite 会清除客户端任务；StateAutoProduce.cs:401-430 要求 reward/building/collaborator。 |

主城限定是模拟服支持范围，不推断支城行为。查询不创建任务、不扣钱、不发奖。
四个拒绝入口保留 placeholders 模块归属，不计作完成。

## 未决规则与静态边界

- 道路基础倍率、边/角相邻、是否连接城堡、多路叠加、布局取样时点，以及技能/协作者结算顺序。
- 生产耗时、奖励组选取、全槽位数量、经验/耐久、自动循环、任务计数、取消退款和加速上限。
- 生产生命周期与收获幂等须一起完成；本批不开放能扣费却不能正确收获的生产任务。

复核原 1,343 建筑、1,288 配方、2,183 建筑等级行；见 table-audit.json、product-dependencies.tsv。
仍有 588 条数量上下界不同、625 条奖励选择规则待核实（可重叠），8 条缺奖励行、3 个建筑缺初始等级行。
这些是静态引用，不计为新增资源文件缺失；此前 10 个请求资源和 combo/strategy_battlefield 两张表未由本批解决。

附带检查 usePotions 和背景查询/购买消费者，尚未实现：药水半恢复的舍入/超上限、背景归属和商城开放范围还缺规则；不计入本批六个深入追踪入口。
后续动态取证应比较同配方/同级田地在无路、贴边、仅贴角、多路、带技能时的原始回包与前后状态。
本模拟服日志只能证明本模拟服行为，不能用自己生成的数值反过来证明原版倍率。

## 验证

本地 226 项测试通过。新增 8 项覆盖等级区分、查询不改档、认证/归属/参数、缺表/缺行、未知任务门槛、
四拒绝入口仍属占位、混合批次原子拒绝、缺任务但 producing 状态保护。
服务器已部署 `ad3549d`：226 项中 223 通过、3 项因缺少可选 IL 分析依赖跳过；这 3 项在本地通过。
经 80 代理端口完成隔离账号注册/登录/建造/升级/配方查询和四接口无写入检查，测试账号已清理。
6 个既有玩家存档散列不变，mission_chain.py 旧补丁和全部表文件保持不变，proxy 未重启。
结果见 deployment-result.json；代码/数据库备份为 `/var/backups/onisoul/production-contract-20261115-ad3549d`。
真实 Unity 操作未验收；HTTP 验证不能替代画面验收。
