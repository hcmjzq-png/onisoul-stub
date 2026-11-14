# C 组：武将、装备、道具与抽取静态复核

基线 `1f287e33123afa452d2f5d2aac2427566d549f73`，独立分支
`parallel/342-c-card-growth-20261115`。用户指定读取 A 文件但明确负责 C，
因此沿用共同规则，范围按同目录 `C-card-growth.txt` 的 32 项；没有修改 A 组文件。
没有部署、访问服务器、启动客户端或更改 hosts/proxy80/config.ini。

## 交付范围

`reviewed-endpoints.tsv` 恰好 32 行入口，逐项区分请求、已见响应读取、原表、
持久化、权限/费用/重试、未决事项。响应栏是本次确认的读取路径，非完整协议声明。
`evidence.json` 保存原版 51 个 C# 文件与 16 张原表的 SHA-256、包装器行号、
调用点以及原协议证据/兼容选择的分界。没有复制原客户端或完整原表。
三份 fixture 共六行，逐行与原表校验一致。

独立 `CardGrowthServices` 新增四个**未生产挂载**的处理器：

| 入口 | 可集成范围 | 限制 |
| --- | --- | --- |
| deck/sellCharacters | 1–8 个自有、未保护、未被头像/六组编队引用的携带武将；按 character.sellPrice 加金币并删除实例 | 不出售仓库武将；整批拒绝金币溢出；引用限制是保守兼容策略 |
| deck/sellEquips | 1–8 个自有、未保护、未引用装备；按 equip.sellPrice 结算 | 不复原装备强化；同样拒绝溢出 |
| deck/transferStoreCharacters | 携带/仓库双向批量移动原记录；保留保护；验证两端最终容量、明确保存的冷却；一次保存 | 仅无付费扩容；必须显式配置 nextOpenLimit>0；lastOpenDate=提交秒数是兼容选择 |
| politic/lottery/getSouls | 七色存档余额，只读，无赠送 | 裸根数值映射，不能加 succeeded/now；缺失颜色为0沿用现有 profile 策略 |

没有修改共享注册、响应形态、状态层或全局计数。32 项中其余 28 项未实现，
其中 getFormation/setFormation/getNavigators 只找到包装器，没有直接 C# 调用点。
没有将“包装器存在”“拒绝请求”算成实现。

## 关键原证据

- `DeckSale_Character.cs:85-92,242-260` → `CharacterTableAccessor.cs:341-348`：
  价格取基础卡行 sellPrice，不按武将等级猜倍率；返回 `sellPrice` 与
  `characterIds.<index>` 数值。装备同链见 `DeckSale_Equip.cs:108-115,290-308`。
- `CharacterConflateFablic.cs:549-610`：保护卡允许仓库移动，头像不允许；
  不把“保护不能出售”误写成“保护不能入仓”。六组编队全部拒绝移出是本服务保守策略。
- `DeckStorage.cs:150-151,179-182`、`DefinesTableAccessor.cs:355-362`：
  仓库基础容量读 `default_extend_character_store`，原表为100；回包直接替换 StorageInfoHash。
  `DeckMode.cs:371` 使用 `now-lastOpenDate > nextOpenLimit`，边界等于仍不可移动。
  原 defines 另有 `character_storage_open_interval=3600`，但未找到 C# 消费链证明它就是
  原服 nextOpenLimit 的默认值，所以不自动迁移/填入。
- `onikujiWork.cs:181-206`：getSouls 回包根每一项强转 double。
  此次在独立模块中返回裸映射，正式集成时还应修共享 response_shapes 记账。
- `DeckSale_Tactics.cs:337-361`：tactics 返回的是**售出数量**，不是剩余数量。
  堆叠库存无法像唯一实例那样自然防止重复扣款，等待共享请求去重方案，不新增假实现。
- `DeckConflate_SkillRefresh.cs:526-540`：setSkillSlot 请求 baseId/paymentId，
  回包 result.character/category/amount；不是普通布尔启用槽。
- `PoliticItemInventory.cs:107-141`：usePotions 响应为 result.<pointType>.point；
  `DeckUseItem_confimation.cs:187-215` 的武将药水响应则是 potion.<id>.amount、character、
  技能药的 addPoint。两者不能混用。没有把 potion.initialAmount 当赠送。
- `WebApiClient.cs:4676-4692`：getFormation 用 atkOrdef，setFormation 用 atkOrDef；
  不能因命名相近复用 setDecks 协议。

## 待证范围

原表确有 character/equipGrade、Level、skill、potion、navigator、lottery、
booster_packs 等数据，但表存在不等于服务器算法已知。未猜强化成功等级、继承失败损耗、
学习技能、属性舍入、药水50%恢复取整/超限/批量数量、租用续期、卡包阶梯次数与概率。
旧武具强化不是本批证据。九宫格经 NineGridDataParser 追踪到嵌套字段，
活动启用、九格内容、抽取与奖励闭环仍未证，不构造活动日期或奖励。

原始静态文件只读。缺表文件报告 `stub has no assets`；表存在但缺引用行/字段，
报告 `no stub response`，不计为资源文件缺失。原有10个请求资源和两张表缺口未解决。

## 验证

在本工作树执行：

```powershell
python -m unittest tests.test_card_growth_services -v
python -m unittest discover -s tests -v
```

14 项新增测试与完整 240 项回归通过，零跳过；本机没有因可选依赖跳过的测试。
覆盖真实小样本售价、跨账号/未认证、保护/头像/六组编队、批量原子拒绝、资源溢出、
容量、冷却等号边界、重复/混合 ID、立即重试、同玩家并发单胜、revision 保存冲突、
重建服务/重登持久化、裸魂余额与缺表/缺行区分。
费用不足不适用于本批四项（出售是收入，转仓/查询无收费）；付费接口未启用。
测试使用隔离内存账号；没有声称验证 MySQL 实例或真实 Unity 画面。
存储适配器必须保证单份玩家文档原子保存；本批沿用已有 revision 冲突处理。

重试采用拒绝已消失的来源实例，不重放成功回包。跨转仓往返后迟到的旧请求无法仅凭
相同参数识别，仍需总集成的持久请求标识；不会宣称任意延迟重放都已幂等。
唯一实例分配器也必须保证 ID 永不复用，详见 integration-notes.txt。
