# C 组：卡牌成长、抽签、九宫格与道具

基线 `8023c3fee8e525040d101fee8bf843b48b3256d3`；分支
`feature/research331-c-card-growth-20261115`；工作树
`D:/onisoul-worktrees/research-331-c-card-growth`。开始时干净，只改 C 授权文件。
当前任务是 30 项，未把旧 342 分组的销售/查魂三项重新算入。

本轮补充 **10 项端点证据**，实现 **1 条有限道具事务闭环（2 个候选 API）**，
修正战术出售重复成功的客户端增量问题。**无条件可公开接入闭环 0、正式注册减少 0、
Unity 验收 0**。正常 `build_registry()` 仍为 402 总数、71 专用、331 占位。
有完整业务操作和注册路径测试，不仅是查询/helper；但可信传输操作身份尚未接入，
不能把隔离测试的 context 提供者当线上能力。

## 已实现和未实现

`CardGrowthServices.register_mutations` 提供候选注册；必须显式注入可信
`OperationContext` 提供者，正常注册不调用它。每个 context 绑定认证玩家、API、
一次用户意图的稳定身份和请求摘要；摘要只校验请求绑定，**不是去重键**。

1. `politic/support_item/useDopingItem`：已有携带武将、已有普通能力石，
   按 `potion.uses/effects/itemID` 同时扣库存、更新对应总属性和 `atkAdd/defAdd/intAdd`。
   仅原 UI 20 种石、1/5/10 个完整批次；批次任一属性越过 `characterLevel.cap` 整笔拒绝，
   不猜自动减少用量/截断/返余的算法。不改等级、经验、技能，也无额外金币扣费。
2. `politic/support_item/useDopingRemoveItem`：消费 `potion0000201` 一枚拆除铃，
   从三项总属性减去对应 Add 并清零；严格按原预览的降序贪心拆分返**单属性石**。
   例如三项 Add 各 50，分别返 40+10，不能返神石 5 颗。非完整表示的余数、
   负值/坏档、返还库存超 Int32、无可拆增量全部拒绝，不丢余数、不自动进信箱。
3. 两项均保守拒绝保护、头像、六种编队引用、仓库卡、携带/仓库重复实例。
   这是本服支持范围，**不是声称原版禁止给保护/编队卡用道具**。
4. `deck/sellTactics`：旧账本保留，已提交的相同 operation_id 改为 `errorReason`，
   不再次返回 `sellPrice/tactics` 成功增量；新身份允许合法同参数第二次出售。
   旧报告只读保留，以本轮修正替代其中“重放成功负载”的实现结论。

业务变更与收据在同一玩家文档 CAS 中保存；没有跨库/分步写入。保存冲突不提交收据；
提交后丢包重试拒绝，重启或补货后旧请求仍不再消费。收据上限 1024 是本服支持限制，
到限拒绝新操作、不淘汰旧收据。详细身份来源和显示策略见 [integration-notes.md](integration-notes.md)。

闭环测试从已有可信石库存开始，使用正式普通商店处理器按原 `shop0700013.credit=150`
购买拆除铃（不是 `costAmounts=300`），查询 → 使用神石 → 拆除/返还 → 重登回读。
测试初始库存/credit 是明确的隔离场景，不是新增赠送/充值/掉落业务；真实新玩家仍为
5000 金钱、其他资源 0。没有实现石头的战斗掉落、拍卖锁和付款渠道。

## 本轮新证据与排除的猜测

- `ConflateItem.cs:96-147` 用**总属性**与等级 cap 比较，不能把 cap 当成 Add 单独上限；
  `CharacterStatus.cs:176-182` 分开读总属性和 Add。
  `DeckUseItem_confimation.cs:70-136` 可验证拆石预览的排序、除法与余数；本服仅支持无余数情形。
- 普通公开 HTTP 请求成功读到 S8、S4、石头讨论和两篇 GNN 正文，均为 HTTP 200。
  网页工具先前返回 403 仍记入证据；未把搜索摘要冒充正文。
  [2012 年玩家直接报告](https://forum.gamer.com.tw/C.php?bsn=22241&snA=677)
  的五档增量与本包 20 个 potion 原行一致；年代/服别差异不被隐藏。
- [S4 新手指南](https://forum.gamer.com.tw/Co.php?bsn=22241&sn=4031) 标题虽写
  2014/05/06，实际正文编辑到 **2014-11-19**，混合台日版本。G4 进化所举
  80/50/35 与本包 `characterGrade.4.gradeMin3/2/1` 相符，只确认 UI 所显示概率。
- `DeckConflate_Evo.cs:388-395` 直接读 gradeMin；`DeckConflate.cs:331-345` 显示
  `min(基础+道具+额外,100)`。[S8](https://forum.gamer.com.tw/Co.php?bPage=0&bsn=22241&sn=18669&subbsn=1)
  对付费继承的描述是失败保护，不能写成必成。`DeckConflate_Skill.cs:475-517`
  还检查 inheritFlag/class/grade/conditions。显示概率不是完整结算、技能赋值或失败补偿算法。
- 强化预览 `DeckConflate_Conflate.cs:144-184` 有经验系数、费用、逐级经验扣除，
  回调另外读 powerUpRank。仍缺原服 rank 分布、倍率及活动生效条件，不以预览冒充随机结算。
- 已重读现在可加载的 G2/G4/G6 原表，分别 200/235/158 行；rate 总和为
  1831/1641/1405，rate_credit 总和为 1657/1529/1060。
  不能直接当作全表互斥抽取的逐行百分比；也不能仅因此证明是全表归一化权重。筛选、保底、重复技能、
  learning/visible/经验迁移仍未知。三表现已恢复，旧“导出缺失”不是本轮阻塞。
- [2014-06-10 公告](https://gnn.gamer.com.tw/detail.php?sn=98372) 有一次到顶的钻石，
  但原 potion.doping 仅 20 种普通石，未找到该钻石可用匹配。
  不因公告比安装包早而虚构物品 ID，普通石不升级成钻石。
- `GameRestarter.cs:70-95` 拦截 errorReason；`WebApiClient.cs:324-337` 在过滤后才进入
  成功回调。这支持重复请求失败后重登的本服策略；不是无感重试或原服幂等协议。

## 九宫格三项统一归属

`getNineGridInfo/playNineGridGacha/claimReward` 均由 C 记录，没有挂载其中任意一项。
原八线几何已在 `card_growth_ninegrid.py` 落地，并枚举 512 个棋盘核对。
这只是几何，**不算九宫格业务闭环**。

[2013-11-19 厂商原文](https://gnn.gamer.com.tw/detail.php?sn=88819) 说明三卡成线、
按线数领奖，同时排除挂卖/鬼签来源。库存有同卡并不足以建立资格；这项历史条件
与目标版本的具体获卡来源映射仍须复核。GamerSky 是同文转载，不算第二份独立佐证。

原请求 claimReward 传 `reward` 字符串，**不是成就 category**；
`NineGridCollectionRewards.cs:63-80` 比较 condition 与完成线数；
`NineGridDataManager.cs:133-150` 只处理新近从未领变已领的第一项。
`NineGridGacha.cs:67-90` 以 played_gacha_times 索引服务端 gacha_cost，用 credit 判断费用，
`GenerateIndices` 的随机仅用于动画，不能据此恢复服务器抽取分布。
`NineGridDataManager.GenFake*` 含假奖励和假费用，**全部排除为生产配置**。

活动、来源权益、抽取结果和领奖账本的设计/重试要求见接入说明；没有可信事件生产者或
可核实配置前，不发布抽取资格、不造奖、不凭历史公告复活活动。

## 验证

```powershell
python -m unittest tests.test_research331_c_items tests.test_card_growth_services -q
python -W ignore::ResourceWarning -m unittest discover -s tests -q
python docs/analysis/research-331/results/c-card-growth/reproduce.py --table-dir D:/onisoul/work/verified-trophies-20261115/runtime-tables
git diff --check
git apply --check docs/analysis/research-331/results/c-card-growth/integration.patch
```

本组 **43 项**；全量 **434 项通过，0 跳过**。37 个源文件散列及 3 份原行 fixture
（25 行）校验通过；完整原表内存 smoke 通过；普通注册保持 331 占位。
覆盖请求身份绑定、同参数新意图、补货/变价后旧请求、并发同身份单胜、双实例 CAS、
保存失败回滚、道具/金币精确余额、cap 等值、保护/所有编队、拆石余数/库存溢出及重登。
`ResourceWarning` 抑制参数沿用基线命令，不忽略测试失败。

未部署、未改 hosts/proxy80/config.ini、未访问生产玩家或数据库、未启动 Unity。
真实 MySQL 多进程适配与原客户端画面仍待 I/总集成串行验收。
缺表文件/不能加载：`stub has no assets`；规则未恢复、坏引用/不支持边界：`no stub response`。
既有十个缺资源请求和两张缺表不在本次修复范围。

完整 30 项状态见 [endpoints.tsv](endpoints.tsv)；来源/版本/可信度/冲突见
[external-evidence.json](external-evidence.json)；后续实测见 [capture-plan.md](capture-plan.md)。
