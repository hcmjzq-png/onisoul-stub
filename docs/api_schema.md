# 本批服务端字段来源与边界

2026-11-17：`GET /client/status` 的 `environment`、`instance_id`、`build_id`
以及 HTTP `X-OniSoul-Environment` / `X-OniSoul-Instance` 是**本服运维自定义**，
用于本机启动器核对目标，非原版游戏协议。只在显式配置环境身份时启用；
不加入 auth、politic 等业务响应。原画布尺寸和资源包保持原有格式。

2026-11-18 追加（**bundle / 本服兼容判定**）：原 `beginning_equipment` 的起始图纸为空，
主城图纸由任务 1 `clearReward → country_00041_self → reward99_country → item04` 发放。
移除本服额外初始 `draft2000002`，保留现有物品。任务 4 使用 `totalBuildingCount`，
原 `StateBuilding.complete` 在排队 `completeTask` 前增加总计数；服务器对显式剩余点击
为 0 的待确认建筑允许该条件计数，`categoryGradeCount` 仍须完工。这不新增回包字段，
不提前修改施工状态。来源与本机验收见[图纸与任务 4 排查](analysis/tutorial-build-contract-20261118/README.md)。

2026-11-15 追加：**bundle**，auth/registerName 重名结果必须是布尔 succeeded=false，
不带 errorReason。原 PC LoginEnvironment.<registerName>.<>m__7EE（RVA 0x2300F8）读取该布尔，
LoginTransNameEntry.<onResult>.MoveNext（0x20ED88）显示姓名提示并允许重试；
GameRestarter.isError（0x70C60）把 errorReason 判为全局错误，导致联机中断。
不改变 createPlayer 二次校验和数据库唯一索引。详见
[本轮证据](analysis/name-media-20261115/README.md)。

2026-11-15，基于原始安装包重新提取的 `Assembly-CSharp.dll`：
SHA-256 `b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`。
来源标记 **bundle** 表示该安装包中的 DLL/表有直接证据；反编译行号来自
ILSpy 8.2.0.7535 的本次输出。指纹链见 `analysis/static-review-20261115/README.md`。
未采用旧工程中九项争议功能的实现。

| 接口 / 字段 | 来源 | 客户端证据与服务端行为 |
| --- | --- | --- |
| `common/getEventStatuses` 的四种活动根键 | bundle | `StatusView.cs:480,555` 通过键是否存在判断活动开放。当前没有活动排期，因此省略 `turfWar/strategy/siege/giganticRaidBoss`，只返回正常信封。没有实现这些活动玩法。 |
| `common/getShopsale` 的 `openTime/storetable/endTime` | bundle | `PoliticShopSaleManager.onGetShopSaleData`：存在前两键才进入特卖分支。当前无特卖，省略全部特卖字段，使用普通商店分支。 |
| `common/getCharacters`、`common/getSelectCharacters` 的 `<instanceId> -> character` | bundle | `WebApiClient.cs:1098,1106`、`DeckConflateCards.createStatus`、`QuestDataCache.calcDeckParameter`；裸映射，仅返回当前玩家存档中的武将。选取接口参数是 `ids` 数组。沿用已有武将记录字段，没有发明新武将属性。 |
| `deck/getDecks` 的 `avatar.id/grade` | bundle | `DeckScene.cs:309` 读取 avatar.id；`WebApiClient.cs:1131` 写入 id/grade；`DeckMake.cs:896` 明确发送显示 grade=1。只允许选择已拥有武将。 |
| `attack/defense/politic/quest/strategy/siege.<deck>.ids/tactics/equip` | bundle | `DeckMake.cs:80-104,847-892`、`DeckPostPanel.cs:452-540`。数字字符串键，ids 的值为数值实例 ID 或字符串 `empty`；战术/装备 ID 为字符串。保存全部六组，拒绝未拥有的卡和同组重复武将。国战/城战这里只储存编队结构，不实现争议玩法。 |
| 编队数量及位置 | bundle / 待验证 | attack 数量来自 `playerLevel.attackDeckCount`；politic 数量由 `DeckMake.cs:214-222` 的地图解锁控制；strategy/siege 各两组，defense/quest 各一组。武将位置 0..4 见 `DeckPostPanel.cs:9-21`；attack/defense/quest 末位是主将（相应子类 settingPostObject）。装备/战术仅有空库存，非空槽位会拒绝；它们的完整槽数和玩法仍待验收。 |
| `inheritPoint/skillCoins/possessionLimits` | bundle / 待验证 | `DeckScene.OnEnable` 直接读取这些字段。容量沿用 `playerLevel.maxCharacter/maxEquip/maxBuilding`；点数从玩家存档读，缺失返回 0，是当前模拟服默认策略，原版初始赠送值待验证。 |
| `deck/setDecks` 成功 `{}` | bundle | `DeckMake.cs:908-916` 通过 Hashtable.Count==0 判成功；禁止加入 succeeded/now。失败沿用裸映射错误策略，并保证不写存档。 |
| `deck/getAvatarCharacters` | bundle | `Politic.cs:301-307` 遍历全部返回值并逐一覆盖头像；`QuestDataCache.cs:606-624` 同样覆盖主角。因此自身请求只返回选中的一位，避免把全武将表的最后一位当主角。其他玩家的查询未实现，会明确失败。 |

`WebApiClient.cs:300-318` 按响应 Content-Type 选择解码，缺省是 JSON；即使
getCharacters 请求偏好 IgBinary，服务端返回 application/json 仍使用 MiniJSON。

## 初始编队与旧存档修复

- **bundle**：`beginning_equipment.<country>.questCharacters/attackCharacters/defenseCharacters`
  给出初始物品 ID；`item01.parameterId` 关联 `character`。服务端使用这些表和已拥有的
  武将实例建立编队，空的 politic/strategy/siege 不生成武将或装备。
- **待验证**：初始槽位顺序、初始头像选择是本模拟服引导策略：表中第一位放主将位 4，
  其余按 0..3；首个 quest 武将作头像。原服初始化响应尚未取得，不能称为完全复原。
- `tools/repair_starter_rosters.py` 默认只读；应用必须指定备份目录。只修复 created=true、
  武将/编队/建筑/任务进度/领奖记录均空、任务仅 0:C 或 0:C+1:O 的旧角色。
  补齐本国表中初始武将、初始编队及武将计数，不重置姓名、资源或任务，不改有武将/已有进度的账号。
  写入前保存原始 JSON，数据库按 revision 检查并发，重复运行不会重复发放。

## 任务校验

**bundle**：`PoliticMissionProgressList.cs:810-825` 的 clear_mission 要求全部前置任务完成；
`PoliticMissionConditionOne.cs:174-182,211-255` 分别读取总建筑计数、当前地图分类计数、
精确任务状态；`checkCondition` 按 conditionCountN 汇总子条件、锁存已完成组；
`PoliticMissionProgressStatus.cs:133-149` 的 IsClearedMission 按 needClearCount 汇总组。

本批服务器实现 none/clear_mission 前置检查，以及 missionStatus、totalBuildingCount、
categoryGradeCount（建筑 grade/level=any）、eq_greater_than 条件。
真实表的新手 1—4 任务已覆盖；第 4 任务的三种田地是任选一种，不能误写成全部完成。
未完成建筑不计数；未知条件返回失败，不发奖。批量请求中任何一项不合法都不保存。
客户端可合并状态更新，所以接受 accepted→closed，但仍检查真实条件。

`missionChecks` 是仅服务端使用的完成组记录，不回传为协议字段。旧存档中已 finished
但没有此记录的自接受教学任务允许继续领取；建筑条件仍必须重新验证。
已 closed 不可回退重领奖；重复 closed 不发奖；奖励表缺行时不关闭任务或消耗领奖记录。
奖励数量沿用已有实现读取 countMin；原版随机奖励、后续任务条件和九项争议玩法未复原。

本批新增 6 个专用处理器：两项活动/商店状态、两个武将查询、编队读/写。
登记端点仍为 402；专用处理器从 23 增至 29，通用占位从 379 降至 373。
这个计数只表示派发覆盖，并不表示 29 项玩法已全部完成或通过 Unity 真机验收。

## 第二批：编队依赖、资料与普通商店

本批再接管 16 个端点，通用占位从 373 降至 357。完整清单由
`python tools/endpoint_progress.py` 生成到 `analysis/player-loop-20261115/`；
该清单的 next_work 是工作安排，不表示每条都已完成新的手工复核。
以下源码沿用本文开头指纹对应的重新反编译目录。

| 接口 / 字段 | 来源 | 实现及限制 |
| --- | --- | --- |
| `common/getEquips`、`common/getTactics` | bundle | `DeckConflateCards.createStatus`，返回当前玩家保存的裸映射；不生成不存在的装备/战术。 |
| `deck/getProtectedCharacterIds/getProtectedEquipIds`、`setCharacterProtect/setEquipProtect` | bundle | `WebApiClient.cs:1249-1288`、`DeckScene.cs:179-202` 和对应 CharacterConflatePreview 的 protectOrRelease。参数 characterIds/equipIds 与布尔 enable；读取是索引到 ID 的裸映射，设置成功为空表。只修改已拥有卡（含已入仓武将）的保护状态；整批验证后保存。 |
| `deck/getCharactersInStore` | bundle | `DeckConflateCards_StrageCharacter.cs:21-26` 把根表传给 createStatus，故纠正为裸映射。旧契约把另一个响应 StorageInfoHash.extendSlot 误挂到本端点。 |
| `deck/getCharacterStoreInfo` | bundle / 待验证 | `DeckScene.cs:66-72,141-146`、`DeckStorage.cs:118,147-166`，需 characterCount/extendSlot/extendLimit/lastOpenDate/nextOpenLimit/now。计数取保存的仓库武将，其他值取存档；缺失填 0 表示没有扩仓/开仓记录。这是兼容初始化策略，原服冷却时长未恢复，未新增存取/付费扩仓业务。 |
| `deck/getDeckBonus.deck.<kind>.<slot>.id/bonus` | bundle | `DeckScene.cs:214-238`、`vsSetting.cs:87-107`。读取实际编队中的 ID；当前未启用排行/限时加成，bonus 为空，不因存在 limitedTimeBonus 表就激活旧活动。不代表完整加成玩法实现。 |
| `politic/mypage/getPlayerProfile` | bundle | `mypageProfileUpdate.cs:239-299`：username/level/country、三种 Point、characterCount/buildingCount/tacticCount/friendCount/raidBossPoint/rank、souls 七色、selfIntroduction.message/三项 habits。纠正旧契约把嵌套的 message、habits、颜色错误平铺到根。取玩家存档，无记录的统计为 0；无排行不伪造 rank。eachKokudaka 仅当前主城。 |
| `politic/mypage/setSelfIntroduction` | bundle | `mypageSelfIntroduction.confirmCallback` 传 message 与 habits.0/1/2；长度按 defines.self_introduction_message_min/max_length，偏好 ID 按 habit 表，保存后 profile 返回。 |
| `politic/map/setMapName2`，`getMapData.map.name` | bundle | `WebApiClient.cs:704-711` 的 mapId/mapName；`UserStatus.cs:1301-1332,1371-1404` 从 map.name 读取，none 容器以空表判改名成功。只支持主城 mapId=0，长度按 defines；不将支城旧实现引入。 |
| `politic/mypage/getLessonStates.states` | bundle | `LessonMissionSimpleStatusManager.cs:66-127`、`LessonMissionSimpleStatus.cs:20-33`，索引数字字符串对应 L/C。枚举 lesson 表，按 lessonsDone 返回；未读不标完成。2026-11-15 从原表包找到 reward14_lesson（24 行）；takeLesson 已实现的限定范围见下文成长流程复核。 |
| `politic/support_item/getPotions.potions.<id>.amount` | bundle | `PoliticItemInventory.setup/putInItemList`、`PotionTableAccessor.getItemId`，potion.itemID 映射已有 items；不把 initialAmount 字段当免费赠送。全自动用药条目明确回零余额，其余按实际库存返回。恢复公式尚未证实，usePotions 未纳入完成计数。 |
| `politic/shop/getShopItems.shopItems/recommendedItems` | bundle / 待验证 | `ShopUpdate.cs:57-110,204-210` 要求两张表；条目读 state/isNewBuyable/discount。当前仅列出 isInitialSale=true、无折扣、有正价格且能发放的图纸/消耗品，其他商品不展示。isInitialSale 作为白名单是本模拟服保守策略，未声称复原原服上架/解锁规则。 |
| `politic/shop/buyShopItem.resources/result` | bundle | `WebApiClient.cs:1036-1046` 请求 shopItemId/index/quantity/storetable；`ShopItemBuild/Support.saleWindowResult` 读取 resources，`DailyMissionScene.cs:440-450` 读取 result 中购买后物品余额。只接受普通 shop_item 表；整套/单件按 isSet/itemIds/quantities；countryshop 通过 shop_item_country 映射本国物品。 |
| 商店费用 | bundle | `ShopUpdate.cs:114-146`、`ShopItem.sortResource`：credit 类型使用行内 credit 替换 costAmounts，不能相加；其他资源按表值。缺余额/未知商品/非整数或非正数量/错误下标/未知促销表均失败，整笔不扣款、不发物品。写入沿用玩家锁与数据库 revision 校验。 |

新逻辑对应 `app/business/player_services.py`。商店发放进入现有 items，图纸通过
getDrafts 可见，消耗品通过 getPotions 可见；保护、介绍、改名跨重登保留。
没有实现战斗、关卡随机事件、领奖概率、药品恢复、付费扩仓和九项争议玩法。

## 2026-11-15 动态关卡表复核

来源：bundle。关卡索引/区域/奖励动态表及响应层级的新增证据见
[关卡与战斗分析](analysis/quest-contract-20261115/README.md)。
本批仅修复服务端表加载与 UTF-8 数据，不新增接口处理器；旧 api_contract.tsv 中的
quest 扁平字段并非完整协议，后续实现以该复核记录为依据。事件概率、初始进度、
战斗运算及领取条件仍待验证，不使用占位值替代这些规则。

## 2026-11-15 成长流程复核

原安装包来源、逐接口证据与限制见 [357 接口复核](analysis/remaining-services-20261115/README.md)。

| 字段 / 行为 | 来源 | 证据与范围 |
| --- | --- | --- |
| `politic/mypage/takeLesson.reward/toInbox` | bundle | `LessonScriptCommand.cs:148-167` 读取两张表；按 lesson.triggerMissions 要求 C，按 reward14_lesson 确定数量发资源/经验。24 项中支持 19 项；其余 5 项或资源溢出明确失败、不记完成。成功的 toInbox 为空，因为本批只支持可直接交付的奖励。 |
| `common/solvePlayerLevelCap.cap` | bundle | `PoliticMissionManager.cs:461-496` 读取 double；playerLevel.requirementForNext 和 defines.level_limit=15，依任务 C 状态依次开放 5/10/15。 |
| `common/increasePlayerLevel.kokudaka/possessionLimits` | bundle | `StatusView.cs:331-338` 调用 updateKokudaka/updateActionPointTotal/updateLimits，后续 resetStatus 重取状态。前两字段取存档与原级别容量；未证实的升级点数奖励不发放，保留点数。累计 exp 的门槛由 `UserStatus.cs:262-334,1247-1286` 和 PlayerLevelTableAccessor 支持。 |
| `common/getPlayerEntity.playerId` | bundle | `WebApiClient.cs:1562-1576` 的 debugCreateQuestEncount 读取根 playerId.ToString；返回当前认证账号，不接受参数替换成其他玩家。额外字段未证实。 |
| `common/getServerTime.now` | bundle | `SceneResources.cs:114-117`、`Configs.cs:1336-1339` 按 double 读 now；返回当前 Unix 秒数，沿用已有信封。 |
| `auth/keepAliveContainer` | bundle | `SessionKeeper.cs:207-218` 回调不读负载；返回已有确认信封，HTTP token 解析层触碰会话。删除旧契约误抄 guestLogin 的 isCreatedPlayer/loginHash。 |
| 点数超过 maxPoint 的存档读取 | bundle | `UserStatus.cs:861-890` 的 setActionPoint 允许 0..999，不以 maxPoint 截断；读取时保留超额值。药水公式及实际溢出上限仍待验证。 |

`usePotions` 及 4 个 dailymission 入口仍是待办；新发现的准确响应层级记录于复核报告，不以缺乏规则的空成功回包代替业务实现。

## 2026-11-15 城市与道路复核

完整范围、原版文本证据与待办见 [城市接口报告](analysis/city-contract-20261115/README.md)。

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| 新角色 `resources`、`actionPoints` | bundle + 用户首次进游戏截图 | beginning_equipment.common：gold=5000，food/wood/iron/credit=0；所有国家行这五项为 0。playerLevel.1：MP=25、PP=25、BP=100。截图逐项相符，来源散列见本批 source-proof.json。资源仅在创建角色时发放，读档/重登不补发，任务及教程奖励独立按原表结算。修正旧代码把初始 5000 金钱归到任务奖励的错误。 |
| 道路邻接提高生产量、修路不扣金钱/PP | bundle | 原教程 POM_MES_000006_03_001；三种道路的原 draft/building 行；PoliticBuilding.cs:1239-1275,2350-2387 的即时建造分支。已修正 PP，未猜收益加成系数。 |
| `submitBulkBuildAndComplete.buildings/autoProducings/originCoords.<id>.0/1` | bundle | PoliticFSMConstruction.cs:472-532。坐标是按实例 ID 索引的数字键映射，删除旧契约根 0/1。仅免费道路批量建造。 |
| `submitSerialBuildAndComplete.<index>.x/y/buildingId/building` | bundle | PoliticBuilding.cs:2402-2478 按数字根键读取，Count-2 个记录，另需 autoProducings。 |
| 连续建造元数据 `now` | 待验证 | 消费者只证明两个非数字根键，其中一个 autoProducings。沿用已存在的 now，成功时省去 succeeded 来满足循环长度；这一组合是兼容实现，非原服抓包。 |
| `relocateEnded` 请求 relocatedGrids | bundle | PoliticBuilding.cs:1750-1758 生成 xNyN→数值实例ID，PoliticBuildingList.cs:268-274 枚举完整布局。回调不读字段，返回原有确认信封。 |
| 库存 deployedMapKey="none"；`deployBuilding.buildingId/building/autoProducings` | bundle | PoliticBuildingParameter.cs:284-291、PoliticMap.cs:278-287、PoliticBuilding.cs:842-895。只接入空闲普通建筑，不接自动生产/道路移除。 |
| `levelUpBuilding.building` / `levelUpBuildings.output_buildings` | bundle | PoliticBuilding.cs:931-951、PoliticFSMBatchUpgrade.cs:77-111、PluginRunner_LevelUp.cs:46-69。建筑字段沿用原持久记录；缺经验/成本/PP 或非空闲失败。 |
| `levelUpBuildingCollectively.resultBuildings/totalUsedPoint/restResources.<resource>.amount` | bundle | PoliticFSMProduct.cs:1086-1124；PoliticBuilding.cs:2258-2332。原 amount 在 restResources 内，非根字段。逐级扣经验与费用，未发放经验。 |
| 城市回包 kokudaka | 待验证 | 单体贡献 helper 可见于 BuildingsTableAccessor.cs:637，但全局汇总/加成尚未核实。本批新入口省略可选字段，保留原存档值；UserStatus.cs:1820-1830 容许缺省。 |
| `submitProduceTask.dueTime/now` | bundle | StateManualProduce.cs:51-66 → PoliticBuildingParameter.cs:172-182；仅修契约，生产服务尚未实现。 |
| `submitBulkProduceTasks.producings.<id>.productId/createdTime/dueTime` | bundle | PoliticFSMCollectiveProduce.cs:98-125 → PoliticBuildingParameter.cs:191-199；仅修契约。收获时同名 producings 另有 reward/building/collaborator。 |

## 2026-11-15 生产链追加证据

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| getProductsByBuilding 请求 buildingId、响应 products 的键 | bundle | WebApiClient.cs:973-979、PoliticFSMProduct.cs:608-616,652-659、ProductUpdate.cs:121-144。按账号主城建筑原 products 与玩家等级过滤；level/buildingTypeId 由客户端 Add，不能预填。 |
| products.<productId> 的空对象值 | 待验证 | 消费者只读键。空对象是模拟服兼容选择，原服值尚未抓包证实。 |
| product.openLevel / openMission | bundle | PluginManualProduce.cs:105-113 → UserStatus.cs:1212-1215 使用玩家等级；该类为原包自动操作插件。原 1288 行 openMission 均为字符串 null；非空门槛不猜实现。 |
| 菜单产量 countMin/countMax | bundle | ProductItem.cs:98-102 → UserStatus.cs:1735-1740 按建筑 grade/level 做 float32 线性插值后向下取整；item15 改用伤害值。只证明预览，不证明含道路/技能的最终结算。 |
| 生产未实现错误 errorReason | bundle + 待验证 | 字段来自 GameRestarter.cs:61-94 的过滤器，WebApiClient.cs:324-333 据此跳过回调；错误文案/no stub response 是本服务诊断，不宣称原服错误码。四个生产占位写接口和 completeTasks 的生产分支明确失败、不写档。通用错误 UI 待真机验收。 |

范围与未决规则见 [生产链报告](analysis/production-contract-20261115/README.md)。

## 2026-11-15 A–H 汇总接入

完整逐组范围、暂缓项及证据见 [汇总审核](analysis/parallel-342/review/README.md)。
本批 8 项限定端点接入，其他 21 个候选组件仍未挂载。

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| `politic/shop/sellBuildings.buildings/gainGold/buildingCount` | bundle / 待验证 | A 组 evidence.json；InventoryUpdateSaleBuild.createItemObject 按 ItemIdToShopIdTableAccessor.getPrice 得到售价，消费方只读被售建筑键、gainGold 和总数。buildings 值保留原记录为兼容选择，非原服抓包。仅库存空闲建筑、无引用、无溢出整笔出售。 |
| `deck/sellCharacters.sellPrice/characterIds`、`deck/sellEquips.sellPrice/equipIds` | bundle | C 组 evidence.json；原出售消费者读 sellPrice 和数字键映射的数值实例 ID，价格来自 character/equip.sellPrice。保护/六种编队/头像引用不可出售，重复请求不再次付款。禁止溢出是本服保守边界，原溢出处理待证。 |
| `politic/lottery/getSouls.<red/blue/purple/yellow/green/black/white>` | bundle / 待验证 | onikujiWork.cs:199-206 遍历所有根值并强转 double，使用裸数值映射。读取现有 souls；未存余额返回零为兼容策略，不证明原服赠送规则、不发魂。 |
| `common/getPlayerCogid.playerId` | bundle / 待验证 | H 组 Configs.GetUserInfo 消费 playerId.ToString。会话 playerId 作为本服身份映射，不声称恢复 COG 平台绑定。 |
| `plugin/getPluginData.pluginData/pluginTime.pluginTime` | bundle / 待验证 | PluginTaskManager.OnGetServerData；PluginPoliticSetting/PluginBattleSetting/HashAccessor 强类型读取三类设置，DreamSpaceType 必须有可用的 0/1 索引。返回内部 accountProgress 的已保存设置/到期秒数；无记录为空设置和零时长为兼容策略。plugin/setPluginData 仍未接入，不发时长。 |
| `plugin/getPluginLog.logdatas`、`plugin/addPluginLog` 的 logdata.action/reward/time | bundle / 待验证 | H 组 PluginTaskManager/PluginLog 消费者。仅诊断存储，reward 不作奖励；服务端覆盖 time、按追加序号保存并限制 200 条为本服策略。无 nonce，重试允许重复日志。 |

历史审核时背景 `setBackground` 的 mapId 尚待确认；后续结论见下方「首档成就与原表发布」。
`trophy/getTrophyProgress` 旧 SCALAR_ROOT 记录不足以指导全部 access；至少 mypage 消费者要求根记录映射，
本批不接入该业务、不将其算完成。其余商业规则和状态生产者仍按汇总逐项标记为待验证。

## 2026-11-15 A–H 第二轮候选协议（未挂载）

以下为候选组件的原消费者字段，来源索引及阻塞见 [第二轮汇总](analysis/parallel-342/review-round2/README.md)。
本轮不减少占位数，新增内部存档键不作为原协议字段。

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| `getQuestEncountWorks.obstacle.<questType>.questId/chapter/area/step/category/type/needAmount/amount`；`clearObstacle.isSuccess/uses.category/uses.<resource>` | bundle / 待验证 | B lifecycle-evidence.json，QuestScriptCommand.cs:724-732,2189-2232,2287-2289。仅已生成且获授权的四资源障碍；已解除重试明确失败不重放扣费量是本服策略；未恢复原遭遇生成或活动授权。 |
| `deck/sellTactics.sellPrice/tactics.<baseId>` | bundle / 待验证 | DeckSale_Tactics.cs:307-368、DeckSaleTacticsObj、TacticsTableAccessor；数量是已售数量增量。只有内部可信 operation_id 事务入口，收据/1024 限额为本服策略，未公开挂载。 |
| `getBackgroundItems.shopItems`、`buyBackgroundItem.resources`；国家商城 `shopItems.<id>.state/remain`、根 `recommendedItems`、购买 `resources` | bundle / 待验证 | D shop-evidence.json / 原 ShopUpdateBg、ShopItemBackground、ShopItemNationalPower。shopItems 的背景空值是仅消费键的兼容选择。静态上架、全局 period、items 归属为待接内部策略，不证明原运营排期。 |
| `inbox/getParcels` 的 `parcels.<id>.createdTime/rewards`、根 `totalCount`；`resolveParcels` 的 `successful.<id>.rewards`、根 `failed` | bundle / 待验证 | InboxReader.cs:92-177、InboxResolveWorker、PluginRunner_DoReceiveMail、RewardProcessor。仅四资源；包含 end 的分页、排序、500 批次、永久已领取 ID、重试空 rewards 均为兼容选择。未恢复发行、旧档和通知。 |
| `siege/getPairings.pairings.<index>.defender/attacker.<slot>` | bundle | HTMLSiegeMediator.request 的数字槽及国家 ID；名称、排名、isMe 为客户端产生，不当作服务端字段。真实配对生产端未提供。 |
| `strategy/getStrategyWinLossRecords` 根 `totalCount`；`records.<index>.openTime`、该记录内 `decisions.<match>.winner` 及 `a/b.<slot>.countryId/rate` | bundle / 待验证 | HTMLStrategyMatchMediator_History.analize；a/b 在 match 内。rate 经 HashAccessFuncs.getInt，投影拒绝 float32/Int32 无法精确表示的整数。按已存完整记录计总数和排序为限定兼容行为，无真实历史来源。 |
| `trophy/getTrophyProgress.<category>.level/status/window`；`completeTrophy.progress/rewards/characters/equips/toInBox` | bundle / 待验证 | TrophyWindow、mypageTrophyUpdate、mypageTrophyReward；mypage 查询裸根、toInBox 大小写已核实。仅 playerLevel 首档，清除提醒及重复拒绝是本服策略，首次 4 级阈值和固定奖励来自原表。其他 access、后续档和历史领取迁移未支持。 |

A 的生产费用/预览/耐久 helper 和 G 的数值精度检查没有新增公开响应字段，不据此开启生产或排行榜。

## 2026-11-15 首档成就与原表发布

本批正式注册 3 个 trophy 入口，仅支持 `access=mypage` 的 `playerLevel` 首档。
详细限制和复现命令见 [实施记录](analysis/verified-trophies-20261115/README.md)。

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| `getTrophyProgress` 裸根 `<category>.level/status/window` | bundle | TrophyWindow.cs:80-94 遍历每个根值为 Hashtable；mypageTrophyUpdate 同样消费根记录。全局形状从 SCALAR_ROOT 修正为 BARE_MAP，错误仅含 errorReason。其他 access 明确失败。 |
| `completeTrophy.progress/rewards/characters/equips/toInBox` | bundle | mypageTrophyReward.cs:50-61；奖励逐项累加到客户端，重复领取必须失败，不能重放成功奖励增量。无角色、装备、溢出转信箱时对应 map 为空。 |
| 首档阈值与奖励 | bundle | mypage_trophy.playerLevel_001.clearAmount=4；reward06_trophy.reward06_playerLevel_001 的 A/B 两组固定 100%：item11_0000101=100000、item08_0102701=6。item08 定义后者为启用的 jewel。原字节哈希见 recovered-tables-source-proof.json。 |
| 领取后 `level=1,status=lock,window=0` | bundle + 待验证 | mypageTrophyItem.cs:70-94 证明该组合显示「首档已领取」、后续不显示领取按钮。只投影已支持首档是本服限制，不声称原服永远停在首档；不存在自动授予下一档。 |
| 通知确认与首次旧档初始化 | 待验证 | `accountProgress.trophyClaims` / `levelTrophyNoticeSeen` 是本服内部状态。原 stub 尚未发放成就，缺失 ledger 视为未领取；已有合法 ledger 保留，损坏 ledger 拒绝。禁止未经迁移导入原服领取历史。通知确认不发奖励；超资源上限整笔拒绝，未实现信箱分流。 |
| 背景 mapId / 解锁边界 | bundle | mypageCastleTownItem.cs:101-147 仅 no=1 显示背景切换和商店按钮，并要求 mapEntry.isEnable、PoliticMissionManager.IsOpenSubMap。mypageBgSelectWindow.cs:135-150 明确发送 mapId=1 并更新同一 mapEntry。主城 no=0 隐藏按钮，不存在 0→1 偏移映射。 |
| 背景内部归属与选择 | 待验证 | 候选购买/选择统一读取 items，选择保存于 mapBackgrounds["1"]。内部 subcity_enabled 提供者尚无正式实现，因此四个背景入口仍不挂载，不把旧 backgroundOwnership 或 mapBackgrounds["0"] 自动认定为原服权益。 |

## 2026-11-15 research331 汇总：社交、通知与权限

本批正常注册新增 7 个 friend 和 2 个 inbox 入口，详见 [汇总审核](analysis/research-331/review/README.md)。协议来源均为原安装包反编译，不采用旧 AI 的收件箱页面作为证据。

| 字段 / 行为 | 来源 | 证据与限制 |
| --- | --- | --- |
| 好友写入 `result`、失败 `detail.0` | bundle / 本服重试策略 | FriendConfirmationWindow.cs:127-154,195-299。成功回调增减客户端计数；无实际状态转换的重复操作返回 false，避免重放增量。已提交丢回包需重新查询，不能证明跨全新申请周期的幂等性。 |
| `getFriends` 裸 playerId 映射，name/country/level/baseId/grade/status | bundle | FriendData.cs:40-59。原 option 为 ""/ok/send/receive；基于双边关系投影，不返回伪造 isFirst/访城许可。 |
| `getFriendProfile`、selfIntroduction.habits | bundle / 本服兼容策略 | FriendData.cs:61-94。仅 forHTML=false；现有缺历史统计的 0/空字符串保持明确兼容范围，不代表恢复战果。 |
| `updateFriendData.count.ok/send/receive`、`remove.<peer>` | bundle / 本服通知策略 | FriendWindowControll.cs:118-127、FriendConfirmationWindow.cs:168-187；remove 消费键，具体原因文案与保留/刷新策略为内部实现。 |
| `periodicInquiry.friendOffer/inboxParcel` | bundle | UserStatus.cs:148-164 按绝对数字赋值，不累加；不发送未实现的 unreadMail。SessionKeeper.cs:176-199 登录即开轮询，未创建角色时省略社交计数并保留 gmMessage/show_off。 |
| `getParcels.parcels.<id>.createdTime/rewards,totalCount` | bundle / 本服分页策略 | InboxReader.cs:92-177；真实发行记录，时间倒序再按 ID 排序、包含 end 为本服策略；没有普通玩家指定奖励的发行入口。 |
| `resolveParcels.successful.<id>.rewards,failed` | bundle / 本服重试策略 | InboxResolveWorker.cs:11-105、PluginRunner_DoReceiveMail.cs:12-66；失败只消费 Count。已领取重试不重放奖励增量，仅返回空 rewards。奖励与领取墓碑同一 CAS 保存。 |
| item11_0000101/201/301/401 → gold/wood/food/iron | bundle | RewardProcessor.cs:51-73。仅四资源，不扩展付费货币、卡牌或随机奖；容量不足该包裹失败。无已证期限，此发行子集明确无自动过期。 |
| 管理/调试拒绝的根 `errorReason` | bundle 字段 / 本服关闭策略 | GameRestarter.cs:79-99 在成功消费者之前检查。32 项在 HTTP 认证及 Registry 直调均拒绝；原包装器存在不构成管理员授权。 |
| socialOffers/socialRemovals/socialInboxIssuances/shared_records | 本服内部持久化设计 | 不加入原请求/响应。无对应字段的本服旧档按各模块缺省读取，损坏数据拒绝；不自动导入原服历史、重置资源或授予奖励。 |

## 2026-11-15 新手初始化与开放位一致性

来源：**bundle**。详见 [运行修复与验证](analysis/research-331/review/new-player-fix-20261115.md)。

- `getStatesFromAllMissions.states` 不再为尚未唤醒的任务预先写 O；初始仅系统任务 0:C。
  O/A/F 摘要与 `getMissionsInProgress.missions` 明细必须一致，否则明确报错，不生成虚构进度。
- 系统任务 `work0` 由原客户端默认映射位、任务接受/完成开放位及 10 级截图条件派生。
  `unlockBits` 是内部缓存，不是独立授权来源；不持久化未经验证的客户端上报。
- `setWorkingValue` 只实现原客户端当前可追溯的系统任务 index=0。允许确认已符合前置的接受开放位，
  以兼容原客户端先上报位、后提交状态的顺序；实际权限在任务状态提交后保存。
- 不新增协议字段，不把 0x1fffffff 传输范围当作玩家权限，也不绕过剧情临时操作锁。
  本轮静态/HTTP/MySQL 回归完成，真机新手对话与逐步解锁尚未验收。

## 2026-11-15 任务经验奖励修复

来源：**bundle**。`RewardProcessor.cs:29,260–264` 将 `item11_0000501` 作为角色经验累加；
原表前三项新手任务对应奖励分别为 25、50、25。任务领奖现在写入 `entity.exp`，不写入 items 或 credit。
原有领奖记录保证重试不重复累加；失败批次不保存奖励，正常重登通过 getPlayerParams 读取累计经验。
不新增协议字段、不自动升等级，也不自动修复未经核对的旧奖励记录。
真机发现与 #65 上线边界见 [部署验收](analysis/research-331/review/deployment65-20261115.md)。

## 2026-11-15 昵称唯一性

来源：**bundle**，`LoginEnvironment.registerName` 按 succeeded 判断命名能否继续；
`LoginTransNameEntry.onResult` 已有名字不可用的提示。本轮保持这两条接口的响应结构，
为 auth/registerName 和 auth/createPlayer 增加数据库冲突到 succeeded=false 的处理。
内部 player_id 保持稳定主键；username_key 仅为内部唯一索引，不是新增协议字段。
上线前必须解决现有两组精确重名，迁移不会擅自改名。
国家图片/随机语音、最终决定等待及白屏内存证据见 [本轮审核](analysis/login-country-20261115/README.md)。

## 2026-11-17 建造成功响应的错误标记

来源：**bundle**，`GameRestarter::isError`（`0x0600158D`）按根 `errorReason` 的存在判错，
空串也会触发中断；`WebApiClient` 在成功回调之前执行它。契约的读取键同时包含成功、失败
分支，不能把 `errorReason:string` 的空默认值放入真实成功响应。
`GameplayService._success` 移除该占位默认键，失败仍走 `_failure` 并保留错误原因；
不新增字段或改变建筑存档。任务 2 的抓包与本机验收见
[摆放主城中断排查](analysis/mission2-build-disconnect-20261117/README.md)。

同类模板审计还涉及两个建筑升级入口；四个真实处理器共用本次修复。
尚未实现的 conflateBuilding 改为明确 no stub response，保留真正失败的 errorReason。
普通重登缺失 scr2_000001 的临时锁另由客户端兼容补丁处理，不是协议字段或任务解锁修改。
