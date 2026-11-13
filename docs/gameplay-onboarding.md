# 登录、主城与新手任务 1～4

本层实现第一个可验证的游戏闭环，不依赖手工修改“新号/老号”开关：

- 登录按账号读取玩家存档；`entity.created` 决定新号或老号。
- `auth/createPlayer` 只在首次建号时写入初始状态。
- `common/getPlayerParams`、主城地图、图纸和任务状态均从玩家存档组装。
- 任务 1～4 的状态、奖励和解锁位按 `politicMission.json` 推进入库。
- 建造、施工完成和建筑计数写回同一份玩家状态，重登不丢。

## 已接真实 handler

| 范围 | 接口 |
|---|---|
| 登录 | `debug/devLogin`、`debug/debugLogin`、`auth/gameLogin`、`auth/guestLogin`、`auth/login`、`auth/refreshToken`、`auth/registerName`、`auth/createPlayer` |
| 玩家 | `common/getPlayerParams`、`deck/getAvatarCharacters` |
| 主城 | `politic/map/getMapData`、`politic/building/getBuildCounts`、`politic/building/getDrafts` |
| 任务 | `politic/mission/getStatesFromAllMissions`、`getMissionsInProgress`、`setWorkingValue`、`changeState` |
| 建造 | `politic/task/submitBuildTask`、`submitBuildAndComplete`、`progressBuildTask`、`completeTasks` |

## 新号判定

`debug/devLogin` 先按用户名创建/复用账号和会话，再读取该 `playerId` 的存档：

- `entity.created == false` → 返回 `succeeded: false`，客户端进入建号流程。
- `auth/createPlayer` 成功后写 `entity.created = true`。
- 后续登录返回 `succeeded: true`，客户端直接下发玩家状态。

`entity.cap` 表示 `playerLevel` 的最大等级，武将容量由
`possessionLimits.character` 单独承载。账号、token、playerId 与玩家 JSON 均由现有
`sessions` / `state` 持久层保存。

`deck/getAvatarCharacters` 返回完整武将状态映射；主城立绘只读取其中的
`baseId / grade / voice`，后续编成和详情仍可复用 `atk / def / int / level / exp / skills`。

## 任务链

任务定义来自 `politicMission.json`，服务端不写死任务 1～4 的条件与奖励：

- 任务 1：自动引导任务，完成后发放 `reward01_04_00001_01`。
- 任务 2：建造任意城；初始提供一张城图纸，放置后施工完成。
- 任务 3：自动引导任务，奖励包含田地图纸 `item04_0200041`。
- 任务 4：任意一种田地达到 1 座即可满足 `needClearCount=1`。

任务奖励只在首次进入 `closed` 时发放。资源类 `item11_*` 写入资源余额，图纸类
`item04_*` 通过 `item04.parameterId` 映射为 `draftId`，建造成功后从库存扣除。
stub 奖励按每组 `countNmin` 发放，`ratioNmax > 0` 表示该组存在；这是确定性测试口径，
不实现线上随机区间。

新号基础状态是系统任务 `0: C`，即公告栏 `unlockMessageBoard` 出生可用；任务 1
由客户端 `IsAutoStart` 唤醒，不伪造任务 0～4 的完成状态。

## 地图建筑

建筑使用独立实例号作为 `buildings` / `producings` 的键。地图
`occupiedGrids` 固定为 `坐标 -> 实例号`，符合 `PoliticMap.reset` 的实际读取顺序。
建筑记录包含客户端 `PoliticBuildingParameter.set` 需要的字段：

`buildingTypeId / level / exp / deployedMapKey / status / remainedClickCount / durability`

`submitBuildTask` 的 `remainedClickCount` 直接取 `draft.progressCount`。正数时客户端每次
点击调用 `progressBuildTask`，递减到 0 后才进入 `completeTasks`；0 才允许一步完工。

初始城图纸 `draft2000002` 不是客户端 reset 清单中的初始库存。由于任务 2 必须有城，
这里只发放任务所需的最小一张；来源与限制在代码常量旁明确标注。

## 错误与并发

bare-map 端点认证失败时返回 `{"errorReason": "..."}`，让客户端
`GameRestarter.isError` 在消费数据前接管错误。

`players.state_json` 带 `_revision`。保存前在事务中 `SELECT ... FOR UPDATE`，版本不一致
抛出 `StateConflictError`。进程内还会按 `playerId` 串行化 handler，避免
`getPlayerParams`、任务推进和建造读改写互相覆盖。

## 回归

`tests/test_gameplay.py` 使用内存会话与内存玩家表跑完整流程：

1. 新账号登录返回新号。
2. 建号后玩家参数和 30×30 地图可读取。
3. 任务 1 发奖且重复关闭不重复发奖。
4. 城图纸施工完成后地图与建筑计数更新。
5. 任务 3 发放田地图纸。
6. 田地放置完成后任务 4 条件成立，重登状态不丢。
