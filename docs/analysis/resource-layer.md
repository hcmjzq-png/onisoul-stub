# 资源层契约（resource_contract.tsv / asset_prefixes.tsv / table_list.tsv）

从客户端反编译源码静态抽取：**客户端会向资源服要哪些文件、URL 怎么拼、表数据是什么格式**。

## 三个服务端地址，全部来自同一张配置表

| 用途 | 模板 | 取值来源 |
|---|---|---|
| API | `http://{webHost}/api/{endpoint}` | `settingTable_["web"]`（`Configs.ServerBase`） |
| 资源 | `http://{assetHost}/client/{platform}/{language}/...` | `settingTable_["asset"]`（`Configs.DownloadsBase`） |
| IRC | `{ircHost}` + 密码 | `settingTable_["irc"]`、`settingTable_["ircPass"]` |

`platform` 是常量 `"pc"`（`Configs.cs`）。这张表由 `Configs.setup(host)` 加载，改表即可三个端点全部指向 Stub。

## 资源 URL 的组装规则（`Loader.getBaseUrl` + `getHashFilePath`）

```
base = "http://" + Configs.DownloadsBase + "/client/" + Configs.Platform + "/" + Configs.Language + "/"
       (Configs.Platform 恒为 "pc"，Configs.Language 默认 "jp")
path = AssetPathConverter.convertUrl(name)     # 前缀命中时变成 {root}/{dir}/{name}
realUrl = 协议+主机 + 目录 + "/" + MD5(文件主名) + 扩展名 + "?r=" + (RevisionNo*10 + Performance)
```

`Loader.getHashFilePath`（Loader.cs:118）源码逐字：

```csharp
empty = empty + directoryName + "/" + MD5.Compute(fileNameWithoutExtension) + extension
              + "?r=" + (revisionNo * 10 + performance);
if (instance.IsDebugMode) empty = empty + "&" + fileNameWithoutExtension;
```

- **文件名会被 MD5 掉**：请求的不是原名，而是 `MD5(去扩展名的文件名)` + 原扩展名。
- **调试模式下 URL 尾巴会再拼上原名**（`&原名`）——把客户端的 `IsDebugMode` 打开，Stub 日志里就能直接看到原始资源名，省掉反推。
- MD5 是标准 `System.Security.Cryptography.MD5`（`MD5.cs`，`MD5.Compute` 走 `InputData(string)`），无 salt；但字符串编码未逐字节核对，**建议 Stub 直接忽略文件名，只按目录匹配**，绕开这个问题。
- `?r=` 只是缓存破坏参数，Stub 可忽略。
- `RevisionNo` 来自 `common/getRevisions` 回包的 `root` 字段；`Performance` 是画质档位（0/1/2）。

## 前缀目录表（46 条，`asset_prefixes.tsv`）

每个前缀映射到「目录 + 三档根目录」：

```
prefix   directory          perf0   perf1    perf2
chara    chara              assets/ assets/  assets2/
building building           assets/ assets2/ assets2/
product  product            assets/ assets2/ assets2/
cch      cch                assets/ assets/  assets2/
cna      cna                assets/ assets2/ assets2/
qbg      qbg                assets/ assets2/ assets2/
pbm      pbm                assets/ assets2/ assets2/
pbsm1    pbsm1              assets/ assets2/ assets2/
pbsm2    pbsm2              assets/ assets2/ assets2/
```

其余 37 条三档都是 `assets/`。**9 个前缀在画质档 1/2 时走 `assets2/`** —— 这是客户端唯一会跨根目录的情况，Stub 如果只做 `assets/`，高画质档会 404。

## 加载策略与重试

| 行为 | 参数 |
|---|---|
| 并发上限 | 10（`loadLimit_g`） |
| 重试 | 10 次，间隔 3s |
| `assets2` 回退 | URL 含 `assets2` 时经 `AssetPathConverter.convertUrlHP` 换路径再试 |
| 缓存下载 | `name` 存在于 `FileDataBase`（表 `assetbundle.json`）→ `WWW.LoadFromCacheOrDownload(url, RevisionNo)`；否则裸 `new WWW(url)` |
| 超时 | `configs.downloadTimeOut_` |

`FileDataBase` 的判定依据是表 `assetbundle.json`，也就是说**哪些 bundle 走缓存是表数据决定的，不是代码写死的**。Stub 只要让这张表可解析，客户端会自己决定。

## 资源名清单（363 条，`resource_contract.tsv`）

| 类别 | 数量 |
|---|---|
| 字面量（源码里写死的名字） | 146 |
| 运行时决定（变量拼接，如 `"chara" + id`） | 217 |
| 其中 `SceneResources.load<GameObject>("prefab 名")` | 大头是 UI 预制体名 |

两个硬编码的 bundle 名：

- `globalAssets.unity3d`（5 处，`GloabalObjectRead.cs` / `SceneResources.cs`）——客户端启动就要它
- `assets/scene/tableAssets.unity3d`（`TableResources.loadTableData` 唯一引用）——全部配置表容器

## 表数据：JSON，不是 MessagePack（这条纠正了旧结论）

表的容器是唯一硬编码路径 `assets/scene/tableAssets.unity3d`（`TableResources.cs:8`），下载方式（`loadTableData`）：

```csharp
url     = Loader.getBaseUrl("assets/scene/tableAssets.unity3d") + "assets/scene/tableAssets.unity3d"
realUrl = Loader.getHashFilePath(url)      // → /client/pc/jp/assets/scene/{MD5("tableAssets")}.unity3d?r=...
www     = WWW.LoadFromCacheOrDownload(realUrl, configs.TableRevisionNo)   // 失败重试 10 次
```

取表（`loadFileFormAssets`）：

```csharp
if (!tableAssets_.Contains(filename)) return null;          // 先查存在性
tableAssets_.Load(filename, typeof(TextAsset))              // 再按名取 TextAsset
```

**`filename` 就是 `reset()` 的第一个参数，形如 `building.json` —— 所以 bundle 内每个 TextAsset 的名字必须逐字等于 `xxx.json`（带扩展名）。** 取不到时还有一层回退 `Resources.Load("tables/" + name)`（客户端自带 Resources，不是给 Stub 的路径）。

`TableResources` 有两条读表路径：

| 路径 | 实现 | 调用面 |
|---|---|---|
| `load(name)` | `AssetBundle.Load(name, typeof(TextAsset))` → `MiniJSON.JsonDecode` → `Hashtable`（**字符串键**） | 125 个 `*TableAccessor : TableAccessorCore` 全走这条 |
| `load2(name)` | `AssetBundle.Load` → `bytes` → `JsonTablePacker.Unpack` → `Dictionary<uint,object>`（**CRC32 键**） | **0 个业务调用点** |

实测：`get2` 只有定义、全代码无调用；`JsonToTable.convert` + `JsonTablePacker` 只在 `AssetTest.cs` 里被用到。**所以表就是 JSON 文本，Stub 只需提供 JSON，不需要复刻 CRC32 + MessagePack 的表格式。**

（`JsonToTable` / `JsonTablePacker` 的结构仍然记录在案：`{CRC32("keys"): 压缩的键名 JSON 数组, CRC32("ids"): ..., CRC32(表名): {CRC32(参数名): 值}}`，将来如果要做体积优化可直接照抄，但不是必需。）

## 客户端要求的 108 张表（`table_list.tsv`）

每个 `*TableAccessor` 在 `reset("文件名", "根键")` 里写死表名，抽出来 108 条，例如：

```
accelerate_produce_task.json   accelerate_produce_task
artifactSeries.json            artifactSeries
assetbundle.json               assetbundle      ← FileDataBase 用它决定哪些 bundle 走缓存
battleCost.json                battleCost
booster_packs.json             booster_packs
building.json                  building
```

**这就是 Stub 里 `tableAssets.unity3d` 必须包含的资源名清单**：AssetBundle 内部每个 TextAsset 的名字等于第一列（`xxx.json`），内容 JSON 的顶层键等于第二列。

## 表内容在包里，不需要等运行时（`table_schema.tsv` / `table_inventory.tsv`）

包内 `app/cache` 解出的 textassets 里有 **1112 个 JSON TextAsset**，命名形如 `<bundle前缀>.unity3d__<asset名>.json`：

| 类别 | 数量 |
|---|---|
| stringtable 类（本地化字符串） | 40 |
| 客户端 `TableAccessor` 引用的表 | 106 |
| 未被客户端引用的 JSON 资产 | 966 |

`table_inventory.tsv` 是全部 1112 条的清单（`asset_name / json_root / record_count / field_count / bytes / client_referenced / accessor_root_key`）；`table_schema.tsv` 是其中**客户端引用的 108 张表**的字段结构。

- 命中 **106 / 108**：共 **32,999 条记录**，平均 **12.3 个字段/表**。
- 结构统一为 `{rootKey: {id: {...}}}`——`json_root` 与 `*TableAccessor.reset("xxx.json", "rootKey")` 的第二参数**逐条比对 0 不一致**，说明 accessor 声明的根键就是数据真根键。
- 缺 2 张：`combo.json`（包内无任何 combo 命名的 JSON 资产）、`strategy_battlefield.json`（包里只有 `strategy_battlefield_catalogue.json`，是另一张表，不是同一个根键）。
- 解析要点：表 JSON 由 MiniJSON 写出，**含尾逗号**（`,}` / `,]`），标准 `json.loads` 会报 `Illegal trailing comma`，需先 `re.sub(r',\s*([}\]])', r'\1', raw)`；另有极少数文件是多段 JSON 拼接，需 `raw_decode` 取首段。

**2026-11-15 复核更正**：上述 106/108 只是固定表名扫描结果，不能证明其余 966 张不被客户端读取。
原客户端动态拼接关卡索引、区域和奖励表名，已从原安装包核实并登记 552 张关卡相关表。
必须保留原 bundle；仅用固定 106 张表重打包会丢失动态资源。来源、偏移、校验值及服务器
UTF-8 提取修复见 [关卡表复核](quest-contract-20261115/README.md)。

## Stub 侧最小实现

1. 静态文件服务挂在 `http://{assetHost}/client/pc/jp/`，按目录前缀匹配，忽略文件名与 `?r=`。
2. 提供原始 `globalAssets.unity3d`、`assets/scene/tableAssets.unity3d`；不可仅凭固定表清单缩减或重新合成表包。
3. 画质档 1/2 的 9 个前缀目录（`assets2/`）也要能命中，或直接把配置的 Performance 固定为 0。
4. `common/getRevisions` 回 `{root, unity, server, table}` 四个整数，客户端拿它们做缓存版本号；任一变化都会触发重新下载。

## 一个可用的加速开关（当前包里是关的）

`TableResources` 在 `Configs.IsLocalDevelopMode == true` 时会跳过 bundle，直接读本地文本文件（`Configs.jsonFilePath_g + name + ".txt"`，`file://`）。实测全代码只有 `Configs.cs:1238` 的 setter 被定义、**无任何调用点**，所以这个 PC 包里该开关恒为 false，走不到这条捷径——但它说明「本地读表」是官方支持的模式，改动成本低时值得在 Stub 侧顺手接上。

## 已知局限

- `MD5.Compute` 用的是什么变体（是否带 salt）未逐字节核对；建议 Stub 直接忽略文件名，回避这个问题。
- 客户端请求的语言目录 `{language}` 取自 `Configs.Language`，其取值来自运行环境/配置表，未在本次抽取中确认默认值（日服包预期 `jp`）。
- `resource_contract.tsv` 里 217 条运行时决定的名字没有展开成可能值集合（要展开需要追拼接表达式）。
- 表数据只做到「字段名 + 类型 + 记录数」，104 MB 原始 JSON 不入仓；字段语义（外键、枚举、位标志）尚未逐表标注。
