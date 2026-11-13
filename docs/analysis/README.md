# 客户端接口契约（docs/analysis）

来源：唯一可信来源 `OniSoul_Setup_20140712.exe` → `app.unity3d`（UnityWeb 容器）→ `Assembly-CSharp.dll`（4,584,448 B）→ `ilspycmd 9.1.0.7988` 反编译 2034 个 `.cs` 后静态抽取。

**这些结论未经运行验证**；属于「从客户端代码直接读出的线上约定」，不是抓包实测。

## 入仓内容

| 文件 | 内容 |
|---|---|
| `api_contract.tsv` | 402 个 api 端点契约，一端点一行；列定义见 `api-contract.md` |
| `api-contract.md` | 列定义、十六类抽取手段、交叉校验、嵌套结构、常量枚举、缺口清单 |
| `verify/endpoints.txt` | 端点清单双向对账（契约↔源码字面量） |
| `verify/channels.txt` | `WebApiClient` 之外的网络通道（资源下载 / 截图上传 / IRC） |
| `verify/params_keys.txt` | 用方法体范围重算参数后的差异与常量枚举 |
| `verify/types.txt` | 响应字段类型自洽性 |
| `verify/dynamic_keys.txt` | 78 处动态拼接键（请求模板键 + 表访问器键） |
| `verify/static_field_keys.txt` | 静态字段跨类传递的 3 个端点 |
| `verify/no_key_final.txt` | 124 个零字段端点的逐条处置（79 无调用点 + 45 不读命名键） |
| `verify/final_check.txt` | 推送前完整性检查结果（结构 / 编码 / 分隔符 / 键回查 / 类型冲突） |
| `verify/summary.json` | 计数汇总 |

## 当前覆盖

| 指标 | 数量 |
|---|---|
| 端点总数（= `httpCall` 唯一字面量） | 402 |
| 已抽出响应字段 | 278 |
| 有调用但回调体不读命名键 | 45 |
| 本客户端从不调用（无调用点） | 79 |
| 唯一响应键 / 带类型 / 带可选标记 | 382 / 250 / 57 |

## 不入仓

以下属客户端本体或体积过大，留本地 `analysis_full/`，可由脚本从安装包重建：

- 12 个程序集（含 `Assembly-CSharp.dll`）与 2034 个反编译 `.cs`
- `ilspycmd` 工具链与 IL 反汇编文本
- 历史报告 `report.md`、`scripts.tsv`、`tables_schema.lite.json`、`strings.json` 等明细清单

E 盘旧目录、安卓、PS3 素材一律不采信、不入仓。

## 重跑前置

`api-contract.md` 的「重跑」一节列了脚本顺序；前提是本地已存在反编译产物 `analysis_full/il_csharp/app/`。
