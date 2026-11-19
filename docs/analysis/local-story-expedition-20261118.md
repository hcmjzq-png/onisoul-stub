# 鬼物语原版 PC 出阵取证 · 2026-11-18

当前成果在独立回环验收服务复现。以下按时间保留取证与验收过程。资源包、存档、客户端截图和本机连接配置留在验收机。

本地测试服已撤下临时出阵面板，恢复此前的 PC 主包与原场景跳转。网关返回的主包 SHA-256 为 `593f03e241a9f9f7c3fa9939b3df9eb87f86e50b662093484f71af0027b9ed23`；临时页面与两个 `localStory/*` 接口均返回 404。15 个此前补好的收集图标原样保留。已打开旧版的进程需要完整退出重开才能卸载其内存中的程序集。

截图作为真机验收参照：原版「探索」按钮、队伍、关卡进度、右侧「获得物」，以及简易自动/完全自动入口。截图来自公开视频、帖子或旧截图线索，未附带可提取的客户端缓存。国服表中启用了 9 篇、41 章及 401 区域。

## 资源缺口

| 原版入口 | PC 资产键 | 核对结果 |
|---|---|---|
| `quest` | `scene/9af398d6690a6b65145bb21a3c61ac43.unity3d` | 找到 PS3 原包，已生成 PC 移植候选（未部署、未真机验收）；没有找到原生 PC 包 |
| `questAssets` | `scene/4313f662f5b84d1790d4e7f1836b45ad.unity3d` | PS3 找到原包；已移植首批 HUD/提示特效所需的 8 个预制件，非完整原 PC 包 |
| `stq0_main` | `stq/da83c61a24cb68a768ad88bcaa95fc05.unity3d` | 未找到必需的 `stq0_main_01` 和 `stq0_main_01_stringtable.json` |
| `stq0_100010` | `stq/7791537fac4c803514f42a1fb4edf408.unity3d` | 未找到首章开场和后续探索事件的脚本组 |
| `stq0_300001` | `stq/6860e792eb792a8c23dafd94d81ad50e.unity3d` | 未找到首章第 6 步事件脚本 |

这些路径在本地均为 `stub has no assets`。原版 `QuestSelectFrameTransition.onAreaSelectNext` 先切入 `quest` 场景，客户端在这里请求五次 404，没发出步进；`Quest.setup` 在场景进入后运行开场脚本，`Script.Interpreter.load` 需要脚本及对应的文案 TextAsset。本机 `_server/client/pc/jp/assets/scene` 的同名包实际是平台 10；`work/build` 中的 Android 包只有 32 字节的 `QuestHUDController`，而 PS3 原文件对应对象为 128 字节，不能直接作为 PC 包上线。`work/recover_all` 的平台为 13 但序列化仍是大端。

核查范围：原安装包的 Qt 缓存、本机 WebPlayer Shared 缓存、本机档案与恢复副本、本地服务资产和工作树生成物。重点 PC 缓存结构盘点了 425 个条目、267 个可读不同资产，未发现完整 PC 候选。扩大搜索了 19,375 个不同的 UnityWeb 包，以内部场景名和开场脚本标记作预筛（个别格式错误或超出分析大小限制，不能据此断言任何副本都不存在）。`<archive>/10-原版客户端/data.dat` 的 SHA 与[已验证的随机填充](data-bin-verification.md)一致。原 CDN `client-onisoul.86joy.com` 的公开 DNS 查询返回 NXDOMAIN；Wayback CDX 对国服及原程序集声明的 Mobage、Mixi 资产域名的三个目标键及修订参数通配查询均无 HTTP 200 记录。

本轮复核直接从原安装器的 `cache/data7` 取出未修改的国服 `app.unity3d`。包内 25 个条目（含 `mainData`、`level0`–`level4`），逐对象盘点：`resources.assets` 中的 `assetbundle.json` 明确把 `assets/scene/quest.unity3d` 和 `assets/scene/questAssets.unity3d` 列为独立包，主包没有出阵场景或开场脚本的 TextAsset。程序集里的 `stq0_main_01` 是加载名，实际由解释器另取脚本和文案。安装器的 159 条 Qt 缓存中有 128 个 CDN 资源包；逐包检查了 1,161 个 TextAsset。场景组有平台 7 的 `BuildPlayer-questSelect`（选关），没有 `BuildPlayer-quest`（出阵）；无 `stq0_*` 脚本。也检查了同缓存中的 `scriptAssets`，未见目标脚本。结论只适用于这份安装器、主包和本机已核对的缓存，不排除其他玩家的原服缓存。明细：`<qa-root>/ps3-quest-port/original-pc-app-audit.json`。

新缓存可用 [审计器](../../tools/audit_pc_story_cache.py) 只读检查；需要 UnityPy。报告区分 PC 布局、内容完整性与原包来源，候选仍需原客户端验证。优先找当年实际进入过鬼物语探索的 PC 客户端的 `cache/data7` 或 Unity WebPlayer 的 `Cache/Shared` 备份。

## PS3 主场景移植试验

- 从提取的 PS3 安装文件直接核对 `quest`、`questAssets` 及其战斗特效依赖，三包与 本机归档字节一致。没有使用丢失 HUD 字段的安卓移植包。
- [移植工具](../../tools/port_ps3_quest_scene.py) 把主场景转换成 PC UnityWeb v3：以现有 PC `questSelect`、`globalAssets` 的类型和资源为基准，逐字段处理大端数据，按 PC 程序集更新组件标识，重连原有字体、材质和按钮。转换了 32 个场景网格和两张 HUD 贴图。解包预览能看到中文「探索」「获得物」以及自动探索的图块。
- 主场景 247 个、共享文件 15 个对象通过结构回读；保留 HUD 的 13 个绑定字段，确认 `Quest` → HUD → 「探索」按钮及 `questAssets.unity3d` 的引用。重复构建哈希相同（SHA-256：`4edfea4159f9eb6df7c5e7a7a03a64d12c7afd17f14401325f23c69df911f896`）。候选包及报告位于 `<qa-root>/ps3-quest-port/rebuild-check`。
- `questAssets` 另有 798 个对象，含 82 个脚本组件、自动探索按钮和战斗粒子特效；其特效材质所指的外部节点 `CustomAssetBundle-3e876c123e40ffc4194f33f182af40c1` 已定位到 PS3 原包 `801689503012efa6d492ec49dfca6918.unity3d`。其余配套包的字段和引用仍需转换。PS3 已提取的 `Media/Raw/assets` 只有 `scene`、`vse`，没有找到原开场和事件的 `stq` 包。
- 未在运行中的服务安装候选包。UnityPy 回读不能替代 PC WebPlayer 验收；需在隔离测试中加载原生场景，取得并验证资源和脚本后，再用「探索」验证推进、物语点数和奖励入库。

## 原生探索的配套资源

用户提供的外部复现说明与本地资源盘点一致：原版 PC 选关照用，探索主场景来自 PS3 移植，按原客户端路径加载；缺失的剧本用原 PC 脚本指令编写流程，原剧情对白仍缺。对方报告涉及隔离档中的原生客户端验证，未收到其场景构建物或流程脚本，未把其验收当作本机结果。

- [配套包移植工具](../../tools/port_ps3_quest_prefabs.py) 从 PS3 `questAssets` 取出 8 个原预制件：两个自动探索按钮、提示确认窗、上下遮罩、物品图标框、图标图像、探索按钮和遭遇提示特效。根据 PS3 原包的 preload 表保留 345 个对象，并用 PC 场景脚本和共享包重连字体、着色器、动画及组件。重新解包核对了路径、预加载引用、对象数据及 3 张贴图的像素。候选位于 `<qa-root>/ps3-quest-port/prefabs-checked`；未部署、未在 WebPlayer 验收，也不包含完整的战斗或宝箱特效。
- 原安装器缓存内确实有 PC 原生 `quest_layout`（`scriptAssets` 的 GameObject #34）。它是剧情布局，不是缺失的出阵场景或 XML。流程脚本可通过客户端已有的 `loadLayout` 使用它，再调用 `quest_start`、`quest_QuestButtonWait`、`quest_stepNext`，按事件调用奖励或战斗流程，返回仍走 `quest_transitionQuestSelect`。写入口需要将同一次点击的操作 ID 贯穿客户端重试与服务端结算，不能拿收到请求的次数当点击数。

## 已补齐的后续依赖

从原关卡表的 `bgImage` 取得 `qbg3_0017_01`、`qbg3_0018_01`、`qbg3_0019_01`；用 本机同名 512×512 原画及原 PC 单纹理模板生成 PC 包。保留原图尺寸、名称，UnityPy 回读验证，`assets` 与 `assets2` 两条路径的实际下载哈希均一致。它们是重打的纹理包；未把它们标成原版场景包。

从已固定指纹的原始表容器提取 `monster_story_1`，按原 TextAsset 名、偏移、哈希和 722 行校验后部署本地。使用已部署的表在隔离存档中验证前五步：一步一点、第 3 步发前田豪姬、第 4 步发阵笠、第 5 步记录待处理遭遇，重试没有再次扣点或发奖。

`quest/executeQuestEx` 的原客户端请求无操作 ID 或期望步数，而且原客户端收到奖励增量会用于更新本地状态。原生入口接通前不把该写请求直接绑定到步进，以免断线重试误扣或误发。战斗结算和章节完成奖励尚未接通；本次没有原版真机通关验收，也没有向正式服部署。

## PC 客户端隔离验收

- 在 127.0.0.1:18119 的独立数据库验证了第一章前四步。测试档只预置城下町的物语解锁，进度、点数和奖励均由原生探索按钮触发的 `quest/executeQuestEx` 写入。
- 修复了 `questAssets` 的对象 ID 排序。旧包 HTTP 返回 200，但 Unity 3.5 读不到自动探索按钮、物品图标等预制件。重新构建的包与真机验证使用的包字节一致。
- 重建的开场流程通过 `quest_layout` 的背景层显示 PC 背景，按关卡表在第三步更新背景。进度从 0/10 到 4/10，物语点从 25 到 21。第三步发前田豪姬 1 张，第四步发阵笠 1 个。隔离存档中的武将、本地道具和选关收集标记均已核对。
- 隔离档主将的 `cch/f3eaafecee830797b986b70b2b16ee08.unity3d` 返回 404，因此出阵场景中缺少该立绘。首次战斗、后续章节和原版对白尚未接通。验收明细位于 `<qa-root>/verified-native-story.json`。

## 第五步和全章节排查

- 同一隔离档重进仍为 4/10、物语点 21。复用已安装 PC 包的全尺寸主将贴图，为物语路径加了同名索引。真机请求收到 200，Unity 3.5 读回了 1024×1024 的 `Texture2D`。
- 第五步在存档副本内产生了 `q_mons_0000_01`、1000 HP 的遭遇，核对了原奖励表。副本结果未写入数据库。已核查的 `vsBattle` 和 `vsBattleAssets` 候选只包含 PS3 或安卓平台数据，PC 原版对白也未找到。`battle/executeBattle` 仍缺服务端结算，战斗和战后到账未验收。
- `quest_1_index` 有 315 行，同时开启客户端和服务开关的范围是 9 个篇目、41 章、401 个区域。启用章节的区域步数均能落到关卡表，奖励表均可读取。按本地安装路径检查，40 章缺探索背景，41 章缺至少一组剧情脚本。逐章结果位于 `<qa-root>/chapter-static-audit-v2.json`。

## PS3 战斗包转换和独立结算试跑

- `vsBattleReturn` 从 PS3 原包逐对象转换为 PC 包，保留 16 个对象与 PC `BattleTransToBattle` 绑定。隔离客户端的 Unity 3.5 按场景名确认可读，证据在 `battle-return-port/native-engine-v2.json`。
- 从 RPCS3 安装目录的 PS3 原包转换 `vsBattle`（156 个对象）和 `vsBattleAssets`（12,550 个对象）。[场景转换工具](../../tools/port_ps3_battle_scene.py) 按 PC 程序集及序列化布局重连组件、网格和 PC 共享资源。隔离客户端的 Unity 3.5 能识别 `vsBattle`，并读出原战斗时间轴 `BattleEventTimeline` 和结算预制件 `Battle_End_0001`。验证记录在 `battle-pc-engine-probes.json`。
- [依赖转换工具](../../tools/port_ps3_battle_dependencies.py) 保留战斗引用的 272 张贴图和 334 个材质，并将 PS3 的 `Transparent/Constant` 渲染流程转换为 PC 的固定功能纹理阶段。三个依赖节点随战斗主场景装载，隔离客户端读到了战斗特效材质、原贴图和共享字体。验证记录在 `battle-dependency-engine-probes.json` 和 `battle-integrated-engine-probe.json`。第五步仍需从原生入口触发战斗和接收结算回包，战斗画面与发奖未做全流程验收。
- 第五步的怪物表指向 `q_mons_0000_01`，即原消息表里的「刀足轻」。从美术归档的同名 TGA 重封 `cch2_00007_01_3_01`，隔离客户端按原名读到 1024×1024 的贴图。来源、哈希和读回结果位于 `battle-portrait-candidate/manifest.json` 和 `battle-monster-portrait-engine-probe.json`。
- 参照用户提供的离线首回合算法加入隔离结算逻辑。用 4/10 存档副本验证了首回合 1,562 伤害、玩家经验 +20 和紫魂入账。重复结算返回同一回执，经验和紫魂未重复增加。存档副本结果没有写回当前验收档，真机仍保留 4/10 和 21 点。本地明细为 `step5-settlement-dry-run.json`。
- 扩查安装包缓存和现存资源归档，尚未找到原版对白。缺失背景里找到 5 张同名原画，已按 PC 格式重封并在 Unity 3.5 读回；候选包留在隔离目录 `story-background-candidates`，未部署到正常本地服。

本机回滚与核对证据保存在 `<qa-root>/local-story-expedition/withdrawn`。其中 `original-cache-audit-v2.json` 为逐对象审计，`native-preparation` 包含三张背景及怪物表的构建来源和哈希。

## 第五步原客户端验收

- 隔离服从同一份 4/10、21 点快照开始。在原 PC 客户端点击「探索」后，实际进入 `vsBattle`，显示背景、敌我立绘及开场特效。敌方血条归零后出现原生胜利结算。点击结算画面，返回选关看到 5/10。
- 第一轮接通了步进和结算接口。第二轮沿用 PC 相机和 UI 组件的序列化布局，并用原图补回技能经验、紫魂两个奖励图标。第三轮修复了 `BattleEventTimeline` 的轨道和动画引用。隔离客户端直接读回了开场和背景轨道，修复前对应集合被读为空。
- 结算界面显示紫魂 15、经验 20、技能经验 10。数据库记录只扣 1 物语点，经验 +20，紫魂 +15。队伍没有可升级的技能，技能经验实际应用 0。按同一遭遇重放两次 `battle/executeBattle`，每次返回同一份结算数据。再次提交原探索请求被拒，三次重试前后玩家数据完全相同。
- 战斗回包沿用用户提供的首回合结算方案。原始敌方攻、防、知数值未找到，当前画面使用协议里的 0 值占位。战斗 BGM 路径 `bgm/7c8c84e84f10815127ca2c528a4feeb3.unity3d` 仍返回 `stub has no assets`。此流程限于隔离档第一章第五步。
- 实机截图里的四个空武将槽显示白块。后续在美术归档找到 PC 原客户端请求的 `card_image_enpty_001` 原图，两份候选图的像素相同。隔离客户端确认能解包并按原名读取 256×256 贴图，隔离服已提供更新后的资源包。截图和全流程结果来自补入该贴图前的同一战斗版本。
- 验收证据保存在 `<qa-root>`。`step5-native-*-v3.jpg` 记录探索、战斗、攻击、结算、返回，`step5-live-reward-retry-v3.json` 记录实际入账与 HTTP 重试结果。

## 其余章节资源复查

- 重新检查安装归档和 PS3 提取目录中的 10,462 个可读包，首章目标脚本与对白均未找到。逐章从关卡表检查 9 篇、41 章、401 区域，40 章缺至少一张背景，41 章缺至少一组剧情脚本。按原名或包名哈希查找 391 张缺失背景及 406 组缺失脚本，确认五张同名原画已有留档，其余资源仍缺。逐章结果见 `chapter-static-audit-v3.json`、`chapter-resource-search-step5.json`，尚未全章节真机验收。

## 隔离档全章预览 · 2026-11-19

- `--chapter-preview` 开放国服表中双开关启用的全部鬼物语。按原版界面名称是 9 篇、41 话、401 章，分别对应表中的故事、`chapter` 和 `area`。从「物语 → 鬼物语」用篇名旁的箭头翻篇，再选话、选章、点「出阵」。接口逐话核对了 401 章的上限与存档投影。
- 预览进入原版 PC 选关和移植的探索场景，显示战力、主将立绘、进度和获得物。原背景可用的入口共 34 个，来自 8 个同名背景包，缺背景时中间留黑。逐章入口背景清单见 `chapter-preview-entry-backgrounds.json`。预览模式隐藏探索和自动按钮并停用物语写入，抽测前后隔离档仍为新手第一章 5/10，库存奖励与库中 20 点物语点数相同。客户端的自然回点倒计时照常显示。
- 真机抽测「领内巡检篇 → 行踪不明的渔民 → 第二章」，原背景与主将立绘正常，伊达爱、姊小路良赖、来岛通康图标路径返回 `stub has no assets`。最后一篇「龙虎冲突篇 参 → 龙虎迅猛 → 第十章」的背景 `qbg3_0128_01` 仍缺，立绘、进度和部分获得物图标可见。两处均能返回原版选关。证据为 `chapter-preview-with-original-bg.jpg`、`chapter-preview-missing-bg.jpg`、`chapter-preview-last-story-menu.jpg` 和 `chapter-preview-http-proof.json`，均位于 `<qa-root>`。
- PS3 安装文件补查 `mainData`、4 个关卡文件、`resources.assets` 和 5 个共享文件，只有 5 个 TextAsset，内容属于字体、资产索引和词表。没有找到原版对白脚本或对应文案表。PC 安装器原包及缓存的检查结果同上。PS3 逐文件证据见 `ps3-main-dialogue-audit.json`。结论限于当前已检查的安装包、提取文件和缓存。

## 原图复扫与补写对白 · 2026-11-19

- 按原 URL 哈希和包内纹理名巡查 PC 安装器及运行过的 Qt 缓存、Unity Shared 备份、PS3 安装目录和同名原画归档。主报告枚举了 23,149 份不同载荷，包括 PS3 安装目录的 10,469 份文件。四个多级 UnityWeb 记录都是 PC `app.unity3d` 副本，另用 UnityPy 核对。此前找到的 8 个同名背景包仍覆盖 34 个出阵入口。这轮没有找到新的同名背景或缺失奖励图标。详见 `original-story-resource-audit-v2-20261119.json`、`original-story-resource-audit-extra-20261119.json`。
- 原生客户端的 76 种鬼物语奖励图标路径逐一请求，19 种可用，57 种返回 `stub has no assets`。已有原图正常显示，缺图仍会出现白块。详见 `chapter-dialogue-reward-asset-http.json`。
- 从 PC 原版 `quest_1_indexMessage.json` 读取话名和简介，并参考公开的[原编剧访谈](https://www.4gamer.net/games/150/G015000/20130628015/)。为 41 话各补写两句开场对白，首句标注「补写对白」。隔离预览按选中的篇、话调用原版 `quest_layout` 与 `EffectiveText`，由客户端处理翻页。文案见 [native_story_preview_dialogue.json](../../tools/native_story_preview_dialogue.json)。
- 真机抽测新手第一章和「龙虎冲突篇 参 → 龙虎迅猛 → 第十章」。两处都显示本话各自的两句对白，使用原版黄色箭头切换，结束后仍显示探索画面并可返回选关。测试前后数据库中的进度、物语点和奖励相同。截图为 `chapter-dialogue-tutorial-first.jpg`、`chapter-dialogue-tutorial-second.jpg`、`chapter-dialogue-last-first.jpg`。

## 在本机复现预览

1. 准备原 PC 的 `app.unity3d`、其 `Assembly-CSharp.dll` 和本地编译引用 `mscorlib.dll`、`UnityEngine.dll`、`Assembly-CSharp-firstpass.dll`。安装仓库现有的分析和媒体依赖。用 .NET Framework 3.5 的 C# 编译器和这些引用将 `tools/client_native_story.cs` 编为 DLL。给 `tools/patch_native_story_client.ps1` 传入原 DLL、编好的辅助 DLL、Mono.Cecil 路径和隔离端口，并开启 `-ChapterPreview`。
2. 准备 PS3 原安装包的 `quest`、`questAssets`。依次运行 `tools/port_ps3_quest_scene.py` 和 `tools/port_ps3_quest_prefabs.py`。PC 输入来自 `bundles/scene` 中的 `questSelect`（`1ac13bd637a6ae646b4c42226cdee284`）、`globalAssets`（`7536912f38fca927a22a16bdbefcdc07`）、动画资源（`21f922c997e0ce6d37edd5d592364480`）和音频资源（`7f963973463ed3cf3318cd5c9cce5b58`）。两个转换工具的 `--help` 列出对应参数。
3. 创建预览背景 JSON，内容是手头已经核对的同名 `qbg` 名称列表。取回原画时，用 `tools/port_legacy_media.py` 将同名图转为 PC 包，包名为纹理名称的 UTF-16LE MD5。构建候选后、启动服务前，把重封的包放入候选目录的 `qbg` 子目录。已有的 PC 包可直接从本机资产目录的 `bundles/qbg` 读取。列表可以为空，缺失背景在探索场景中留空。
4. 在仓库根目录构建候选并运行。下例的变量均指向本机私有文件。`$pcScriptTemplate` 是原 PC `bundles/scr/78a4465015e3bd14bc422ab9309ece80.unity3d`，`$pcPortrait` 是 `bundles/chara/05408acd6c1d55d25f99368a9a90de38.unity3d`。`$localProfile` 提供本机 MySQL 3307 的 `mysql_root_password`。客户端补丁、服务启动和客户端登录入口统一使用同一个回环端口。

   ```powershell
   python tools/build_native_story_qa.py --app $pcApp --assembly $patchedDll `
       --template $pcScriptTemplate --portrait-source $pcPortrait --out $candidate `
       --preview-backgrounds $backgroundNames --preview-dialogue tools/native_story_preview_dialogue.json
   python tools/run_native_story_qa.py --profiles $localProfile --assets $pcAssets `
       --candidate $candidate --scene $portedQuest --prefabs $portedPrefabs `
       --schema onisoul_native_story_qa_20261119 --port 18119 --chapter-preview
   ```

5. 将隔离客户端的 `StartUrl` 指向候选目录的 `fixture-start.txt` 中的登录地址，再从「物语 → 鬼物语」选话、选章并出阵。登录地址含本机临时会话入口，应保存在本机配置中。开启 `--chapter-preview` 的服务只展示章节和对白，步进及战斗写接口限于另外的隔离验收模式。
