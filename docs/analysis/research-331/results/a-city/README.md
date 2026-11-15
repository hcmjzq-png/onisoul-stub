# A 组：开工持久化、支城准入与背景适配

固定基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`，分支
`feature/research331-a-city-20261115`。仅修改 A 授权路径；未部署、未启动 Unity、未改玩家数据。
29 项归属见 [endpoints.tsv](endpoints.tsv)，不包含旧分组的出售入口。

**结果：新增可执行的田地开工组件、支城条件校验及四入口背景适配；收获闭环仍未打通。**
正式注册保持 402 / 71 / 331，没有用缺公式的成功回包减少占位计数。

| 验收口径 | 本轮结果 |
| --- | --- |
| 资料增补覆盖 | 7 个入口：两个开工、四个背景、switchMap 的解锁条件；不声称 29 项全部新复核 |
| 可直接正式接入的完整闭环 | 0 |
| 条件化组件链 | 田地开工→到期→重登；背景在显式测试前提下购买→选择→重登投影 |
| 正式注册减少 | 0 |
| Unity 验收 | 0 |

## 原代码与外部资料的交叉结果

1. **支城条件 verified。** 原 `politicMission.po_mission_00281` 的 index 是 **306**，
   `bootCheckFunc=player_level, bootCheckData=["15"]`；两个完成组分别是
   `storyQuestClear(2,5,10) >= 1` 与 `getKokudaka >= 7500`，关闭解锁 `unlockChangeMap`。
   `PoliticMissionConditionOne.cs:268-280` 虽解析 target=10，却只检查**第 2 篇第 5 话完成标志**，
   不能用“第十章已走到最后一步”代替整话完成。原文本 `POM_MES_000281_01_003`
   指明京都美妃第五话，`_03_004` 指明 **40×40 且仍有未开拓土地**。
   `UserStatus.cs:1359` 明确支城部署键 `map1`，不能别名到已有主城内部键 `map001`。
   [2013 年国际中文版公告转载](https://n.yam.com/Article/20130527512911)正文仍是
   25 级、龙虎机突、30000，证明旧版差异，不能覆盖 20140712 原包。
   [2014 年 5 月报道](https://gnn.gamer.com.tw/detail.php?sn=96690)检索出现 15/7500/京都美妃，
   但正文 403，仅记为时间匹配线索，不冒称已读全文。

2. **道路影响田地已确认；精确结算仍 hypothesis。** 原教程、用户确认、
   [2014 玩家投稿](https://gwz.yeyou.com/news/08192014/101521036.shtml?_platform=PC)
   一致支持资源生产受道路影响。投稿给出的基础 20%、一格道路及经验加成只作为跨版本线索。
   它不区分贴边/贴角、取整及加成取样时点，不能得到可检验的唯一产出公式。
   [2012 论坛](https://forum.gamer.com.tw/C.php?bsn=22241&snA=697)正文 403，搜索摘录的
   技能任意内政位置说法与原包 `skill1_10041_01/10042_01` 的位置条件有冲突：原文本限定
   城代/水上，表有 `multiple=false, group=10041, priorityInGroup=1/2`。
   这支持“不能简单重复累加”，不证明具体择优算法。未写死 1.2、1.3 或 1.5 收获倍率。

3. **开工成本/PP verified，服务端时钟安排 compatibility-policy。**
   `PoliticBuilding.cs:1117-1131,1872-1884` 表明手动开工支付配方成本及 1 PP；
   原费用沿用 float32 乘 costRatio 后截断。单体回调读 dueTime/now；批量回调读
   producings 的 productId/createdTime/dueTime。没有内政编队修正时，本组件明确采用
   `floor(server_time)+product.dueInterval`，这是按原显示时长排程的兼容策略，非原服抓包。
   [2012 正式版实录](https://game.watch.impress.co.jp/docs/news/568916.html)亦记录生产与收获消耗内政点，
   仅补玩家可观察行为，不用它推算现代版本费用。

4. **重试消费者链 verified。** `PoliticFSMCollectiveProduce.cs:100` 在成功回调里调用
   payoutCosts；重复成功即可能再次扣客户端显示资源。因此已有任务重复请求返回 errorReason，
   不重放成功。`GameRestarter.cs:64,70-90` 安装错误过滤，`WebApiClient.cs:324-339`
   在回调前过滤 errorReason；不能仅凭 succeeded=false 推断 UI 行为。失败后需权威重读，
   原客户端会进入错误恢复流程，真机体验仍待验收。

## 已实现与未实现

`app/business/city_production_services.py:128` 的 `ManualProductionServices` 只支持原 G1 田地
`building200_041_01_01_1_1` 的两个普通配方；无武将/装备/战术修正、无限耐久、主城已部署且空闲。

| 原配方 | 开工费用 | 原显示时长 | 原解锁级别 | 收获状态 |
| --- | --- | --- | --- | --- |
| product060_023_01_01_1_1 | gold 0 + PP 1 | 10 秒 | 1 | 未实现；13..17 食物为预览范围，不能称真实产出 |
| product060_001_01_01_1_1 | gold 10 + PP 1 | 900 秒 | 5 | 未实现；奖励原行留在样本中，不发奖 |

验证整批后在一次保存中扣费、写 produce 和 building.status；重登可由既有 getMapData 回读。
到期不凭空发资源/玩家经验/建筑经验，不扣无限耐久；保留地图道路，没有以“田地不受道路影响”绕过问题。
重复和混合冲突整批失败。由于没有收获结算，**这两个开工入口必须保持未挂载**。
finite、自动续产、技能叠加、取消退款、加速、好友业务均未实现。

`app/business/city_background_services.py:37` 从原任务编译支城条件；`:91` 统一四个背景入口。
复用只读 D 购买方法，未改 `economy_shop_services.py`。新适配拒绝裸 bool 提供者；
需要同一玩家快照的 `SubcityFacts`、任务 306=C、可信已存在的 map1/40×40 地图。
验证成功保存内部准入收据，之后石高下降不会撤销已开放权益；任一购买/选择失败则不保存收据。
items 归属、mapBackgrounds["1"] 选择和余额一起保存。默认背景/免费赠品/期限不猜测。
完整真实地图和 B/G 事实生产者仍未接入；测试中的地图、等级及任务完成是人工前提，**不是已恢复的支城生产过程**。
旧存档只有 unlockBits 或 C 不直接发权益；需重新核验，或由总集成完成可信迁移。

conflateBuilding 已补读库存素材选择、回包及进化材料读取器；结果等级/经验/有限耐久继承等
仍无法定论，未通过默认重置制造另一套经济规则。其余入口沿用既有协议证据并逐项列缺口。

## 验证

- 本轮 15 项测试通过；全量 **432 项通过，0 跳过**。
- 16 并发开工仅一次成功和扣费；购买并发仅一次扣款。保存冲突不部分写入。
- 覆盖原 10/900 秒、费用、重登、到期不自动发奖、混合建造收获拒绝、缺资产/坏引用分类，
  以及支城阈值、错账号、裸 True、缺地图、坏收据、购买/选择/重登投影。
- 31 行原表小样本、12 个原源码文件和 5 段容器文本的来源与散列见
  [source-proof.json](source-proof.json)，复现命令见 [integration-notes.md](integration-notes.md)。
- 未做真实数据库多进程故障测试；保存冲突是隔离注入。未部署、未测 Unity、未修改本机/局域网路由。

道路/技能精确结算、支城原始地块与默认背景，是当前真实阻塞；对应区分实验见
[capture-plan.md](capture-plan.md)。外部攻略不能替代缺失 AssetBundle。
