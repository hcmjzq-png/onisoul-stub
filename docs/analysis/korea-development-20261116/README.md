# 韩国开发节点验收

2026-11-16 的历史环境验收，主机地址已脱敏。2026-11-17 起改为本机开发、云端运行，
当前分工及迁移结果见 [切换记录](../local-debug-cloud-service-20261117/README.md)。
服务端基线 `34b5361993a84114579a722ebe065735d37e6eda`（#78）；
本次只添加环境约定、开发 service 模板和隔离测试入口，不修改游戏业务规则。
操作入口见 [远程开发说明](../../remote-development.md)，原始摘要见 [acceptance.json](acceptance.json)。

## 已完成

| 项目 | 实测结果 |
| --- | --- |
| SSH | 使用本机私有 SSH 配置，以普通账号登录；维护账号独立保存 |
| 开发仓库 | `/srv/onisoul/repo`；独立工作树目录 `/srv/onisoul/worktrees` |
| 依赖 | Python 3.12.3、MySQL 8.0.46、.NET SDK 8.0.134、ilspycmd 9.1.0.7988；三份 requirements 已安装，pip check 通过 |
| 完整回归 | 656 项，655 通过、1 跳过、0 失败；跳过项为 Windows DPAPI 集成 |
| 真实 SQL 隔离 | I/E/新手三组真实 MySQL 测试开启；临时实例退出，数据目录清除 |
| PC 资源副本 | 23,099 文件逐一 SHA-256 相同；无遗漏、无额外文件 |
| 原版分析输入 | 程序集与既有原版取样摘要一致；25,174 方法体解析无失败；生成 2,034 个 C# 文件 |
| 开发服务 | `onisoul-dev` 启动且开机自启，监听 `127.0.0.1:18080` |
| 开发数据库 | 独立 `onisoul_dev`，专用账号；3306/33060 只监听本机 |
| HTTP 冒烟 | 注册、登录、命名、建号、重登、读取资源、编队保存、新手奖励、道路与建设等既有支持范围通过 |
| 其他检查 | 内存 gameplay 冒烟、契约检查通过；契约问题 0 |
| 本机连接 | SSH 转发 `127.0.0.1:19880` 后，`/client/status` 返回 HTTP 200/up；验收后关闭临时隧道 |

HTTP 测试账号已清理；开发库 users/accounts/players/sessions 均回到 0 行。
私有环境配置权限 0600。私钥留在 Windows；服务器仅有登录公钥，未配置个人 GitHub token。
资源传输期间曾发生 SSH 断开，视频经前缀比对后断点续传，最终全量校验通过。
这次结果证明环境可用，不承诺网络长期无波动。

## 资源来源与一致性

来源为旧服 `/opt/onisoul/assets/pc` 的 bundles、tables、web 当前副本。
逻辑文件字节总数 `1,354,668,340`；硬链接别名导致该数值不等于实际磁盘占用。
按 bundles、tables、web 顺序，各目录文件路径排序，将每个文件的
`相对路径 + NUL + SHA-256 + 换行` 累计散列，源/目标均为：

```text
25341146e69fe3db08be8ff20f382f688680a9fed9ad8f5b9270b2c3bb2c399f
```

本机可复用文件先核对实际字节摘要，再按源路径上传；剩余文件从旧服只读复制。
临时跨服传输公钥仅允许指定来源 IP 执行资源导出，完成后已撤销，临时私钥也已删除。
旧服 `onisoul-stub`、`onisoul-proxy` 最终均 active，代码仍为 `e7d905f4`，
既有 `mission_chain.py.bak-20261115` 保留，未发布新代码或迁移玩家存档。

原版程序集 SHA-256 为 `b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`，
依据 [原安装包取样记录](../static-review-20261115/source-proof.json)。
它单独存放于 sources，区别于运行资源中的客户端兼容补丁。

## 证据位置及范围

新节点 `/srv/onisoul/logs` 保留：

- `acceptance-20261116-r2/tests.log`、`summary.json`、MySQL 日志：完整回归。
- `dev-http-smoke.log`、`dev-gameplay-smoke.log`、`dev-contract-check.log`：服务与契约检查。
- `pc-original-il-verification.json`、`pc-decompile.log`：原版静态分析工具验收。
- `environment-acceptance.json`、`environment-assets-source.json.gz`：摘要与逐文件资源来源。

本次未做 Windows 原客户端流程复测，未切换玩家 hosts/入口，也未复制旧服账号、密码、存档。
23,099 是现有副本的一致性数量，不是“原游戏资源已齐全”；既有资源缺口与占位接口仍按
[系统台账](../../project-status/README.md) 跟进。
原始 PS3/Android 素材、PC 安装包全集及 Windows 调试工具仍保留在原位置。
