# 云端服务部署与维护

日常 Codex、代码修改、资源转换、自动回归和原客户端调试均在物理机进行。
云服务器只运行游戏服务。主机地址、SSH 登录配置、数据库凭据均私有保存，示例只用占位符。
当前分工见 [本机开发与云端服务](remote-development.md)，本次迁移见
[切换验收](analysis/local-debug-cloud-service-20261117/README.md)。

## 正式运行布局

| 项目 | 配置 |
| --- | --- |
| 系统/依赖 | Ubuntu 24.04 LTS、Python 3.12 venv、MySQL 8.0；此表是本次运行环境，不是所有部署的硬限制 |
| 代码 | `/srv/onisoul/server` |
| Python | `/srv/onisoul/.venv/bin/python` |
| 资源 | `/srv/onisoul/assets/pc/{bundles,tables,web}` |
| 存档 | MySQL 正式库；库名和专用账号见私有环境配置 |
| 配置 | `/etc/onisoul/server.env`，root:root，0600；必须存在 |
| 代理抓取日志 | `/srv/onisoul/logs/server` |
| 服务日志 | `journalctl -u onisoul-stub -u onisoul-proxy` |
| 历史恢复资料 | `/srv/onisoul/backups`；普通代码/有本机原资源的发布不新增永久备份 |

客户端 → hosts → 本机 relay:80 → 云端 proxy80:80 → stub:18080 → MySQL。
服务以普通账号 oni 运行；proxy 单独获得绑定低端口的权限；stub 和数据库只监听回环。
开发服务 `onisoul-dev` 已停止且取消开机自启。

## 首次准备新主机

这部分只适用于空环境；**已有正式库不要重新初始化、清空或导入演示存档**。

1. 创建普通运行账号及上述目录，在 server 目录放已审核的服务代码。
2. 安装 Python venv 和 MySQL，创建虚拟环境，安装 requirements.txt。云端不需要运行完整逆向/媒体工具。
3. 创建独立正式数据库与专用账号，权限限于本库；密码在主机本地随机生成，不放命令行或 Git。
4. 从 `.env.example` 的变量清单准备 root 私有 server.env，填入正式库、资源和日志路径。
5. 空库使用 db/schema.sql 并核对登录 users 表；已有库必须按实际版本执行 db/migrations，不靠初始化自动升级。
6. 迁服先停源服务写入，导出一致性快照及私有恢复备份，在新库恢复，按表核对行数和内容摘要后启动。
7. 复制资源后逐文件校验 SHA-256，按已核对的恢复策略保留必要来源；正式切换后取消旧游戏服务自动启动。

安装 systemd 单元（仓库模板含运行目录，按实际布局检查后执行）：

```bash
sudo install -m 644 deploy/onisoul-stub.service deploy/onisoul-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now onisoul-stub onisoul-proxy
```

## 日常发布

本机改动、测试、PR、owner 合并分别记录；用户明确授权时可发布已测试的特性提交，
不因此自行合并 PR。先确定发布提交和各项变更：

- 代码：在干净的 server 工作树更新到指定提交，保留私有配置和未跟踪运行文件；版本通过 Git 追溯，无须另留代码归档。
- SQL：先备份，审查迁移的提交边界与回退方式；CREATE TABLE IF NOT EXISTS 不会补已有表的列或索引。
- 资源：按清单校验来源、目标及旧版本；已有本机验证来源时不额外留云端历史副本。
  47 国背景可通过 `--baseline --no-persistent-backup` 使用临时恢复，验收后清理；代码合并不自动上传资源。
- 客户端工具：在物理机重新安装相应启动脚本，不把私有连接配置提交到 Git。

服务更新后：

```bash
sudo systemctl restart onisoul-stub onisoul-proxy
systemctl is-active onisoul-stub onisoul-proxy
curl --noproxy '*' --fail http://127.0.0.1:18080/client/status
curl --noproxy '*' --fail http://127.0.0.1/client/status
journalctl -u onisoul-stub -u onisoul-proxy -n 40 --no-pager
```

再从本机检查公网与游戏域名，执行必要的临时账号 HTTP 冒烟并清理。
普通回归使用本机临时库；不得把云端玩家存档当测试夹具。
发布记录分开说明代码、SQL、资源、连接入口和原客户端验收。
两端代码对齐还应记录 Git HEAD；`ONI_BUILD_ID` 是运维发布标记，不能单凭标记相同断言代码完全相同。

## 备份与回退

数据库 dump、账号密码哈希、session、环境文件及恢复归档均是私有数据，不入 Git。
迁移恢复包保留旧代码、配置、日志、运行目录及当时的表备份；游戏资源另有已核对副本。
回退只恢复已验证的代码与对应数据，避免把新玩家写入覆盖成过时快照。
旧云主机已退出当前拓扑，回退必须依赖本机/现云端备份，不能要求旧机在线。
