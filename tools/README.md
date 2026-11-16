# 工具用途与操作范围

日常玩游戏使用客户端目录中的 `Start-OniSoul.cmd`。这里大部分工具服务于开发和资源恢复，
文件名带 `audit`、`smoke` 或 `repair` 不代表只读，按下面列出的操作范围选择。

## 启动和连接

| 工具 | 用途 | 影响范围 |
| --- | --- | --- |
| [install_login_memory.ps1](install_login_memory.ps1) | 给指定客户端安装保存助手和启动入口 | 写入客户端的 `OniSoul-LoginMemory` 目录及 `Start-OniSoul.cmd` |
| [start_client.ps1](start_client.ps1)、[start_login_memory.ps1](start_login_memory.ps1) | 启动本机保存助手/游戏 | 创建本机进程；助手通过 DPAPI 保存本 Windows 用户的凭据 |
| [login_memory.py](login_memory.py) | 本机登录保存服务 | 监听本机端口，保存或清除加密凭据 |
| [configure_client.ps1](configure_client.ps1) | 预览本机/局域网/云端连接配置 | 默认预览；`-Apply` 才备份并修改 config.ini/hosts，依选项决定是否写 hosts |
| [start_cloud_client.ps1](start_cloud_client.ps1) | 创建/检查本机 80 relay，再启动游戏 | 进程、日志、relay 记录；既有端口不匹配时拒绝继续 |
| [proxy80.py](proxy80.py) | HTTP 转发与脱敏日志 | 监听端口、访问上游、写日志 |

本机、局域网和云端的说明见 [中文导航](../docs/README.md#客户端启动与连接)。

## 检查和进度

| 工具 | 用途 | 影响范围 |
| --- | --- | --- |
| [contract_check.py](contract_check.py) | 契约、调用图和批次结构校验 | 只读仓库输入 |
| [export_system_status.py](export_system_status.py) | 按系统导出全部路由状态 | 写指定输出目录；不调用接口、不连接 DB |
| [endpoint_progress.py](endpoint_progress.py)、[index_remaining_endpoints.py](index_remaining_endpoints.py) | 旧接口研究快照/索引 | 会写报告；旧默认目录可能是历史研究目录，先检查参数和目标 |
| [gameplay_smoke.py](gameplay_smoke.py)、[progression_smoke.py](progression_smoke.py)、[trophy_smoke.py](trophy_smoke.py) | 使用表数据做内存玩法检查 | 隔离内存状态；不等于自然通关或 Unity 验收 |
| [http_smoke.py](http_smoke.py)、[social_http_smoke.py](social_http_smoke.py) | 对目标服务做 HTTP 验收 | 创建、操作和清理临时账号/存档，需要目标环境配置 |

## 原版程序与表分析

| 类别 | 入口 | 操作范围 |
| --- | --- | --- |
| 程序集检查与反编译 | [check_pc_assembly.py](check_pc_assembly.py)、[decompile_pc_assembly.py](decompile_pc_assembly.py) | 读取原程序集，反编译写指定目录；指南见 [PC 程序集](../docs/analysis/pc-assembly.md) |
| IL、字段与响应分析 | `oni_il.py`、`verify_il_bodies.py`、`extract_key_types.py`、`extract_read_context.py`、`extract_response_shapes.py`、`verify_response_shape_evidence.py`、`classify_http_methods.py`、`analyze_callbacks.py`、`il_unguarded_reads.py`、`unguarded_reads.py` | 分析与报告；命令顺序见 [IL 分析](../docs/analysis/il-static-analysis.md) |
| 接口及城市/关卡证据 | `audit_client_endpoints.py`、`audit_city_tables.py`、`audit_quest_tables.py` | 读取指定代码/表，生成证据报告；不自动开放玩法 |
| 表与缓存提取 | `extract_tables_from_bundle.py`、`extract_cached_bundles.py` | 写提取产物，不代表已经发布 |
| 安装包填充验证 | [verify_pc_data_bin.ps1](verify_pc_data_bin.ps1) | 读取验证；结论见 [证据](../docs/analysis/data-bin-verification.md) |

## 媒体转换与客户端诊断

| 类别 | 入口 | 操作范围 |
| --- | --- | --- |
| 国家资源审计 | [audit_country_assets.py](audit_country_assets.py) | 读表、包及可选线上资源状态，写报告 |
| 批量扫描与媒体转换 | `audit_legacy_media.py`、`port_legacy_media.py`、`port_ps3_movie.py` | 依子命令读取来源、调用转换依赖并写产物；不等于只读扫描 |
| 包长度修复 | [repair_unityweb_lzma.py](repair_unityweb_lzma.py) | 默认检查；明确输出路径时生成修复副本 |
| 原生加载/内存探针 | `probe_legacy_media.py/.js`、`probe_country_bundles.py`、`probe_unity_lzma_size.py` | 连接指定客户端进程做诊断；需匹配引擎与隔离验收环境 |
| 国家选择兼容补丁 | `client_country_fix.cs`、`patch_country_client.cs/.ps1`、`build_country_fix.py` | 构建新程序集/包，须匹配原输入指纹；详见 [#76 记录](../docs/analysis/country-select-20261116/README.md) |
| 下载公共组件 | `media_http.py` | 供媒体工具调用的 HTTP 功能；不是独立玩法服务 |

媒体工具依赖见 [requirements-media.txt](../requirements-media.txt)，当前转换与原生验证边界见
[媒体记录](../docs/analysis/media-network-20261115/README.md)。

## 发布和存档修复

| 工具 | 影响范围 |
| --- | --- |
| `import_tables.py`、`publish_verified_tables.py` | 向指定运行表目录写入/发布表文件；读取清单与来源证明 |
| `publish_converted_media.py`、`publish_country_fix.py` | 根据计划写资源目录并备份；不能只因文件已转换就直接覆盖上线 |
| `repair_initial_mission.py`、`repair_starter_rosters.py` | 审核/修复特定旧存档；执行模式与前置条件以各脚本参数为准 |
| `cleanup_duplicate_players.py` | 重名预览与按计划清理存档；会涉及删除，先核对具体计划及备份 |

这些工具必须和相应 PR 的输入指纹、目标环境、备份及验收记录一起使用。
代码合并不会自动执行 SQL 迁移、上传资源或安装本机助手。
