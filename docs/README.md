# 中文文档导航

看当前进度从 [系统清单](project-status/README.md) 开始。研究报告记录某次工作的结论，
可能已被后续修复取代；它们保留原时间和基线，不作为当前状态总表。

## 项目负责人常用入口

| 目的 | 文档 |
| --- | --- |
| 查看完成范围、缺口、下一步 | [系统与子项清单](project-status/README.md) |
| 安排仓库清理和代码重构 | [整理清单与顺序](repository-maintenance.md) |
| 查一个接口属于哪个系统 | [路由明细](project-status/endpoints.tsv)，普通阅读优先看系统清单 |
| 交给新聊天继续处理一个功能 | 给出系统子项编号、目标和最新主分支；按清单的交付要求执行 |

## 客户端启动与连接

已安装的入口是客户端目录下的 `Start-OniSoul.cmd`。当前项目曾在 `D:\鬼武者魂` 安装并验收，
安装来源是 [install_login_memory.ps1](../tools/install_login_memory.ps1)，
实际启动逻辑见 [start_client.ps1](../tools/start_client.ps1)。
它负责本机密码保存助手及原 EXE 的启动；网络配置、服务器是否运行需要另行核对。

| 连接方式 | 需要分清的事 |
| --- | --- |
| 本机运行服务端 | 原域名经 hosts 指向本机；本机 proxy80 转到本机 stub |
| 本机转发到云端 | 原域名指向本机；本机 80 relay 再转到云端 proxy80/stub |
| 局域网连接 | 指向实际承载服务的局域网主机；每台玩家电脑独立配置和验收 |
| 直连云端 | 原域名指向云端地址；不能把这种配置与本机 relay 配置混用 |

配置工具是 [configure_client.ps1](../tools/configure_client.ps1)，默认预览，`-Apply` 才写入。
云端 relay 启动工具会检查已占用的 80 端口是否属于记录中的进程；匹配失败需要核对实际进程。
操作范围见 [工具索引](../tools/README.md)，过去配置证据见 [连接审核](audit-20261115.md)。

## 开发与部署

| 目的 | 文档 |
| --- | --- |
| 在新韩国节点开发和测试 | [远程开发环境](remote-development.md) |
| 安装依赖、启动服务、运行检查 | [开发说明](development.md) |
| 理解程序怎么连接 | [架构说明](architecture.md) |
| 找到已接入和候选玩法代码 | [业务代码索引](../app/business/README.md) |
| 首次部署 Ubuntu 服务 | [部署说明](deploy.md)，已有服务器更新须另列迁移与资源项 |
| 查询接口字段的依据 | [接口来源](api_schema.md)、[响应形状](response-shapes.md) |
| 查询会话权限和原表加载 | [鉴权](auth-guard.md)、[配置表](tables.md) |

## 最新主题证据

这些是按主题挑选的验收记录；日期范围内的局部成功不表示全游戏完成。

| 主题 | 记录与范围 |
| --- | --- |
| 国家地图选择 | [#76 修复与正式链路验收](analysis/country-select-20261116/README.md) |
| 全量转换媒体 | [#75 线上原生加载验收](analysis/media-network-20261115/README.md) |
| 姓名冲突回包、国家和小姓语音 | [#67 后续修复](analysis/name-media-20261115/README.md) |
| 保存账号密码、昵称唯一、LZMA 内存错误 | [#67 后续验收](analysis/login-country-20261115/FOLLOWUP.md) |
| 新手唤醒、逐步解锁和经验 | [#65 实测及 #66 经验修复记录](analysis/research-331/review/deployment65-20261115.md)，该页的“经验尚未部署”是当时状态，后续见 #67 记录 |
| 好友与四资源包裹 | [SQL/HTTP 接入验收](analysis/research-331/review/deployment-acceptance-20261115.md)，Unity 社交验收另计 |

## 历史研究与原版证据

| 资料 | 用途 |
| --- | --- |
| [PC 安装包记录](evidence-inventory.md)、[程序集核查](analysis/pc-assembly.md) | 追溯原始输入及后续纠正 |
| [静态分析总索引](analysis/README.md) | 查询原接口、消费点、类型和资源命名 |
| [A–H 初轮汇总](analysis/parallel-342/review/README.md)、[二轮汇总](analysis/parallel-342/review-round2/README.md) | 解释当时为何接入或暂缓某项 |
| [331 项研究与九组汇总](analysis/research-331/README.md) | 保存分工、候选和取证；不是当前待办数量 |
| [早期启动器复现](repro-launcher-login.md)、[早期玩法说明](gameplay-onboarding.md) | 查看演变过程，不代替当前启动和进度说明 |

`docs/analysis` 中有六份仍被程序读取的契约/表清单，另有测试、发布工具引用的证据。
目录名含日期或文件看起来重复，都不能直接推断可以删除。具体依赖见 [整理清单](repository-maintenance.md)。
