# 韩国节点开发环境

2026-11-16 配置。用户指定 `43.108.100.32` 作为后续开发节点，
现有游戏服务仍在 `43.143.69.215`。本机 Windows 继续承担 Qt/Unity 真机验收。

## 常用入口

本机已设置 SSH 别名，正常工作使用非 root 账号：

```powershell
ssh onisoul-kr
```

登录后：

```bash
cd /srv/onisoul/repo
source /srv/onisoul/.venv/bin/activate
git status --short
git fetch origin main
```

SSH 私钥在本机用户私有目录，未上传到新服务器。`onisoul-kr-root` 仅用于主机配置维护。
创建新分支前检查现有改动；多人工作使用 `/srv/onisoul/worktrees` 下的独立工作树。
服务器原有 `/opt/onisoul` 克隆保留，当前开发入口统一使用 `/srv/onisoul/repo`。

## 环境与目录

| 项目 | 配置 |
| --- | --- |
| 操作系统 | Ubuntu 24.04 LTS，x86_64 |
| 开发账号 | oni；普通开发不使用 root |
| Python | 3.12 虚拟环境；已安装服务端、IL 分析和媒体转换依赖 |
| 静态分析 | .NET SDK 8.0、ilspycmd 9.1.0.7988；`/srv/onisoul/bin/ilspycmd` |
| MySQL | 系统实例用于独立开发库；完整回归另起临时实例 |
| 其他工具 | Git、Node.js、FFmpeg、编译工具、rsync 等 |
| 内存 | 约 1.6 GiB RAM，另配置 2 GiB swap；避免并行启动多套重型任务 |
| `/srv/onisoul/repo` | 开发仓库 |
| `/srv/onisoul/worktrees` | 各任务独立代码工作树 |
| `/srv/onisoul/assets/pc` | 开发资源副本：bundles、tables、web |
| `/srv/onisoul/sources/pc-original` | 已按来源摘要校验的原版主包、解压容器、程序集；不入 Git |
| `/srv/onisoul/sources/pc-decompiled` | 新节点生成的原版 C# 反编译源码；不入 Git |
| `/srv/onisoul/config/dev.env` | 独立开发库私有配置，权限 0600 |
| `/srv/onisoul/logs` | 测试与环境验收证据 |
| `/srv/onisoul/test-runs` | 临时 MySQL 数据目录的父目录；正常测试退出后清理 |

资源按旧服务器实际文件摘要核对。开发库不复制旧服账号、密码或玩家存档。
PS3/Android 原始素材、原 PC 安装包及 Windows 工具仍以各自现有来源为准，
已发布 PC 资源副本不等于所有逆向原始材料都已搬到新节点。

原版程序集来源沿用 [安装包重新取样记录](analysis/static-review-20261115/source-proof.json)，
不把线上兼容补丁当作原版。IL 分析示例：

```bash
python tools/verify_il_bodies.py /srv/onisoul/sources/pc-original/Assembly-CSharp.dll
```

## 隔离数据库回归

在相应工作树执行，输出目录每次使用新名字：

```bash
/srv/onisoul/.venv/bin/python tools/run_isolated_mysql_tests.py \
  --temp-root /srv/onisoul/test-runs \
  --output /srv/onisoul/logs/acceptance-YYYYMMDD-HHMMSS
```

脚本使用新的临时数据目录、`--no-defaults` 和 `127.0.0.1:33365`，
启用 I/E/新手的真实 MySQL 测试。实例退出后停止进程并删除本次临时目录；
测试日志和摘要保留在输出目录。默认 3306 不允许作为这个测试实例的端口。
只有该临时实例使用无密码测试 root，系统 MySQL 和开发库保持独立认证。

Ubuntu 的 MySQL AppArmor 配置增加了仅限文件所有者的开发测试目录/日志目录规则，
原配置继续启用。原理见 [Ubuntu AppArmor 文档](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/)。
当前规则允许 `/srv/onisoul/test-runs` 和 `/srv/onisoul/logs`，换目录前先核对配置。

Windows DPAPI 和 Unity 画面不能在 Linux 回归中替代验收。通过和跳过数量须分别报告。

## 开发服务

`onisoul-dev.service` 使用独立 `onisoul_dev` 数据库与开发资源目录，
仅监听 `127.0.0.1:18080`。查看状态：

```bash
systemctl status onisoul-dev --no-pager
curl --noproxy '*' http://127.0.0.1:18080/client/status
```

需要从本机访问开发 HTTP 时使用 SSH 转发：

```powershell
ssh -N -L 19880:127.0.0.1:18080 onisoul-kr
```

本机访问 `http://127.0.0.1:19880/client/status` 可检查连接。
原 Unity 对域名有自己的处理逻辑，这条端口转发不能直接当作游戏完整联机配置。
本次不改玩家 hosts、不替换原有 relay，也不把开发库公开成新游戏服。

需在命令行执行数据库工具时，先加载这个节点的私有配置（不要打印文件内容）：

```bash
set -a
source /srv/onisoul/config/dev.env
set +a
```

上面的完整回归脚本自行覆盖数据库环境，使用临时 MySQL；普通 HTTP 冒烟使用开发库。

## 本次环境验收

见 [2026-11-16 验收记录](analysis/korea-development-20261116/README.md)。
这是开发环境就绪证明，不增加已完成玩法数量，也不替代 Windows 原客户端验收。

## Git 与后续交付

服务器能直接获取公开仓库。没有向服务器复制个人 GitHub token 或本机私钥，
因而读取仓库成功不表示已配置 GitHub 写入认证。
可以在远端完成编辑、测试和提交，经 Git bundle 带回可信本机发布分支/创建 PR；
如果后续需要服务器直接推送，再配置仓库范围的写入身份。

每次交付记录所用提交、环境、测试日志及资源版本。旧服代码、数据库迁移和资源发布，
仍按相应 PR 的部署计划执行；不能把新节点测试成功当作旧服已经更新。
