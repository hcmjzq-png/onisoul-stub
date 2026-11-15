# D：交易、拍卖、国技与国家商城

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`；分支 `feature/research331-d-economy-20261115`。
只修改 D 授权的新模块、测试和本目录。37 项逐项清单见 [endpoints.tsv](endpoints.tsv)。
背景方法及 `subcity_enabled` 完全未改，国家商城沿用既有组件，没有伪造国力、周期或充值。

本轮交付两个**未正式挂载**的组件流程：主城首趟旅交易、资源拍卖托管交割。
没有完成全部 37 项玩法，也没有把测试选择器、内存事务或合成费率接到正式服务。

## 新证据与排除的猜测

1. 对原 `tableAssets.bin` 重新核验 SHA-256 后，按 TextAsset 名称长度、脚本长度、JSON 根提取审计
   28 张交易相关表（其中 `errantry` 是已有表）。原目录只有 `errantry`，其余 27 张未导出；
   它们在原包中存在，不能继续写成原资产丢失。
   本次只提交元数据、散列和小样本，没有提交完整原表或修改公共提取器。
   [source-evidence.json](source-evidence.json)、[build_evidence.py](build_evidence.py) 可复核。
2. `errantry_result_0001..0012` 各 54 行，`reward07_errantry` 120 行，所有旅交易 rewardId 有对应行。
   `leastIntelligence/intelligenceBias` 存在，但不证明“均匀抽样”“按区间抽样”或概率公式。
   `reward07_0002` 等还含 `group=none/ratioMin=0/ratioMax=100` 的额外奖励；不能无声忽略。
3. `waterborne_trade_result_0003/0004` 合计引用 18 个在 `reward12_waterborne_trade` 中不存在的 rewardId。
   这是**表内引用缺口（no stub response）**；不是所有水运文件都不存在。
   基础水运原行 `trade_00001` 是 7200 秒、10 PP、200000 gold、总智略 3000。
   S4 搜索文本中更早的水运 250000 金钱不能覆盖本安装包。
4. `errantry_00001..00006` 原表费用/时长/智略如下；均扣 10 PP。数据来自原表，不来自搜索摘要。

   | 原行末号 | 秒 | gold | 最低总智略 |
   | --- | ---: | ---: | ---: |
   | 00001 | 900 | 2000 | 1000 |
   | 00002 | 1200 | 5000 | 3000 |
   | 00003 | 1500 | 10000 | 4000 |
   | 00004 | 1800 | 30000 | 5000 |
   | 00005 | 3600 | 100000 | 7500 |
   | 00006 | 10800 | 500000 | 10000 |

5. 外部交叉核对见 [external-evidence.json](external-evidence.json)。
   [2014 年新手攻略](https://gwz.yeyou.com/news/07152014/152905148.shtml) 正文确认旅交易以已编成内政队出发，
   但属于国服栏目，不能证明台服数值。
   [国技调整报道](https://www.gamer.ne.jp/news/201309260070/) 正文明确国别/国技内容影响所需点数，
   与客户端响应 `levelRate` 的动态性质相符；不能填常量 1。
   [挂卖正式版转载](https://www.gamersky.com/news/201311/306680.shtml) 记录 2013-11-12 调整为玩家 20 级、卡 G2，
   是 GNN 同一原文的转载，不算独立佐证。GNN 原页本次 403，15 级早期公告只作版本冲突线索。
   拍卖费率、收入税、邮箱交割、资源等级限制仍未获得足够原版依据。
6. 新发现并修正旧报告漏项：`getStatus3` 回调把同一响应交给旅交易状态和内政队两个消费者。
   `<mapId>` 下还必须有 `politicDeck/totalIntelligence`，否则客户端强转缺失值失败。
   模块已补齐类型校验，缺少可信智略 provider 时返回失败；没有另造 getPoliticDeck 接口。

## 真实代码范围

- `app/business/economy_trade_services.py`：`send3/getStatus3/receive3` 的限定组件。
  从本人地图、建筑、内政卡槽和原表产生记录；先校验再同次保存 PP/gold 扣除及出发记录。
  服务端时间控制到期，重登回读同一记录，领取发放已冻结的结果并增加一次 errantryTimes。
  支持结果中的固定紫魂和技宝珠（后者写 `items[item07_0070001]`，不是 `skillCoins`）。
  结果选择器必须由可信实现注入；客户端 params 中智略、奖励、时间均不作为依据。
  测试选择器明确标记 SYNTHETIC，**不是原概率引擎**。
  没有生产选择器时出发返回 `no stub response`，不扣费。
- 原 send 回调自行减费、receive 回调自行增奖励/次数，所以重复请求返回失败，不重放成功。
  原请求没有已证实的旅次标识；本服保守策略是每玩家主城仅首趟，保留完成墓碑，
  防止上一次 send/receive 的迟到重试误操作下一趟。下一趟、取消、地区城、支城、水运均未开放。
- `app/business/economy_market_services.py`：实际生成市场记录，资源从库存扣出托管；
  查询/搜索快照从这些记录生成；购买同时扣买家 credit、交付资源、记卖家收益、关闭挂牌并写收据；
  撤回归还托管资源；到期隐藏公共挂牌但保留卖家槽位，需领取后才能再用。
  价格/收益固定在挂牌时；同一操作键永不复用，同一挂牌只交割一次。
  I 的 UoW 注入接口已按其工作草稿对齐，但 D 不实现 SQL、不修改 I 工作树。
  无默认费率/门槛/槽数/营业期；测试值不进入生产配置。
  直接入余额、溢出整笔拒绝、手续费不返还、十进制定点取整均为明确兼容策略，未恢复原邮箱规则。

## 测试与计数

2026-11-15：

```powershell
python docs/analysis/research-331/results/d-economy/build_evidence.py
python -m unittest tests.test_research331_d_trade tests.test_research331_d_market tests.test_economy_services -q
python -m unittest discover -s tests -q
```

专项 **53** 项、完整回归 **445** 项通过（无跳过）。新增 28 项覆盖真实原表小样本、扣费和领取边界、
跨服务重建回读、并发出发/领取、跨账号买卖/撤回竞争、保存异常、容量不足、重试收据及客户端增量语义。
既有公共测试有未关闭文件 ResourceWarning，本组未改其文件。
内存 UoW 验证完整提交/回滚契约，不是 InnoDB 集成验收；未运行 Unity，未操作生产数据。

按统一口径：**16 个端点补充部分证据、28 张表审计（27 张此前未导出）；组件涉及 9 个端点；
有条件组件闭环 2；当前可直接正式接入闭环 0；正式注册减少 0；Unity 验收 0。**
国技、国家商城真实周期、付费余额、Npoint、武将拍卖及水运未谎报完成。

接入补丁、状态迁移、I/G/A 依赖见 [integration-notes.md](integration-notes.md)；
串行实机实验见 [capture-plan.md](capture-plan.md)。本组不部署、不合并。
