# 客户端接口契约（docs/analysis）

来源：唯一可信来源 `OniSoul_Setup_20140712.exe` → `app.unity3d`（UnityWeb 容器）→ `Assembly-CSharp.dll`（4,584,448 B）→ `ilspycmd 9.1.0.7988` 反编译 2034 个 `.cs` 后静态抽取。

**这些结论未经运行验证**；属于「从客户端代码直接读出的线上约定」，不是抓包实测。

## 入仓内容

| 文件 | 内容 |
|---|---|
| `api_contract.tsv` | 402 个 api 端点契约，一端点一行；列定义见 `api-contract.md` |
| `api-contract.md` | 列定义、十六类抽取手段、交叉校验、嵌套结构、常量枚举、缺口清单 |
| `behavior-layer.md` | 行为层：端点回调的副作用（场景切换 / 窗口 / 服务调用 / 状态写入 / 键守卫）、端点调用图、启动链结论 |
| `resource-layer.md` | 资源层：三个 host 的来源、资源 URL 与 MD5 规则、46 个前缀目录、表数据格式与 108 张表清单 |
| `behavior_contract.tsv` | 402 个端点的行为契约，一端点一行；8 列，列定义见 `behavior-layer.md` |
| `api_call_graph.tsv` | 392 条端点→端点调用边（from_endpoint / to_endpoint / via_method） |
| `behavior_stats.txt` | 行为层计数、场景目标分布、出度榜 |
| `behavior_chains.txt` | 启动链可达性、无入边端点、高扇出端点清单 |
| `resource_contract.tsv` | 363 条资源名（146 字面量 / 217 运行时决定） |
| `asset_prefixes.tsv` | 46 个前缀 → 目录 + 三档根目录（9 个在画质档 1/2 走 `assets2/`） |
| `table_list.tsv` | 客户端 `reset()` 要求的 108 张配置表（文件名 / 根键 / 访问器） |
| `server_tables.tsv` | Stub 玩法额外依赖、但不在客户端 `reset()` 清单内的服务端运行时表 |
| `table_schema.tsv` | 客户端要求的 108 张表的字段结构（106 张命中，32,999 条记录，`fields` 列 `名:类型` 分号分隔） |
| `table_inventory.tsv` | 包里全部 1112 个 JSON 资产清单（40 stringtable / 106 客户端引用 / 966 未引用） |
| `resource_hosts.txt` | 三个 host 与平台、语言常量的出处 |
| `verify/endpoints.txt` | 端点清单双向对账（契约↔源码字面量） |
| `verify/channels.txt` | `WebApiClient` 之外的网络通道（资源下载 / 截图上传 / IRC） |
| `verify/params_keys.txt` | 用方法体范围重算参数后的差异与常量枚举 |
| `verify/types.txt` | 响应字段类型自洽性 |
| `verify/dynamic_keys.txt` | 78 处动态拼接键（请求模板键 + 表访问器键） |
| `verify/static_field_keys.txt` | 静态字段跨类传递的 3 个端点 |
| `verify/no_key_final.txt` | 123 个零字段端点的逐条处置（52 无调用点 + 71 不读命名键） |
| `verify/final_check.txt` | 推送前完整性检查结果（结构 / 编码 / 分隔符 / 键回查 / 类型冲突） |
| `verify/summary.json` | 计数汇总 |
| `unguarded-reads.md` | 无守卫读键扫描：两段式流水线、基线数字、四类误报实证、抽验记录 |
| `unguarded_gaps.tsv` | 扫描 + 契约对账产物：105 条候选行 / 70 个端点（`endpoint / callsite / missing_keys / first_evidence`） |

## 当前覆盖

| 指标 | 数量 |
|---|---|
| 端点总数（= `httpCall` 唯一字面量） | 402 |
| 已抽出响应字段 | 278 |
| 有调用但回调体不读命名键 | 72 |
| 本客户端从不调用（无调用点） | 52 |
| 唯一响应键 / 带类型 / 带可选标记 | 382 / 250 / 57 |

## 行为层与资源层要点

| 事实 | 数值 / 结论 |
|---|---|
| 端点→端点调用边 | 392 条，106 个端点有出边 |
| 无入边的端点（只能由界面或启动流程发起） | 6 个 |
| 直接 `transitionScene` 的端点 | 9 个（politic 4 / vsBattle 3 / deck 1 / migrationLogin 1 / strategy 1，共 10 次切换） |
| 启动链（getRevisions、gameLogin、guestLogin、getPlayerEntity）深度 3 可达端点 | 0 —— 流程由场景切换驱动，不是回调链驱动 |
| 有键守卫的端点 | 67（响应键出现在 `if` 条件里） |
| 资源前缀目录 | 46 个，其中 9 个在画质档 1/2 走 `assets2/` |
| 资源名 | 363 条（146 字面量 / 217 运行时决定） |
| 配置表格式 | JSON TextAsset（`load2`/`get2` 全代码 0 调用点，msgpack + CRC32 路径为死代码） |
| 客户端要求的表 | 108 张，见 `table_list.tsv`；其中 106 张已从包内 JSON 解出字段结构（`table_schema.tsv`） |
| 包内 JSON 表资产 | 1112 个（40 stringtable / 106 客户端引用 / 966 未引用），见 `table_inventory.tsv` |

## 不入仓

以下属客户端本体或体积过大，留本地 `analysis_full/`，可由脚本从安装包重建：

- 12 个程序集（含 `Assembly-CSharp.dll`）与 2034 个反编译 `.cs`
- `ilspycmd` 工具链与 IL 反汇编文本
- 历史报告 `report.md`、`scripts.tsv`、`tables_schema.lite.json`、`strings.json` 等明细清单

E 盘旧目录、安卓、PS3 素材一律不采信、不入仓。

## 重跑前置

`api-contract.md` 的「重跑」一节列了脚本顺序；前提是本地已存在反编译产物 `analysis_full/il_csharp/app/`。

无守卫读键扫描用 `tools/unguarded_reads.py`（`dump` 出读取点、`gap` 出候选缺口），同一份 dump 可反复对账，换契约表不必重扫 2034 个 `.cs`；口径与误报机制见 `unguarded-reads.md`。
