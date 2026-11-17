# 配置表

客户端 `reset()` 要求 108 张 JSON 表，清单与 root key 见
`docs/analysis/table_list.tsv`。服务端玩法额外依赖 4 张表，见
`docs/analysis/server_tables.tsv`。表文件体积较大，不进入 Git，统一放在
`assets/pc/tables/` 或 `ONI_TABLE_DIR` 指向的目录。
108/106 与额外 4 张表是原清单和导入来源维度，不是当前目录全部 JSON 文件的数量；
实际存量和漂移须结合部署清单与 `TableCatalog.check()`，不能跨批次直接相加。

## 导入

```bash
python tools/import_tables.py --source /path/to/extracted/textassets
```

真实解包文件名可能是 `<bundle前缀>.unity3d__<表名>.json`，例如
`app.unity3d__assetbundle.json`。导入工具按文件名末尾的表名匹配，但输出统一
改名成清单里的 `<表名>.json`，并生成 `import-manifest.json` 记录 SHA256、大小
和来源。客户端 108 张中可取得 106 张，仅缺：

- `combo.json`
- `strategy_battlefield.json`

服务端运行时 4 张当前均有：

- `item01.json`
- `item04.json`
- `reward01_politic.json`
- `reward99_country.json`

`assetbundle.json` 可由 `app.unity3d__assetbundle.json` 取得，不能按文件名精确
匹配误判为缺失。`strategy_battlefield_catalogue.json` 是另一张表，不能拿来代替
`strategy_battlefield.json`。

缺少的表不会被伪造。默认导入命令会在摘要中列出缺失项；需要让 CI 或部署脚本
把缺表当成失败时加 `--strict`。

## 运行时

`app/tables.py` 按清单校验文件名、root key 和 JSON 类型；文件 mtime 或大小变化时
自动重载。客户端 TextAsset 由 MiniJSON 写出，加载器兼容 `,}` / `,]` 尾逗号，
并对多段拼接 JSON 取首段。错误分为三类，便于区分故障链路：

- `UnknownTableError`：不在客户端清单或服务端运行时清单内。
- `MissingTableError`：清单已声明，但运行目录没有文件。
- `InvalidTableError`：JSON 损坏、root key 缺失或 root value 不是对象。

`TableCatalog.check()` 还会读取导入工具生成的 `import-manifest.json`，报告运行
文件与导入时 SHA256 不一致的漂移。
