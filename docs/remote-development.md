# 本机开发与云端服务

2026-11-17 起采用以下分工。旧云主机退出运行，后续部署、素材读取和调试不能依赖它。
具体服务器地址和凭据只保存在私有配置；本文中的 `<server>` 等标记需要在本机替换。

| 位置 | 工作 |
| --- | --- |
| 本机物理机 | Codex 对话、编辑、逆向分析、媒体转换、完整回归、Qt/Unity 原客户端验收 |
| 云服务器 | 正式 stub、proxy80、MySQL、游戏资源；健康检查、备份和必要的发布验收 |
| GitHub | 可公开的代码、模板、原版依据和脱敏验收记录 |

不在云服务器运行 Codex、反编译全量任务或完整测试套件。隔离 MySQL 脚本支持 Windows/Linux，
本机可使用免安装 MySQL 运行全量回归；原客户端和调试工具也留在物理机。
真实 SQL 测试需要独立本地数据库，未满足条件的跳过项必须明确报告。

## 日常启动

本机已安装双环境管理器时，使用桌面的 **鬼武者魂－本地测试** / **鬼武者魂－云端正式**。
启动器先核对服务角色和实例 ID；正在运行游戏时禁止切服，不自动转接另一环境。
本地测试的服务、资源和独立 MySQL 都运行在物理机，断开云端也能测试已有本机资源。
本机持久测试库和全量回归的临时库仍分别隔离。

| 模式 | 链路 | 数据 |
| --- | --- | --- |
| 本地测试 | hosts → 本机 gateway:80 → 本机 proxy:18082 → stub:18081 → MySQL:3307 | 本机独立库 `onisoul_local_test`，不导入云端玩家 |
| 云端正式 | hosts → 本机 gateway:80 → 云端 proxy:80 → stub:18080 → MySQL | 云端原玩家库 |

启动器私有配置位于 `%LOCALAPPDATA%\OniSoul\environments\profiles.local.json`；
运行数据、资源、客户端副本和日志位于配置的 runtime_root。原游戏尺寸不变。
本地密码保存助手使用 19766 和独立 DPAPI 文件；云端沿用 19765。
原客户端仍可被直接执行，因此应通过桌面入口启动。两个模式共用原域名与 80 端口，
无法同时打开；不要绕过启动器切换。系统级 Unity 缓存不承诺按客户端目录完全隔离。

首次搭建：使用稳定的独立 Python 安装创建 venv，安装 `requirements-local.txt`；
用 `tools/mirror_pc_assets.py` 只读复制云端 bundles/tables/web 并校验每个 SHA-256，
可通过 `--local-cache` 复用本机内容一致的文件，不复制数据库。
`tools/game_environments.py --action configure --help` 列出私有配置所需参数；
配置后用 `--action backend` 初始化独立本机库。最后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/install_game_environments.ps1 -Config '<private-profiles.json>'
```

安装器备份旧桌面入口和 Start-OniSoul.cmd。服务进程按 PID、可执行路径和创建时间管理，
遇到未知端口占用会停止操作。默认云端使用 HTTP 直连；私有配置 `cloud_transport=ssh`
可使用本机 SSH 隧道，仍须核对同一云端实例，不作为自动回退。
本轮范围和验收见 [双环境记录](analysis/game-environments-20261117/README.md)。

给客户端安装云端启动入口后，双击客户端目录里的 `Start-OniSoul.cmd`。
它读取本机私有连接配置、检查/启动本机 relay 和密码保存助手，再打开原游戏。
私有配置默认位置：`%LOCALAPPDATA%\OniSoul\connection.local.json`。
首次配置按 [连接配置模板](../config/connection.example.json) 在本机填写。

安装入口（会备份既有启动文件）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/install_cloud_client.ps1 -ClientRoot '<client-root>'
```

原游戏域名继续映射本机回环，网络链路为：

```text
原客户端 → hosts → 本机 relay:80 → 云端 proxy80:80 → stub:18080 → MySQL
```

本机 relay 留日志便于排查。它的监听仅在回环；局域网其他电脑仍须独立安装、配置和验收。
已有 relay 切换服务器需要 `-RestartRelay`，脚本只停止能核对 PID、启动时间、命令路径和端口归属的进程。
无记录或进程不匹配时，必须先核对，不能盲杀占用 80 端口的程序。

## 本机开发

从最新 main 创建独立工作树，保留其他聊天的未提交改动。在本机安装 requirements：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-analysis.txt -r requirements-media.txt
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

完整 SQL 回归使用本机 MySQL 可执行文件，不安装系统服务、不使用玩家库：

```powershell
& .\.venv\Scripts\python.exe tools/run_isolated_mysql_tests.py --mysqld '<mysql-dir>/bin/mysqld.exe' --output work/local-sql-acceptance
```

输出目录必须是新目录。临时实例仅回环监听，测试后正常关闭并删除临时数据；日志留在输出目录。
MySQL 可使用 [官方免安装 ZIP](https://dev.mysql.com/doc/refman/8.0/en/windows-install-archive.html)。
按 [本机开发配置模板](../config/development.example.json) 保存私有
`%LOCALAPPDATA%\OniSoul\development.local.json` 后，可直接运行 `powershell -File tools/test_local.ps1`。

本地数据库、资源路径使用本机环境变量；真实玩家库不用于普通回归。
已验证来源的原版输入、反编译源码、转换产物和本机客户端分别保留，不把补丁当原版。
资源恢复与未实现玩法继续按 [系统台账](project-status/README.md) 推进。

## 云端运行和发布

| 路径 | 用途 |
| --- | --- |
| `/srv/onisoul/server` | 正式服务代码 |
| `/srv/onisoul/.venv` | 服务 Python 环境 |
| `/srv/onisoul/assets/pc` | bundles、tables、web |
| `/srv/onisoul/data` | 运行数据 |
| `/srv/onisoul/logs/server` | 代理抓取日志 |
| `/srv/onisoul/backups` | 私有迁移/回退备份；不入 Git |
| `/etc/onisoul/server.env` | root:root、0600；正式数据库及资源路径 |

`onisoul-stub` 以普通账号运行，只监听 `127.0.0.1:18080`；
`onisoul-proxy` 对外监听 80；MySQL 仅回环。两项游戏服务开机自启。
之前的 `/srv/onisoul/repo`、开发库和开发服务是历史环境，不再作为正式运行入口。

```bash
ssh <server-alias>
systemctl status onisoul-stub onisoul-proxy --no-pager
curl --noproxy '*' --fail http://127.0.0.1:18080/client/status
curl --noproxy '*' --fail http://127.0.0.1/client/status
```

本机完成改动和回归后创建 PR；owner 合并。发布时核对代码、SQL、资源是否各自有改动，
先备份再更新，只在云端做必要验收。详见 [部署说明](deploy.md)。
迁移及客户端入口的实际验收见 [本次切换记录](analysis/local-debug-cloud-service-20261117/README.md)。

## 公开资料与私有配置

禁止把真实服务器 IP、SSH 私钥/位置、token、数据库密码或玩家存档写入 GitHub 文件、
PR 描述及公开附件。示例使用占位符；`*.local.json`、`*.local.ps1`、`*.local.toml`、
`*.env`、`*.pem`、`*.key`、work 和 logs 均被 Git 忽略。
提交前运行 `python tools/check_public_config.py --staged` 并检查整个暂存差异。
脚本检查公网 IPv4 字面量、凭据标记和私有文件名；不能替代人工审核或历史清理。

此前的公开记录中的真实主机地址已脱敏；Git 历史仍保留原提交，不在普通 PR 中重写历史。
