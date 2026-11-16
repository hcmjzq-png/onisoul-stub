# 鬼武者魂项目工作约定

## 开发位置

本机物理机运行 Codex、代码编辑、逆向分析、资源转换、自动回归和原 Qt/Unity 客户端调试。
云服务器仅运行游戏服务端、MySQL 和必要运维；不要在小内存云主机启动 Codex 或完整回归。
本机使用独立 `codex/` 工作树，云端运行目录为 `/srv/onisoul/server`，
虚拟环境 `/srv/onisoul/.venv`，资源 `/srv/onisoul/assets/pc`。
本机测试入口为 `powershell -File tools/test_local.ps1`；Python/MySQL 位置读取
`%LOCALAPPDATA%\OniSoul\development.local.json`，实际值不进仓库。
工作方式与部署入口见 [本机开发与云端服务](docs/remote-development.md)。

旧云主机已退出当前拓扑，后续工作不能依赖它。真实主机地址、SSH 别名/密钥位置、
数据库凭据和个人连接记录只放本机私有配置，不提交到 GitHub、PR 描述或公开验收文件。
仓库例子用 `<server>`、`<client-root>` 等占位符；回环地址和原游戏域名属于协议配置。
提交前运行 `python tools/check_public_config.py --staged`，并人工检查暂存差异。

## 项目规则

- 先读 [系统台账](docs/project-status/README.md)，按系统子项交付并更新验收记录。
- 不编造原版文件、接口、字段或规则；不确定时明确标记，区分原版证据、本服内部设计和兼容补丁。
- `stub has no assets` 是资源缺失；`no stub response` 是缺少业务实现/可信状态。
- 排错顺序：客户端 → hosts → proxy80 → stub；本机、局域网与云端配置分别核对。
- 游戏保持原始尺寸；调试监控面板与游戏等大对齐。
- 调试使用本机独立库或临时实例，不拿云端玩家存档做普通测试；云端只做必要健康/发布验收。
- 路由已接入、代码已合并、服务已部署、原客户端已验收分别记录，不以测试数量冒充玩法完成。
- 使用独立 `codex/` 分支和工作树，保留用户及其他聊天的改动。owner 审批并合并 PR，代理不自行合并。
- 输出精简中文，代码引用给文件和行号。遵守 [协作规范](CONTRIBUTING.md)。
