# API 端点契约（api_contract.tsv）

从 `OniSoul_Setup_20140712.exe` 内 `app.unity3d` 的 `Assembly-CSharp.dll` 反编译源码中静态抽取，未经运行验证。

## 表结构

`api_contract.tsv` 共 402 行（一行一个端点），列定义：

| 列 | 含义 | 取值示例 |
|---|---|---|
| `endpoint` | 线上路径，等于 `httpCall` 字面量 | `auction/auctionCardSearchName` |
| `api_methods` | 发出该端点的 `WebApiClient` 方法，多方法用 `\|` 分隔 | `dedicateBuilding\|dedicateGold` |
| `request_params` | 请求参数键（`params` 内的键），多方法时为**并集** | `article,category,token` |
| `request_template_keys` | 序号拼接的模板键 | `character_id<N>` |
| `request_constants` | 参数取字面量常量（JSON） | `{"category": ["building","character"]}` |
| `response_keys` | 客户端回包读取的键，`;` 分隔，`键:类型`，`*` 表示被 `ContainsKey` 保护 | `succeeded:bool;container:string*` |
| `key_count` | `response_keys` 条目数 | `3` |
| `call_sites` | 调用方类.方法 | `BootUp.login` |
| `call_count` | 调用点数量 | `1` |

响应类型来自 `(bool)` / `(string)` / `(int)(double)` 这类显式 cast；无 cast 证据的键不带类型。

## 覆盖统计

| 指标 | 数量 |
|---|---|
| 端点总数（= `httpCall` 唯一字面量） | 402 |
| 已抽出响应字段 | 278 |
| 被调用但回调体不读命名键 | 45 |
| 本客户端从不调用（无调用点） | 79 |
| 唯一响应键 | 382 |
| 带类型响应键 | 250 |
| 带可选标记（`ContainsKey` 保护） | 57 |
| 一端点多方法（参数取并集） | 10 |
| 带序号模板键的请求 | 4 |
| 带常量枚举的请求 | 14 |

## 抽取手段

字面量正则只能覆盖最简单的写法，实际补了十五类（其中「模型构造传参」经实测 0 命中、予以排除）：

1. **命名参数**：`getAuctionCards(p_responder: OnGetAuctionCards, ...)`，需剥掉 `name:` 前缀。
2. **同类裸调用**：`OnGetAuctionCardsCommon(p_payload)`，无接收者，按当前类解析。
3. **泛型单例接收者**：`Singleton<UserStatus>.Instance.updateKokudaka(result)`；最初只认 `ServiceLocator<T>`。
4. **赋值闭包（污点传播）**：`hashtable3 = hashtable2["possessionLimits"]` 后 `setUpCharacter(hashtable3)`，从载体派生的局部变量也算载体。
5. **成员字段接收者**：`desc_.setup((Hashtable)result)`，靠字段声明 `private siegeBriefMenuDesc desc_;` 把接收者映射到类型。
6. **静态字段跨类传递**：`LoginBounusMenu.LoginHash = (Hashtable)result;`，真正的读取发生在另一个类的属性 getter 与 `UserStatus.addLoginBounus` 里。这类写法让 `common/getLoginStampSheet`、`common/stampLoginSheet` 一度被误判成「不读字段」，见 `verify/static_field_keys.txt`。

7. **成员字段承接**：`charactersTable_ = (Hashtable)result;`，键在同类其它方法里读（`charactersTable_["id"]`），见 `field_keys.tsv`。
8. **属性 setter 承接**：`deckScene_.StorageInfoHash = x;`，setter 里 `storageInfoHash_ = value` 之后立刻读键。
9. **常量键**：键名是 static 字段（`storageExtendSlotKey_g`），值在别处声明，需先建常量表再解析。
10. **`HashAccessor` 访问器**：`getInt("sellPrice")` / `getHash("characterIds")`，正文里没有 `["k"]`。
11. **`HashAccessFuncs` 路径读键**：`getInt(hash, "myRecord", "rank", -1)`，两个字符串是**父子键**，落表时记作 `myRecord.rank`。
12. **方法组引用**：`WebApiFunc v = client.getRankersInBattle;`，委托存进 Hashtable、按 span 取出后才 `v(...)` 传入回调。
13. **responder 变量 / 跨帧**：`WebApiClient.Responder response = delegate(object result){...};` 定义在别处，由另一个 lambda 传出，按变量名与形参回溯最多 3 层。
14. **外层动态 id + 内层固定字段**：`foreach (x in hash.Values)` 后包 `HashAccessor`，内层读 `amount`，落表记作 `<id>.amount`，外层键本身是数据 id、服务端可自由决定。
15. **模型构造传参**：`new Xxx(result)` / `Xxx.Parse(result)` 这路**实测 0 命中**，此写法在本客户端不存在。
16. **全局唯一方法名兜底 / 最内层同类解析**：接收者类型推不出时，按方法名唯一性或最内层类作用域解析；前者补出 1 个，后者 0 命中。

递归深度上限 4，带环保护与 memo。多数响应字段不在回调体里读，而是 result 被转发后再读，必须做「result → 参数 → 下游方法」递归才能取到。

## 校验（`verify/`）

| 校验 | 方法 | 结果 |
|---|---|---|
| 端点完整性 | 契约↔源码字面量双向对账 | 402↔402，0 差；唯一非字面量命中是 `private void httpCall(string api,...)` 方法定义本身 |
| 方法归属 | 花括号配对定位方法体 | 445/445 个真实方法全部定位（另 6 个 `public delegate` 声明非方法） |
| 参数正确性 | 用方法体重算参数并集，与表对比 | 差异 6 项，已全部修正（见下） |
| 字段真实性 | 990 个键逐个回查源码字面量 | 0 个找不到（见 `verify/final_check.txt`） |
| 类型自洽性 | 同一端点内的声明类型 vs 实测 cast | 492 处带类型读取，0 冲突 |
| 表结构与编码 | 9 列齐整 / UTF-8 无 BOM / 仅 LF / 无重复端点 / `key_count` 与条目数一致 | 全部通过 |
| 键名一致性 | 回包键不得与同端点请求参数同名 | 5 例经核对为**回显读取**（客户端读回自己发过的值），非错误 |
| 方向一致性 | 键必须出现在「回包路径」而非「请求构造路径」 | `politic/waterborneTrade/send` 两处疑似请求侧复用，已排除未并入 |
| 旁路通道 | 扫 `new WWW(`/`WWWForm`/`TcpClient` | 见下节，不属于本表 |

## 修正过的三类缺陷

1. **一端点多方法**（10 个）。原先按方法名归并，只取到一个方法的参数。典型：
   - `battle/executeBattle` 由 10 个方法发出（`executeBattle`、`...Monster`、`...NPC`、`...Player`、`...Quest`、`...RaidBoss`、`...Siege`、`...Strategy`、`...OutBreak`、`...GiganticRaidBoss`），此前漏了 `buildingId, command, difficulty, encountId, entry, monsterId, npcId, questType, requestPhase` 9 个参数；
   - `common/dedicate` 由 5 个方法发出（character / building / tactics / equip / gold）。
2. **同一方法按分支发不同端点**：`getFriendMapData` / `getFriendMapData2`、`setMapName` / `setMapName2`。原先以方法名为主键，第二个端点被吞掉，端点总数因此少 2。
3. **模板键被当成字面量键**：`hashtable.Add("character_id" + num, ...)` 实际发出 `character_id1..N`，`skill_id` 同理。

## 常量枚举（Stub 必须按此校验，不能任意填）

```
common/dedicate                category: character|building|tactics|equip|gold
battle/executeBattle           battleType: ATTEMPT_BATTLE|BOSS_BATTLE|NPC_BATTLE|PLAYER_BATTLE|
                               QUEST_BATTLE|RAIDBOSS_BATTLE|SIEGE_...|GIGANTIC_RAIDBOSS_BATTLE
battle/getVsBattleLogs         type: strategy|turfWar|vs
battle/getTurfWarReplayData    type: turfWar
trophy/completeTrophy          access: mypage|raidBoss|giganticRaidBoss
trophy/getTrophyProgress       access: mypage|raidBoss|giganticRaidBoss
trophy/messageWindowTrophy     access: mypage
ranking/getRankersInNationalRanking  rankingPeriod: all|weekly
giganticRaidBoss/getGiganticRaidBossEventResult  term: current|last
politic/map/getMapData         assets: map0
quest/executeQuestEx|Ex2      assets: map0
quest/checkEmergencyQuest      questType: event3
debug/debugLogin               username: debug
```

## 嵌套键（未进表，需按结构返回）

原始抽取只记录顶层键，某些键的值是 Hashtable，其子键在源码里按下标或拼接读取。已核实两组，注意二者**不是同一回事**：

### 签到奖励（`common/getLoginStampSheet` / `common/stampLoginSheet`）

```json
{
  "stampCount": 3,                       // 已签到次数，1-based
  "nextStampDate": "2014-07-13T4:00:00+0000",  // 格式 "yyyy-MM-ddTH:mm:ss+0000"
  "loginSheet": {
    "day1": { "itemId": "item11_0000001", "amount": 1 },
    "day2": { "itemId": "...", "amount": 2 },
    "day3": { "itemId": "...", "amount": 3 }
  }
}
```

依据：`UserStatus.addLoginBounus` 先 `ContainsKey("stampCount")` 与 `ContainsKey("loginSheet")` 双判空才继续，再 `int num = (int)(double)hash["stampCount"]`、`hashtable = (Hashtable)hash["loginSheet"]`、`"day" + num` 取当天条目、子键 `itemId`(string) / `amount`(int) 后 `RewardProcessor.process`；`UserStatus.updateLoginStamp` 读 `nextStampDate` 并用 `DateTime.ParseExact`，格式串写死为 `yyyy-MM-ddTH:mm:ss+0000`（注意 `H` 是单字母格式符）。

客户端侧 `LoginBounusMenu.TodayItemId` 用 `hashtable.Count + 1` 反推今天该签第几天，因此 `loginSheet` 里**只应放已签过的天**，未签的不要预置。

### 攻城战三日简报（`siege/getBrief`）

```json
{
  "day": 1, "stage": 1, "isEntry": true, "role": "attacker",
  "winner":   { "day0": "attacker", "day1": "defender", "day2": "none" },
  "attacker": { "0": "country02", "1": "country08" },
  "defender": { "0": "country01" }
}
```

`stage` 取 0/1/2 → `SiegeCategory.One/Two/Final`；`winner.day0..2` 是三天各自的胜方（`Winner[3]`，缺省 `"none"`）；`attacker` 键是数字字符串 `"0"/"1"`（两个攻方国家），`defender` 键是 `"0"`（一个守方国家），缺键退化为 `""`。

`siegeBriefMenuDesc.setup` 里 `Winner[i] = (string)hashtable["day" + i]`（i<3）、`Attacker[j]`（j<2）、`Defender[k]`（k<1）。表里这几个键标为 `Hashtable`，子结构以此处为准。

## WebApiClient 之外的网络通道（不属于本表）

| 通道 | 位置 | 说明 |
|---|---|---|
| 资源下载 | `Loader` / `SimpleLoader` / `StanderdLibrary` / `MoviePlayer` / `SoundPlayer`，`new WWW(` 13 处 | GET 资源服，host 取自配置 `asset` |
| 截图上传 | `SnapshotUploader.cs`，`WWWForm` 5 处 | POST 到 `imageUploderURL_g`（外部 PHP，非本游戏服务端） |
| 聊天 | `Irc.cs`、`Proxy.cs`，`TcpClient` | IRC 长连接，非 HTTP |
| 引擎 | `WWWObject.cs` | PlayMaker 侧对象 |

## 已知缺口

零字段端点共 124 个，逐个给出处置，全量清单见 `verify/no_key_final.txt`：

- **79 个无调用点**：`app/` 内不存在 `.方法名(` 的调用点，只有 `WebApiClient` 自己的包装方法，说明本客户端从不触发。契约参数取自 `WebApiClient` 方法本身。
  （注意：早期口径按「`httpCall` 站点数」判定被调用，把包装方法算进去了，因此曾误报为 55 个。）
- **45 个有调用但不读命名键**，五种形态：
  - `iterates_no_key_name` 5：`foreach` 遍历后取 `item.Key` 当数据 id（如 `deck/getProtectedCharacterIds`），外层键名由服务端决定；
  - `hands_to_callee` 12：原样交给下游方法（`resetItems` / `createPlayerData` / `getQuestProgress` / `cancelWaterTrade` 等），已追一层仍未读到键；
  - `responder_elsewhere` 15：回调体在另一栈帧构造，追 3 层未及；
  - `null_check_only` 3、`count_only` 1、`ui_only` 1、`other` 9：只判空、只取 `.Count`、只喂 UI。
  - 这 45 个回 `{}` 不会导致崩溃（客户端不做命名读取），但会导致**界面为空**，属运行验证可确认的残余项。
- **模板键的响应侧**：`hashtable["day" + i]` 这类已按上面「嵌套键」处理；其余 `*TableAccessor` 里的动态键读的是**配置表**，不是回包，未列入。
- `friend/getPlayerEntry` 方法发出的是 `common/getPlayerEntity`，名称不一致，原文如此，未改动。
- 上述「未读字段 / 未调用」均为静态结论，要变成确定结论只能靠单次启动实测或类型级数据流分析。

## 重跑

前置条件：本地已有反编译产物 `analysis_full/il_csharp/app/`（2034 个 .cs）与 `api_contract.tsv` 的方法表。

```
python a_api_exhaustive.py     # 抽响应字段 → api_contract_final.tsv
python a_contract_v2.py        # 参数并集 + 模板键 + 常量 → api_contract_final_v2.tsv
python a_static_fields.py      # 静态字段跨类传递 → static_field_keys.tsv
python a_verify_endpoints.py   # 端点完整性
python a_verify_channels.py    # 旁路通道
python a_verify_params.py      # 参数重算
python a_verify_types.py       # 类型自洽
python a_verify_dynkeys.py     # 动态键
python a_static_fields.py      # 静态字段跨类传递
python a_field_keys.py         # 成员字段承接
python a_haccessor.py          # HashAccessor 访问器
python a_haccessfunc.py        # HashAccessFuncs 路径读键
python a_methodgroup.py        # 方法组引用
python a_responder_var.py      # responder 局部变量
python a_responder_flow.py     # responder 跨帧回溯
python a_inner_keys.py         # 外层动态 id + 内层字段
python a_final_disp.py         # 零字段端点处置表
python a_final_check.py        # 推送前完整性检查
```

反编译：`dotnet tools_ilspy\cmd\tools\net8.0\any\ilspycmd.dll -p -o <outdir> container_dump\Assembly-CSharp.dll`
