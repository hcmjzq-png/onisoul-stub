# 行为层契约（behavior_contract.tsv / api_call_graph.tsv）

从 `Assembly-CSharp.dll` 反编译出的 2034 个 `.cs` 静态抽取：**每个端点被客户端调用后，回调体里到底做了什么**。

## 方法与口径

1. 端点 → 调用点：沿用 `api_contract.tsv` 的 `call_sites` 列，格式是 `类.方法`（多个用 `|` 分隔，部分带 `#responder=形参` 标注）。
2. 源码范围：`app/` 下**递归**全部 2034 个 `.cs`（含 `PoliticBuildingState/`、`MsgPack/`、`Script/`、`MiniJSON2/` 等 10 个子目录）；只扫顶层 1497 个会漏掉 `StateBuilding` / `StateAutoProduce` / `StateManualProduce` 这类状态机类。
3. 调用点 → 方法体：先按 `class X { ... }` 花括号范围定位类体，再在类体内按「任意缩进 + 多个修饰符 + 返回类型 + 方法名 + `(`」定位方法体。修饰符支持叠加（`protected override`、`public static async` 等），此前只允许单个修饰符，导致 75 个调用点误退到整类体扫描。
4. 从方法体里抽五类副作用：
   - `scene_ops`：`transitionScene("x")` / `process("x")`
   - `windows`：`WindowController>.Instance.xxx(`（窗口创建/开关）
   - `service_calls`：`ServiceLocator<T>.Instance.method`
   - `state_writes`：`类.字段 =`（静态状态、缓存、单例属性）
   - `guarded_keys`：`if (...)` 行里出现的本端点响应键 → 该键驱动分支
5. 端点 → 端点边：方法体里出现 `webApiClient.xxx(` / `client.xxx(` / `ServiceLocator<WebApiClient>.Instance.xxx(`，按 `xxx` 回查端点表。
6. 只有**取到精确方法体**才记账；方法体定位不到的调用点不参与副作用抽取，避免把同类其它方法的调用混进来。

## 覆盖

| 指标 | 数量 |
|---|---|
| 端点总数 | 402 |
| 定位到调用点方法体 | 350 |
| 无调用点（`call_sites` 为空） | 52 |
| 有场景切换证据 | 9 |
| 有窗口操作证据 | 37 |
| 有状态写入证据 | 16 |
| 有键守卫证据 | 67 |
| 端点→端点边 | 392 |
| 有出边的端点 | 106 |
| 无入边的端点（只能由界面/启动流程发起） | 6 |

## 关键事实一：流程是「场景驱动」，不是「回调链驱动」

只有 9 个端点直接触发场景切换，且目标集中：

| 目标场景 | 触发端点数 |
|---|---|
| `politic` | 4 |
| `vsBattle` | 3 |
| `deck` | 1 |
| `migrationLogin` | 1 |
| `strategy` | 1 |

9 个端点共触发 10 次（`debug/debugCreateEquip` 一个回调里连切 `politic` 与 `deck`）。计的是**端点**不是调用次数：同一端点方法体里重复出现的同名 `process(...)` 只算一次。

从 `common/getRevisions`、`auth/gameLogin`、`auth/guestLogin`、`common/getPlayerEntity` 出发做深度 3 的可达分析，**可达端点数为 0** —— 这几条启动链的回调体里不直接发下一个请求，而是 `transitionScene` 换场景，由新场景的 `Awake/Start` 重新发起请求批次（`TableLoad` → `BootUp` → `title` → `politic`）。

对 Stub 的含义：**不能按「一个请求换一个请求」实现启动流程**，必须按场景批次：`tableLoad`（1 个）→ `bootup`（1 个 + 首登补建 3 个）→ `title` → `politic`（一批）。

## 关键事实二：回调扇出（一次响应连发多个请求）

出度最高的端点：

| 端点 | 出度 | 说明 |
|---|---|---|
| `quest/getQuestProgress` | 14 | 任务进度带动 raidboss、select characters、debug 系列 |
| `ranking/getBriefOfRaidBossDaily` | 13 | 排行榜各分页互相预取 |
| `ranking/getRankersInStrategy` | 13 | 同上 |
| `politic/mission/getStatesFromAllMissions` | 9 | 内政总览带动建筑/诏令/巡查/水运 |
| `deck/getDecks` | 8 | 卡组页拉起人物/装备/头像/保护列表 |

这意味着 Stub 里必须允许「同一帧内多个端点并发返回」，且这些端点之间没有强顺序依赖（客户端用回调聚合，不阻塞主流程）。

无入边的 8 个端点（真正的手工入口，不会被别的端点触发）：

```
auth/createPlayer        debug/debugLogin        debug/devLogin
mailbox/getMailBody      politic/map/setMapName2
politic/waterborneTrade/send  siege/discharge  turfWar/getTurfWarResultLog
```

## 关键事实三：哪些键真的驱动分支

67 个端点的响应键出现在 `if (...)` 条件里，是真正的分支开关（其余键只是取值显示）。典型：

| 端点 | 守卫键 |
|---|---|
| `auth/gameLogin` | `certifiedInternetCafe`、`container` |
| `battle/getRivals2` | `bots` |
| `deck/getDecks` | `0`（另有 `siege` 等字面量比较） |
| `politic/mission/getStatesFromAllMissions` | `missions` |

完整清单见 `behavior_contract.tsv` 的 `guarded_keys` 列。

## 抽取保真度

650 个调用点里：

| 情况 | 数量 | 影响 |
|---|---|---|
| 精确定位到方法体 | 650 | 副作用字段可信 |
| 只定位到类体（退化） | 0 | 修正修饰符正则后已消除 |
| 完全定位不到 | 0 | 补上子目录后已消除 |

修正前后对比（同一批源码，仅抽取口径不同）：

| 口径 | 边 | 有出边端点 | 窗口 | 状态写入 | 键守卫 | 场景端点 |
|---|---|---|---|---|---|---|
| 旧：单修饰符正则 + 整类体退化 + 只扫顶层 | 416 | 110 | 40 | 18 | 68 | 10 |
| 中：多修饰符正则，仍只扫顶层 | 388 | 103 | 37 | 16 | 67 | 9 |
| 新：多修饰符正则 + 递归扫 2034 个文件 | 388 | 103 | 37 | 16 | 67 | 9 |

> 说明：上面两行是当时快照。补录 3 个漏记调用点（`friend/getFriendMapData`、`politic/map/setMapName`、`turfWar/receiveTurfWarReward`）后，同口径重跑为 392 条边 / 106 个有出边端点；正文计数已按重跑值更新。

第二段差额是旧正则误退到整类体时混入的同类其它方法调用。第三段补的 537 个文件（`PoliticBuildingState` 等）里只有状态机类，命中 4 个此前漏掉的端点（`friend/task/completeFriendTasks`、`politic/task/completeTasks`、`politic/task/progressBuildTask`、`politic/task/submitProduceTask`），它们的方法体只调 `RpcQueue.reliable`，不产生新边，所以边数不变。

## 表列定义

| 列 | 含义 |
|---|---|
| `endpoint` | 端点 |
| `matched_sites` | 定位到方法体的调用点数 |
| `scene_ops` | 触发的场景切换 |
| `windows` | 触发的窗口操作 |
| `service_calls` | 调用的服务（去重，最多 8 个） |
| `state_writes` | 写入的静态/缓存状态 |
| `guarded_keys` | 出现在 `if` 里的响应键（最多 12 个） |
| `chained_endpoints` | 该方法体里一并发出的其它端点 |

## 已知局限

1. 只做语法级抽取：`transitionScene` 的实参如果是变量、或场景切换发生在协程 `yield` 之后的分支里，抓不到。
2. 650 个调用点全部定位到方法体，无退化、无未定位。
3. 嵌套 lambda 内的 API 调用能被抓到（同一方法体文本），但跨方法传递的 delegate 抓不到。
4. 本表不判断「效果是否成功」的运行时分叉，只给静态证据。
