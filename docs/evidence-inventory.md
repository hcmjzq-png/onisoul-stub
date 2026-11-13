# 素材证据分级清单

- 盘点时间：2026-11-13
- 机器：DESKTOP-N8RCQR0（Windows，本地开发机）
- 范围：`E:\oni-soul`、`E:\oni-soul-recovered-20261112-0109`、`C:\Users\74378\Downloads`
- 方式：只读盘点（统计元数据、文件哈希、抽读小文件），未改动、未移动、未删除任何文件。

> 本文件记录逆向素材的可信度分级与核验证据。响应字段来源纪律见 `CONTRIBUTING.md`「字段来源纪律」。

## 0. 证据分级定义

| 级别 | 来源 | 采信范围 |
|---|---|---|
| A | 原始客户端二进制 / Unity bundle（未被改写的副本） | 接口名、参数字段名、客户端解析逻辑 |
| B | 原厂静态表、常量配置、官方 CDN cache 清单 | 表内数值、ID 映射、常量上限/比例 |
| C | 官方服务器原始网络抓包（har/pcap/原始响应报文） | 真实信封结构、响应字段、真实返回值 |
| D | 旧 stub 派生产物（旧服务端代码、改写资源、本地库、自录日志、构建产物） | 仅作线索，不能作为官方依据 |

定级原则：A/B 两处相互印证才写入正式 schema；单一 D 级出处只记 TODO；推测项显式标「待验证」。

## 1. A 级：原始客户端程序集（哈希已核）

### 1.1 Assembly-CSharp.dll 同源分组（SHA256 前 16 位）

| Hash(16) | 大小 KB | 路径（相对 `E:\oni-soul\`） | 判定 |
|---|---:|---|---|
| `27D862CC41008AA7` | 4060 | `work\apk_1_00_13\assets\bin\Data\Managed\Assembly-CSharp.dll` | 原始（1.00.13 apk 内解出） |
| `27D862CC41008AA7` | 4060 | `work\apk_managed\Assembly-CSharp.dll` | 与上同源副本 |
| `27D862CC41008AA7` | 4060 | `work\patched\Assembly-CSharp.dll` | 同源副本（主 dll 未改；改名副本才是派生，见 §4） |
| `013CF79134F252D3` | 4060 | `work\apk_gwz\Assembly-CSharp.dll` | 原始（另一构建/渠道） |
| `88C763F2004A50D5` | 4217 | `work\apk_v18\Assembly-CSharp.dll` | 原始（1.00.18） |
| `B27BE6995D07248F` | 4477 | `work\pc_dll\Assembly-CSharp.dll` | PC 端原始基准 |
| `B27BE6995D07248F` | 4477 | `analysis\cs_orig.dll` | 与 pc_dll 同源副本 |
| `B27BE6995D07248F` | 4477 | `鬼武者魂\OniSoul-LocalBridge-v1\payload\asm\Assembly-CSharp.dll` | 同源副本 |
| `B27BE6995D07248F` | 4477 | `dist\OniSoul-LocalBridge\payload\asm\Assembly-CSharp.dll` | 同源副本 |
| `B56773EDA9CE95D4` | 4312 | `work\pcweb\asm\Assembly-CSharp.dll` | PC Web 端原始 |
| `B56773EDA9CE95D4` | 4312 | `dist\OniSoul-PC-Direct\asm\Assembly-CSharp.dll` | 同源副本 |
| `05003A56450698B0` | 2459 | `work\ps3_managed\Assembly-CSharp.dll` | PS3 端原始 |
| `57F9B81EC6313430` | 3906 | `work\_cur\Assembly-CSharp.dll` | **派生**，与上述所有原始组均不同 |

### 1.2 原厂安卓安装包（MD5 已与 `downloads\README.txt` 记录核对）

| 文件 | 字节 | MD5 | README 记录 | 核对 |
|---|---:|---|---|---|
| `downloads\onisoul_1.00.13.apk` | 10,062,163 | `4F0809F3DFE07CA23BF86D13273956D8` | `4f0809f3…56d8` / 10,062,163 | 一致 |
| `downloads\gwzsoul_1.00.15_20140217.apk` | 10,062,443 | `2A21D5067EDCF655F17A343EAFD32F09` | `2a21d506…2f09` / 10,062,443 | 一致 |
| `downloads\onisoul_1.00.18.apk` | 10,078,513 | `C5414DFCBA8F6DA7FAE16AFA19A7B8E1` | `c5414dfc…7b8e1` / 10,078,513 | 一致 |

包名（README 记录）：`jp.co.capcom.android.onimushasouljp`；版本 1.00.13 / 1.00.15 / 1.00.18。

### 1.3 A 级待验证项

- 三个 apk 的数字签名尚未核验；MD5 一致只证明文件自 README 记录后未变，**不等于签名有效**。
- `pc_dll` / `cs_orig.dll` 的提取来源与对应客户端版本未追溯记录。
- `work\_cur`（3906KB）派生自哪一组原始 dll、被改动了什么，尚未做 diff。
- `firstpass` dll（`Assembly-CSharp-firstpass.dll`）未纳入本轮哈希比对。

## 2. B 级：原厂静态表与配置

### 2.1 `tableAssets_tables\`

- 规模：1061 个 JSON，94.7 MiB，191,791 条 `id` 记录（据 `_清单.md`）。
- 来源：解包自原厂 `tableAssets.unity3d`（LZMA 解压后 100,194,188 字节）。
- 重点表（`_清单.md`）：`character.json`（3,814 id）、`characterGrade.json`、`characterLevel.json`（850 id）、`building.json`（1,343 id）、`building_level.json`（2,183 id）、`equip.json`、`quest_1_index.json`、`defines.json`（111 id）。
- 样例核验：`defines.json` 结构为 `{"defines": {"<id>": {"id": …, "value": …}}}`，内容为常量键值（如 `quest_work_limit=20`、`username_min_length=1`、`username_max_length=10`、`soul_limit=60000`、`level_limit=15`），未见旧 stub 注入字段。
- 字节一致性核验（2026-11-13，UnityPy 1.25.4 解析原厂 `tableAssets.unity3d`，Unity 3.5.6f4）：
  - bundle 内 TextAsset 共 1070 个；磁盘 JSON 1061 个。
  - 1048 张的 `m_Script` 原始字节与磁盘文件逐字节一致。
  - 13 张 bundle 段略大于磁盘，差值恰好等于被清理的 MiniJSON 尾逗号；删除尾逗号后与磁盘逐字节一致，字段值未改动。
  - 磁盘独有 0 张：不存在 bundle 之外、由旧 stub 编造的表。
  - bundle 内 9 张未落盘：8 张被标准 JSON 解析拒收（非法转义 / 控制字符 / 分隔符，原厂 MiniJSON 容忍；错误与 `_errors.txt` 逐条对应）；`bot.json`（bot NPC 主数据表）为旧导出脚本切分遗漏。二者原始字节仍在 bundle，需要时可经 UnityPy 单独导出，不引用磁盘派生件。
  - 基准 `tableAssets.raw`（100,194,188 字节）即该 bundle 解压后内容；纯标准库手解析在 Message / 布局表上受字符串内括号干扰，其段长差异未采信，最终以 UnityPy 结构解析为准。

### 2.2 其他 B 级辅助素材（`analysis\` 内）

- `official_cache_extract\`：官方 CDN cache 解压目录。
- `official_cache_bundle_contents.json` / `official_cache_inventory.json` / `official_cache_alignment.json`：官方 bundle 清单与对齐记录。
- `cs_strings.json`：C# 程序集字符串提取结果（A 级派生文本，用于定位接口名/字段名）。

### 2.3 B 级待验证项

- 表 JSON 与 bundle 原始字节一致性：**已核验**（见 §2.1「字节一致性核验」）——1048 张逐字节一致，13 张仅尾逗号清理（语义等价），磁盘无 bundle 外文件。
- 带版本后缀的文件（`shop_item_all5/all6/all7/…`、`navigator_monica5…9` 等）分别对应哪个客户端版本，尚未核对。
- 表内数值用于 Stub 初始值前，需与客户端 dll 中的默认值交叉印证。

## 3. C 级：官方网络抓包 —— 本轮未发现可信样本

- 全盘未发现 `.har` / `.pcap` 文件。
- `server\logs\capture-*.jsonl`、`server\logs\requests-*.jsonl`：旧 stub 服务端自录。首行证据：路径 `/api/debug/devLogin`，请求体 `params={"platform":"pc","username":"PydDev1"}`；requests 记录中 `"src": "override"`、`ua: "curl/8.21.0"`。**响应由旧 stub 生成，属 D 级，不代表官方返回。**
- `analysis\mono-trace-*.jsonl`：Mono 托管方法调用 trace（运行时 hook 观测），属 A 级辅助线索，不是网络抓包。

**结论**：当前材料中没有官方服务器原始响应报文。响应结构只能从客户端 dll 反推；真实返回值、服务端校验与计算规则缺少 C 级证据。

## 4. D 级：污染 / 派生产物（实现不参考）

| 类别 | 路径（相对 `E:\oni-soul\`） |
|---|---|
| 旧服务端源码 | `server\`、`_server\` |
| 旧面板 | `panel\` |
| 构建产物 | `dist\`、`build\`、`assets_serve\`、`unity_build\` |
| 回滚 / 归档 | `_recover\`、`_attic\`、`_incoming\`、`_extract\` |
| 云端旧部署副本 | `deploy-cloud\` |
| 工具痕迹目录 | `.workbuddy\`、`.dshwolf\` |
| 派生程序集 | `work\patched\*.patched.dll` / `.phone.dll` / `.diag.dll` / `Assembly-CSharp_politic_input.dll`（3906KB 改名副本）、`work\_cur\` |
| 改写过的 bundle | `app_lc1*.unity3d`、`keep_mypage_fix.unity3d`、`mypage_fix.unity3d`、`st_*.unity3d`、`rt_*.unity3d` 等（区别于 `app_orig.unity3d`、`raw_mypage.unity3d`） |
| 本地数据库 | `server\data\sessions.db*`、`panel\data\panel.db*`（`WebpageIcons.db` 为 CEF 缓存图标，无关） |
| 旧分析过程产物 | `analysis\auto-*`、`analysis\probe-*` 各子目录、大量过程截图、旧测试/回滚脚本 |
| 独立恢复快照 | `E:\oni-soul-recovered-20261112-0109\`（1585 文件 / 229.3 MB，旧 stub 源码按 patch 回滚的副本，见其 `RECOVERY_MANIFEST.md`） |

### 4.1 Dat.bin / data.dat（按要求本轮不纳入）

- `10-原版客户端\data.dat`：503.9 MB 单文件。
- `analysis\data_bin_*`（密码分析、解压探测、keystream 等 JSON / py）。
- 用户已指示：Dat.bin 用途未明，本轮不纳入分析。

## 5. 安装包归属待核验

- 文件：`C:\Users\74378\Downloads\OniSoul_Setup_20140712.exe`，653,677,906 字节，MD5 `EB3FAE6F7C785736C0211278FCC8DA29`。
- `downloads\README.txt` 记录的国服 PC 微端（613 MB）MD5 为 `f306b379c19d59ca9a722f50a129e3b3`，与上述不符。
- 文件大小对应 README 所述「不删档测试客户端 623.4 MB（2014-07-16）」，但该包 README 未记录 MD5，**归属待解包核验**。

## 6. 停运背景（README 二手记录，未独立核验）

- 国服：2016-05-26 停运；台服：2016-07 关闭；日服：2017-03-30 停运。
- 国服官网 `www.gwzol.com` 已停止解析；PC 微端公开镜像已失效。

## 7. 建议迁移素材（进仓 / 服务器，排除 D 级）

1. `downloads\` 三个原厂 apk。
2. §1.1 各组原始程序集代表副本（每组留一份即可）。
3. `tableAssets_tables\`（B 级表数据；`_index.*` 派生索引按需保留）。
4. `analysis\official_cache_extract\` 与官方 bundle 清单 JSON。
5. `analysis\cs_strings.json`、`mono-trace-*.jsonl`（辅助线索）。

不迁移：旧 `server\` / `panel\` 源码、`dist\` / `build\` 产物、改写过的 bundle、本地 db、过程截图与旧脚本。

## 8. 现有材料无法确定的内容（硬限制）

- 服务端校验规则、掉落/抽卡概率结算、战斗与内政数值计算（可能仅存在于已停运的官方服务端）。
- 玩家建号初始资源/等级：仅当 `defines.json` / `characterLevel.json` / `building_level.json` 等表内可证时取值，否则标「待验证」，不从旧 stub 抄。
- 官方真实响应报文结构与返回值：需后续抓到连官方环境的样本，或从客户端 dll 解析逻辑反推后标注「反推，待验证」。
