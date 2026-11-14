# 背景和国家商城追加复核

本轮新增四个独立处理器，保持未挂载、未部署。`shop-evidence.json` 收录源文件散列、
TextAsset 精确偏移、小样本来源和 38 条国家商品逐项审计；此前 39 行清单同步更新。

## 背景：恢复缺漏原表并落实单次购买

只读 `D:\onisoul\work\quest-contract-20261115\tableAssets.bin`，核验 SHA-256
`20b987a41c5ec8f0b70dfe65bf0383c7acf25cc755f38f5b4d9dbdaa361dc4f7` 与既有来源链一致。
按 TextAsset 名称长度、脚本长度、JSON 根验证，直接得到 item13（6 行）与 item14（51 行）。
它们没有出现在之前 662 表导出目录，是提取范围遗漏，不是原包资源缺失。

四个 enabled 商品指向 `item13_0000004/0000005`、`item14_1000048/1000049`，
均 enable=true；类别为 nearground/farground，`parameterId` 对应场景模型。
`value` 被选择页用于排序，**不能解释为期限或发放数量**。
`mypageShopBgWindow` 的价格确认从原表读取 credit，成功后删除商品并更新 resources；
选择页读取物品 ID。限定实现每个物品持有 1 份，写入既有 `player.items`，A 应复用同一来源。

`static_background_sales=True` 是显式模拟服策略：只销售静态 enabled 单物品商品，
按原表 168 credit 扣费；默认 False。已有库存则不扣费、不叠加；查询隐藏已拥有商品。
这些是消费者兼容的购买/重试行为，未声称原服永久许可或恢复其运营排期。
不生成初始免费背景，也不从未发现期限字段推断“原服永不过期”。需要限时背景时必须先
补充生命周期证据和 A 的选择校验；目前实现只支持保留在库存中的背景，不能当作限时销售模块。

## 国家商城：有门槛证据，周期不猜

`national_power_shop_item.goal` 对应 `national_power_goal.incentives`；
`MightOfNationAchievement.updateSetting` 用 `getPower(key) <= power` 判断达成。
shop_01/shop_05=20000、shop_02=50000、shop_03=75000、shop_04=750000、shop_06=1000000。
这是静态奖励门槛和客户端显示证据；当前国力和开放期不是可从表中生成的事实。

`ShopItemNationalPower.saleWindowResult` 对整套传 index=-1，quantity 来自购买窗口；
成功时客户端自行 addDraft。`checkDraftAmount` 上限 99；`checkRemain/setRemain`
以响应 remain 为剩余可购次数。`ShopUpdateNationalPower.setPrice` 的 gold 分支直接取
costAmounts；credit 分支却访问普通 ShopItemTableAccessor，因此本轮仅接 gold、无折扣商品。

实现限定 `limitPerPerson=1/isSet=true/quantities=[1]/costTypes=[gold]/credit=discount=0`，
覆盖 27/38 条表行；全部 47 国的国家映射→item04→draft→building 引用已静态验证无缺行。
运行时仍验证这些引用，不把缺行报成缺文件。剩余 11 条多次限购商品不展示也不接受购买：
请求没有已证实的重试标识，无法区分重复请求与又买一份。

集成方需注入 `national_context(country)` 上下文，提供国家、全局唯一 period、真实 power，
并持有一致性保护直至玩家 `_save` 完成。没有上下文直接 no stub response；不以 0 伪造国力，
不默认开放，不添加周/月重置日期。`economyNationalPurchases[period][shopId]` 为内部购买账本，
与 gold、items 同次保存。相同期间重复购买明确 errorReason，避免成功回调令客户端再加图纸。
账本按全局 period 记录，不按国家拆分，避免换国重置配额；旧期间记录不删除。

单玩家锁加现有 revision 保存只保证玩家更新的并发控制，不构成跨账号交易或国家共享事务。
生产 context 适配器仍缺，不能把测试用内存上下文当作已有数据库能力。

## 对其他未实现入口的补充证据

- 拍卖资源上架预览：`floor(base + amount*amount_mul*seconds/3600)`；金币上架检查
  本金与税费之和，其他资源检查金币税费。武将预览是
  `floor(base + (grade*grade_mul + level)*seconds/3600)`，该消费者没有使用已解析的 level_mul。
  TaxCard/TaxResource 类有默认值，但服务器 Sale.params 会覆盖，不能把默认值当作原服税率。
  仍缺真实系数、挂牌事务与交割闭环，因此未添加上架写处理器。
- `AuctionPostToSellBtn` 的 levelLimit 带 SerializeField，源码 20 可被 prefab 覆盖；
  不能把该初始化值当不可变服务器门槛。禁售卡名单/强化警告也需与 C 组资格校验对接。
- `WaterBorneTradeTableAccessor.getResultFileName` 明确 index=4 读取 result，其他索引读取
  friendResult；不能给好友套用自身结果表。仍缺好友权属及结算概率的完整证据。
- `KokugiScene.toLevel/toPoint` 逐级累加 `(long)(float(table[level][type])*levelRate)`；
  rate 是响应值，不能把点数直接线性除表值。尚未实现国技写操作。
- 游历原表含 dueInterval、intelligenceBias、leastTotalIntelligence 与结果表名；
  PluginRunner_DoTrade 证明按 costTypes/costAmounts 检查并扣客户端显示余额，
  不证明服务器奖励分布或取消退款。继续保留为待证生命周期。

## 验证

`python -m unittest tests.test_economy_services -v`：23 项通过。
`python -m unittest discover -s tests -q`：249 项通过，无跳过。
既有测试中有文件未关闭的 ResourceWarning，未修改共享测试。
新增 13 项包含真实表小样本、余额不足、错误国家上下文、外部 playerId 越权参数隔离、
重复购买、16 次并发购买、保存冲突/异常无扣款无发货、重建服务、容量、国力边界、
周期明示变更，以及缺表文件/坏引用的诊断区分。尚无 Unity 或生产 DB 验收。
