# 开发入口

功能范围和验收状态见 [项目进度](project-status/README.md)。本页面向需要运行或修改代码的人，
日常启动游戏见 [中文导航](README.md#客户端启动与连接)。

服务端后续默认使用 [韩国远程开发节点](remote-development.md)；本机保留客户端验收能力。

## 依赖与配置

Python 3.12+；服务端外部依赖见 [requirements.txt](../requirements.txt)，当前为 PyMySQL。
逆向分析和媒体转换分别使用 [requirements-analysis.txt](../requirements-analysis.txt)、
[requirements-media.txt](../requirements-media.txt)，按相应工具要求安装在独立环境中。

在仓库根目录建立虚拟环境，例如 Windows PowerShell：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

服务端只读取进程环境变量。`.env.example` 是变量说明，复制成 `.env` 不会自动生效；
需要由 shell 或部署系统注入。Ubuntu 的现有 service 使用 `/etc/onisoul/stub.env`。
真实账号/密码和资源包不提交到 Git。

运行需要 MySQL、所选环境的配置及游戏表/资源。服务入口是：

```powershell
& .\.venv\Scripts\python.exe -m app.main
```

`python -m app.main --init-schema` 只用于准备好配置后的建库/建表；
它会创建配置指定的数据库，并导入 `CREATE TABLE IF NOT EXISTS`。
**已有表不会因此自动获得后来新增的列或索引**，升级要核对 [迁移文件](../db/migrations/)。
MySQL DDL 的提交边界与普通业务事务不同，已有数据库应使用专门的迁移和备份计划。

## 程序入口与原版契约

- [app/main.py](../app/main.py) 创建正常注册器，先接入专用处理器，再为剩余原接口补默认处理器。
- [业务索引](../app/business/README.md) 说明哪些模块已接入、哪些只作为候选。
- [contract.py](../app/business/contract.py) 读取 `docs/analysis/api_contract.tsv`、
  `behavior_contract.tsv`、`api_call_graph.tsv`；它们不是废弃文档。
- [tables.py](../app/tables.py) 使用 `table_list.tsv`、`server_tables.tsv`、`quest_tables.tsv`
  三份清单加载实际 JSON 表。资源位置由 `ONI_PC_*`、`ONI_TABLE_DIR` 指定。
- [response_shapes.py](../app/business/response_shapes.py) 区分普通回包、裸映射和特殊索引回包。
  原客户端会遍历根表，不能给所有接口统一添加字段。

没有 `config/responses.example.json` 模板加载机制；旧空模板已移除。
当前业务实现走处理器，未实现部分走契约默认处理器。`ONI_CONFIG_DIR` 的旧路径导出暂时保留兼容，
它不表示修改该目录就能修改接口返回。

## 检查与测试

结构检查和当前路由导出：

```powershell
& .\.venv\Scripts\python.exe tools/contract_check.py
& .\.venv\Scripts\python.exe tools/export_system_status.py --output work/current-status
```

第二条只写本地输出文件，不连接数据库；核对后再更新 `docs/project-status` 的正式清单。

自动回归：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests
```

部分测试需要显式开启的隔离 MySQL 或可选分析依赖。报告通过、跳过和失败数量；
跳过不算通过。真实数据库测试使用独立测试库，不能把生产存档当普通测试样本。

具备真实表目录时，可以运行内存玩法检查：

```powershell
& .\.venv\Scripts\python.exe tools/gameplay_smoke.py --table-dir assets/pc/tables
& .\.venv\Scripts\python.exe tools/progression_smoke.py --table-dir assets/pc/tables
```

内存检查不等于原客户端验收。`http_smoke.py`、`social_http_smoke.py` 则会在目标服务创建/清理
临时测试账号，操作性质不同，先读 [工具索引](../tools/README.md)。

## 修改与交付

按 [系统子项](project-status/README.md) 确定范围，每个 PR 更新对应能力、证据和验收结果。
协议字段来源写入 [api_schema.md](api_schema.md)，内部存档设计与原版线协议分开标识。
重构应先保持回包、存档和接入清单不变，再由后续功能 PR 扩展能力。

运行布局见 [架构](architecture.md)，发布步骤见 [部署](deploy.md)，审批与分支要求见
[CONTRIBUTING.md](../CONTRIBUTING.md)。原版程序集分析入口见
[PC 程序集](analysis/pc-assembly.md)、[IL 分析](analysis/il-static-analysis.md)；
安装包 `data.bin` 的已核实性质见 [固定填充验证](analysis/data-bin-verification.md)。
