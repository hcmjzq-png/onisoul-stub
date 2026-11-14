# 本批服务端字段来源与边界

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
