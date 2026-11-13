# 配置表

客户端 `reset()` 要求 108 张 JSON 表，清单与 root key 见
`docs/analysis/table_list.tsv`。表文件体积较大，不进入 Git，统一放在
`assets/pc/tables/` 或 `ONI_TABLE_DIR` 指向的目录。

## 导入

```bash
python tools/import_tables.py --source /path/to/extracted/tables
```

工具只复制清单中的 JSON 文件，并生成 `import-manifest.json`，记录每张表的
SHA256、大小和加载状态。当前实测清单共 108 张：105 张存在，以下 3 张客户端
安装包未随附：

- `assetbundle.json`
- `combo.json`
- `strategy_battlefield.json`

缺少的表不会被伪造。默认导入命令会在摘要中列出缺失项；需要让 CI 或部署脚本
把缺表当成失败时加 `--strict`。

## 运行时

`app/tables.py` 按清单校验文件名、root key 和 JSON 类型；文件 mtime 或大小变化时
自动重载。错误分为三类，便于区分故障链路：

- `UnknownTableError`：不在 108 张清单内。
- `MissingTableError`：清单已声明，但运行目录没有文件。
- `InvalidTableError`：JSON 损坏、root key 缺失或 root value 不是对象。
