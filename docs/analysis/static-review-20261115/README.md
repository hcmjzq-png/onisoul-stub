# 安装包样本静态复核（2026-11-15）

本轮先做静态分析，没有启动或操作客户端，也没有向游戏服务器发请求。
分析覆盖安装包样本中全部 402 个端点，包括当前 379 个默认 handler；
全量自动扫描之后，对差异、主城、任务、编队与关卡的关键路径进行了人工源码复核。
这不等于 402 个接口的原服务端实现已经恢复。

## 来源链重新建立

直接用 innoextract 从用户提供的 `OniSoul_Setup_20140712.exe` 提取
`app/cache/data7/d/kbeizo6m.d`，取出其 HTTP 记录中的 `app.unity3d`，
解压并按容器目录提取 DLL。没有使用旧工程反编译源码作为本轮依据。

| 样本 | SHA-256 |
|---|---|
| 用户提供的安装包 | ad34a14e3dd67b30c59d5abd9ed2a82b2ab53161e24f3be654a63175e6d890ad |
| 缓存中的 app.unity3d | a374083f4662a5e3d2480058cbd2712d43c29035699b8d453dd749d19a45e9ce |
| Assembly-CSharp.dll | b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e |

安装包内样本与仓库已有程序集清单一致，重新反编译产生 2,034 个 C# 文件。
“原始”在这里指本次直接从用户提供安装包取得的样本；文件名为 original 的旧工作文件不自动可信。
完整提取记录、解压容器哈希、关键源码哈希和 IL 校验计数见 `source-proof.json`。

## 全量结果

| 项目 | 本轮结果 |
|---|---:|
| MethodDef / 有方法体 / 严格解码失败 | 26,688 / 25,174 / 0 |
| 解码指令 | 677,346 |
| HTTP 调用点 / 唯一端点 | 433 / 402 |
| GET / POST 调用点 | 1 / 432 |
| 有 IL 直接调用或委托引用的端点 | 350 |
| 当前默认 handler 中有上述引用 | **327** |
| 当前默认 handler 中没有找到上述引用 | **52** |
| 专用 handler | 23，全部有上述引用 |

初扫时只计外部包装方法，得到 325/54；继续追踪 WebApiClient 内部调用与嵌套委托后，
最终修正为 **327/52**。这是本报告使用的最终口径。

52 条不能直接当作“无用接口”：反射、Unity SendMessage、浏览器和序列化场景事件绑定不完全体现在
普通 IL call 中。350 条有引用也不证明相应代码在当前账号和 UI 状态下可达。

与旧记录相比，已确认这些调用归属问题：

- `common/getResources` 的旧调用依据混入了同名 `TableAccessor.getResources`；后者读取资源表，不是 HTTP API。
- `politic/map/setMapName` 两参重载没有找到调用；用户改名路径调用三参重载 `/setMapName2`。
- `ranking/getBriefOfTurfWar` 与 `/getBriefOfTurfWarDaily` 有 `ldftn` 委托引用，普通文本调用搜索漏掉了它们。
- `debug/debugCreateQuestEncount` 的 HTTP 发送位于嵌套回调；此前它还先调用 `common/getPlayerEntity`。

## 已经能由静态证据定位的问题

### 1. 编队响应缺少必读层级

`PlayerDeckCache.getDeckAllCharactorIds`（新反编译源码第 140 行）直接取
`attack["0"].ids`、`defense["0"].ids`、`politic["0"].ids`。
当前 `placeholders.payload("deck/getDecks")` 没有 attack/defense/politic，进入该路径会访问缺失对象。
即使只补空表，`process` 第 103～131 行也可能因空 ID 集合不发 getSelectCharacters，继而持续等待 Characters。

后续应以玩家持有武将和保存的编队生成一致数据，并同时处理
`common/getCharacters`、`common/getSelectCharacters` 和 `deck/setDecks`。
这些方法的读取关系已能静态确定，不需要通过试填字段来猜。
其他回调所需的武将属性仍要合并审查；不能把这里只见到的 baseId/grade 当作完整角色结构。

### 2. 默认活动键改变客户端分支

`StatusView.setupEventInformation` 第 480 行起按 turfWar → strategy → siege → giganticRaidBoss 的顺序分支；
第 555 行 `isEventOpen` 只判断键是否存在。当前默认 handler 为四项全都生成对象，
即使其中 status 为空、时间为零，仍会进入活动存在的分支。
静态证据能确定“未配置活动时不应制造活动键”，不能确定原服活动开放日程和结算规则。
这与用户指出的九项不可信旧实现有关，旧活动实现不可直接迁入。

### 3. 任务状态上报不是服务端完成条件

`WebApiClient.cs:1671` 支持单任务 missionId/state 与批量 missionIds/states 两种请求。
`PoliticMissionProgressList.makeUpdateStatusList` 第 1199 行起组装请求，回调读取
`mission.<任务ID>.reward`，另有可选 toInbox。
`PoliticMissionProgressStatus.sendUnlockOperation` 第 408 行起使用系统任务、indexes=[0] 和解锁位值。

当前 `app/business/gameplay.py:730` 会接受已知任务的新状态，并在首次 closed 时发奖励；
没有在此处核验合法前序和实际完成条件。客户端的条件检查可作为重建条件语义的证据，
不能替代服务端状态校验。当前奖励选择的概率与原服是否一致也不能仅由客户端证明。

### 4. 关卡不是一个“返回成功”的接口

`PluginRunner_DoEvent.cs:83` 起展示一条可追踪的调用链：getChapterData 读取 clearCount，
openQuest 读取 questIds，executeQuestEx 读取 executeInfo.step 并按区域表消耗行动点，
随后进入事件处理和 checkCompleteQuestEx，再合并奖励。
它证明了一条插件消费者路径，不代表所有手动关卡入口完全相同。
相关接口须共享进度、行动点和奖励状态；原服务端事件概率与结算事务无法从这条客户端链条独立还原。

### 5. 两张缺表的优先级不同

- `ComboTableAccessor` 在本次反编译源码中只有定义，未找到其他显式引用；暂未证明主线需要它。
- `StrategyLogManager.cs:1342` 的 setBattleField 确实调用 StrategyBattleFieldTableAccessor.getCatalogId，
  上游是 `StrategyResultWindow.cs:21` 的 setup。不能继续把 strategy_battlefield 当作完全未使用的表。
- 这只能确认表的使用点，不能从访问器恢复缺失的原始记录；空表和 catalogue 表不能冒充它。

### 6. 原契约仍有漏抽与误归属

本轮 Hashtable 写入候选比较产生 8 组差异，逐项复核见 `request-candidate-verdicts.tsv`：
3 组为嵌套键、3 组为条件分支误报、1 组为构造器模拟漏报，只有嵌套回调的调试接口是已确认的旧请求缺口。
其请求字段为 info/playerId/questType/token，questType 固定 story。
该接口的旧响应键字符串 ` + name + ` 也不能当作真实字段；实际消费者用 getInt 读取 encountId。
补充证据见 `contract-amendments.tsv`，尚未据此改动服务端响应。

## 九项旧实现的处理

支城、密书箱、收件箱、国战、城战、公会战、排行榜、收藏品、武具强化：
继续按用户警示，把相关旧业务实现视为不可信。安装包中可见某个类、按钮或 API，
只说明客户端有相应代码，不能据此认可旧模拟服务器的功能实现。

例如 `HTMLMailBoxMediator.cs:39` 会调用浏览器 startMailBox，后续还经过 reseiveMessage 与 HTMLMailCore；
这是原样本里的跨 Unity/网页边界证据，不能用此前自制的单一窗口流程替代原流程结论。
网页侧资料或绑定缺失时应补取来源再分析，确实无法静态确认的部分才做运行观察。

## 静态边界与后续验证清单

| 问题 | 静态已知 | 下一步手段 |
|---|---|---|
| 编队、活动响应的结构与键存在语义 | 已定位上述必读路径 | 可先据证据修复，然后真机验收 |
| 新号引导何时实例化、哪个条件先触发 | 状态机和调用存在；实际场景/玩家状态有关 | 修复已知问题后，用新号观察任务 1～4 和重登 |
| 九项入口的实际按钮绑定、网页桥接 | DLL 中能看到部分方法；完整资源绑定未覆盖 | 先补查原场景/原网页；资料不足才运行并记录调用 |
| 重建角色包在 Unity 3.5 中实际显示 | 文件、贴图和下载已在上轮验证 | 进入对应角色画面观察 |
| 旧契约 142 个默认接口含无类型响应键 | 目前仍有未定型或辅助方法读取 | 继续跨方法静态追踪；无法定位的才定点运行观察 |
| 原服概率、经济平衡、服务端防重和并发事务 | 客户端只能提供部分约束 | 需要原服记录/原始数据；跑当前 stub 也不能证明原规则 |

因此本轮不需要为了定位上述确定问题而立即跑客户端，也没有把所有未实现接口都列成运行测试项。
当前默认接口仍为 379。本轮成果是证据和实现顺序，不是接口补完声明。

## 产物与复现

- `endpoints.tsv`：402 条端点逐条审查索引，含当前 handler、IL 引用、包装方法签名、既有字段与候选差异。
- `direct-callers.tsv`：642 个调用/委托引用点，包含外部客户端与 WebApiClient 内部来源。
- `request-write-candidates.tsv`：1,086 条 Hashtable 写入候选，**不是可以直接用于回包/请求校验的完整字段表**。
- `summary.json`：最终计数、52 条未发现直接引用的端点以及分析边界。
- `source-proof.json`：样本链和复跑一致性。

新清单的偏移均是独立 DLL 的文件偏移；旧分析 TSV 的偏移是解压容器绝对偏移，
本样本换算为旧偏移 = 新偏移 + 1,474,648。不能混用两种偏移。

```powershell
python tools/verify_il_bodies.py work/static-review-20261115/app_unity3d.bin --json
python tools/audit_client_endpoints.py work/static-review-20261115/Assembly-CSharp.dll --out docs/analysis/static-review-20261115
```

审查工具在分析前核对程序集 SHA-256，不接受与仓库 PC 清单不同的 DLL。
包装方法 CLR 签名部分无法被现有元数据解析器解析时保留 `?`，不能据此推断 JSON 类型。

已有 HTTP 方法、回调扇出、键类型、无守卫读键、响应形态六份产物复跑后逐行一致。
其中 response_shapes 工具仍依赖人工维护的 21 条裸映射覆盖，其余 381 条是默认形态判定，
一致性不等于每条响应形态和业务含义都已独立证明。
回调工具的 507 条记录中只有 217 条解析到具体 responder；其余包含方法参数或字段传递边界，
同样不能据产物存在就宣称所有回调都已追踪到底。142 条默认接口含有既有未定型响应字段，
这部分仍应先继续静态追踪，不能一概认定必须运行客户端才能分析。
本轮未更改运行时契约 TSV、业务代码、云端服务或玩家数据。
