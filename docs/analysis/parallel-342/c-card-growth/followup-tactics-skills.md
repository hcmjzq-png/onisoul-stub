# 战术出售、技能换币与技能槽追加复核

本次优先深入这三项；其余25项继续保留 reviewed-endpoints.tsv 的原有待证状态，
不宣称它们已完成第二轮深入追踪。未改共享文件、未部署、未启动客户端。

## 战术出售

原链：WebApiClient.cs:1305-1311 → DeckSale_Tactics.cs:307-368 →
DeckSaleTacticsObj.cs:57-66,86-106 → TacticsTableAccessor.cs:181-188。
请求是 tactics.<基础战术ID>=数量；TacticsStatus.cs:29-37 直接以该ID查表，不是武将实例ID。
最多8种，种类内可选多张，不能把“8种”错写成“总计8张”。
原595行战术表的sellPrice为售价来源；小样本两行分别为10、20。
回包 sellPrice 是金币增量，tactics.<id> 是**售出数量**，回调按其从当前余额减去。

WebApiClient.sendRequest:190-217 在网络错误时最多尝试10次，重复相同form；
_httpCall:247-273 的httpCallId只用于本地请求列表，没有放进表单。
RpcQueue.reliable只排队，并不提供服务端幂等标识。
因此“相同参数永久去重”会吞掉合法第二次出售，“每次随机ID”又会重复扣量。

新增 sell_tactics_with_receipt 是**仅供可信总集成调用的事务入口**，没有直接注册HTTP：

- 认证玩家、1–8种、正整数数量，检查全部余额及原表售价；拒绝编队引用和金币溢出。
- 原记录只更新amount，保留零余额行；扣量、金币、内部收据在一次玩家文档保存内提交。
- 玩家内 operation_id 相同且数量相同则回放原业务负载，不再次结算；数量不同则失败。
- 重启/重登、库存重新获得、表价变化后仍可重放旧收据；新意图使用新ID可正常再次出售。
- 去重账本不按时间淘汰；达到1024条先拒绝新交易，旧收据仍可读。此上限是本服支持策略。

operation_id、cardGrowthTacticSales和保守编队限制均为本服内部设计，不是原协议。
缺少可信上游操作身份之前，不能将本方法包装成公开路由；**不计新增已完成接口**。
需D组对接挂牌库存锁，需总集成解决长期收据归档；没有跨账号交易。

## 技能换币

WebApiClient.cs:4554-4560 请求只含token、characterIds；没有目标武将、等级、兑换数量或兑换率。
DeckConflate_SkillRefresh.cs:215-274 校验客户端选中的素材不含根卡，回调验证characterIds并
删除素材，以skillCoins设置最终余额；重登时DeckScene.cs:244-253从getDecks重读该值。

同类105-171仍有强化预览MaterialPoint、power_up_exp_coef、moneyCost_等代码，
但setSkillcoins回调没有用它们作为兑换率或扣金费用。也未在已审阅character/defines/grade/level
表中找到与换币率连通的读取链，不能拿“有数值字段”代替证明。
原deckMessage文本资产312行没有DECK_MSG_CONFIRM_ABSORB_CARDS，容器中该完整键也未命中；
这仅限制当前证据，不能称所有原资源都没有说明，更不应误报整个资源文件缺失。
本次未实现换币，不注册空成功或猜测“每卡N币”。

## 技能槽刷新

DeckConflate_SkillRefresh.cs:512-604 证明按钮档位与paymentId映射；
SkillRefreshPaymentTableAccessor.cs:17-35读category/amount：

| 按钮 | 技能币 paymentId / amount | 点券 paymentId / amount |
| --- | --- | --- |
| G2 | slot_0001_1 / 500 | slot_0002_1 / 5 |
| G4 | slot_0001_2 / 900 | slot_0002_2 / 15 |
| G6 | slot_0001_3 / 1500 | slot_0002_3 / 30 |

此处G2/G4/G6来自按钮传入参数，不能直接推断请求武将本身等级就是2/4/6。
响应 result.character/category/amount；amount是支付后余额，character为更新记录。

验证原容器 SHA-256 `20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7`，
按TextAsset名称长度、脚本长度、JSON根完整校验，定位三张尚未导出的表：

| 根名 | 行数 | (rate, rate_credit)与行数 | 所有ID能否在skill表找到 |
| --- | --- | --- | --- |
| skillRefreshG2 | 200 | (1,1)×29；(4,6)×128；(30,20)×43 | 是 |
| skillRefreshG4 | 235 | (1,1)×33；(2,4)×159；(30,20)×43 | 是 |
| skillRefreshG6 | 158 | (1,1)×30；(1,2)×85；(30,20)×43 | 是 |

既有table_inventory.tsv已记载三表；本次补足原容器偏移、原字节散列、行引用及非均匀分布。
三个候选表的原文件存在，缺少all-tables导出不是stub资源文件丢失。
没有C#访问器/抽样消费者证据证明rate如何归一化、如何过滤候选、重复/继承条件如何处理，
也没证明替换槽与技能经验/learning/visible的赋值规则。因此不生成技能、不扣费，
更不能为了通过回调而返回未变化的character。

## 复核与测试

```powershell
python docs/analysis/parallel-342/c-card-growth/card_growth_followup_audit.py
python -m unittest tests.test_card_growth_services -v
python -m unittest discover -s tests -v
```

审计脚本默认只读；--write仅重建本组证据与少量原行样本，不改原表或原包。
本组26项、完整252项通过，零跳过；本次12项覆盖战术部分/多类出售、客户端扣量语义、
重登收据、补货/变价后的重试、新意图、ID冲突、认证/账号隔离、数量不足、编队引用、
溢出、缺表/缺行、同实例并发、双实例CAS及失败回滚、账本满额与未挂HTTP。
双实例测试使用隔离内存CAS；没有将其说成真实数据库或Unity验收。
