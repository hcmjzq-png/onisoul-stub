# 国家地图选择修复（2026-11-16）

PR #75 的全量媒体验收逐包加载后即卸载，没有覆盖国家图片同时驻留，也没有修改地图共享锁。
本次实际修复客户端状态与 18 个图片包；27 国缺图仍是 `stub has no assets`。
未发现地图点击卡点属于 `no stub response` 的证据：地图决定由客户端发出，尚未调用创建角色接口。

## 原因与修改

- 原 PC `LoginCharacterIcon.loading` 在下载前设置共享布尔锁 `BushoTrans`，只在成功回调解锁。
  其他国家失败可阻止当前已有头像的国家被选择；其他成功回调也可能提前解锁。
- `LoginColorMask.checkRegion` 现改为只检查当前活动头像的 `bLoadTexture` 与 `IsValid`。
  国家头像不再写共享锁，其他登录阶段的锁调用保留。
- 单个预览超过 30 秒仍未完成，取消该 sprite 的原加载回调、清除加载标志、停止转圈并显示“读取失败”。
  本次悬停内不逐帧重试；移开后再次悬停允许重试。已完成头像沿用原内存复用路径。
- 18 个不同图片包的内部序列化文件原本同名；改为各自序列化字节摘要生成的唯一名称。
  包内序列化数据、贴图字节、原始资源名全部保持一致，另两个无冲突包逐字节保留。
- chara HTTP URL 增加 `countryfix=country76-20261116a`，避开 Qt 已缓存的旧包。
  主包原有 `no-store` 响应策略保留；新开客户端取得新代码，无需清空全部客户端缓存。

补丁仅接受 SHA-256 为 `b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`
的原 PC 程序集；原主包为 `a374083f4662a5e3d2480058cbd2712d43c29035699b8d453dd749d19a45e9ce`。
修改后的程序集为 `05f8e6963aeee70bde0aa25b56457c0e800d1d655d160db0c4512f6d1a54bb39`，
主包为 `980438293373658772bf29aac1d87dbc545992cec3e7ff1db9d0d25d68342656`。
主包 25 个条目中，其余 24 个逐字节保留，仅替换 `Assembly-CSharp.dll`。
实际测试引擎为 Unity WebPlayer 4.3.7f1 x86；未按术语中的 Unity3.5.7 推断运行版本。

## 验证

- 严格 IL 解码：25,189 个方法体全部可解析，无失败。
- C# 策略测试 10 项通过，覆盖其他国家加载中/成功回调对当前点击的隔离、超时取消、再次悬停重试、内存复用及 URL 版本。
- Python 回归 656 项：627 通过、29 跳过。包括主包其他条目保留、发布前指纹拒绝、发布中断回滚。
- 实际引擎同时持有全部 20 个国家图片包，各自具名头像均为有效 128×128 Texture2D；
  不是依次加载并卸载。探针只在 Unity Update 内调用原生 API，结束后卸载测试包。
- 隔离账号真实 UI：蝦夷缺图显示“读取失败”；切回近江后头像可用，点击进入浅井长政大立绘页，确认按钮可用。
- 离线重建主包和 20 个图片包，输出摘要与发布计划完全一致。

`input-inventory.json` 是原始 47 国 HTTP 指纹；`release.json` 记录逐包修改前后摘要与内部名；
`native.json` 是同时驻留的实际引擎结果；`deployment.json` 是线上发布核对结果。
账号、令牌、完整日志、游戏二进制及测试配置只在忽略的 work 目录，未纳入版本库。

## 发布与缓存边界

线上资源于 2026-11-16 更新，备份目录 `/var/backups/onisoul/country76-20261116-022251`。
先备份并核对全部旧指纹，再原子替换 18 包，最后替换主包；21 个 HTTP 完整 GET 摘要核对通过。
两个其他国家包不变。服务未重启，部署前后 6 个玩家摘要相同（含 1 个隔离测试账号，验收后单独清理）。

正式本机链路：客户端 → hosts 127.0.0.1 → 现有本机 80 relay → 云端 proxy80 → stub。
预发布 UI 使用独立的 127.0.0.1:19876 转发和临时进程内下载路由；正式链路复测撤销该路由。
用户原客户端 EXE、hosts、config.ini、现有 80 relay 配置未修改。局域网其他机器未实际操作验证；
各机器需要重新启动客户端取得新主包，各自的图片请求会使用新版本缓存键。

缓存仍先复用当前头像/Loader 内存；国家图片不在原 FileDataBase 的 63 条 Unity 磁盘缓存表内，
因此走 `new WWW`，而不是 `LoadFromCacheOrDownload`。Qt HTTP 缓存可将下载结果写入本地
`cache/data7/`，并按响应头 `public, max-age=600` 管理；不保证所有图片已预装或永久离线。
第一次请求新版本包后，后续悬停继续复用，不应通过反复清空缓存处理真实缺图。

## 重建入口

1. 保留原 app、从中提取的 DLL，以及实际 Unity 引擎的 mscorlib/UnityEngine 引用。
   用 Windows .NET 3.5 csc 的 `/nostdlib /noconfig /target:library /optimize+` 编译
   `tools/client_country_fix.cs`；引用原 Assembly-CSharp、firstpass、mscorlib、UnityEngine。
2. PowerShell 7 执行 `tools/patch_country_client.ps1 -Original <原DLL> -Helper <helper.dll>
   -Output <新DLL> -CecilPath <Mono.Cecil.dll>`。本次使用 ilspycmd 8.2.0.7535 附带的 Cecil 0.11.4。
3. Python 安装 `requirements-analysis.txt` 后，运行 `tools/build_country_fix.py --app <原app>
   --assembly <新DLL> --inventory docs/analysis/country-select-20261116/input-inventory.json
   --source-dir <原始chara目录> --out <新目录>`。未提供 source-dir 时从指定 host GET 并核对原指纹；
   上线后应使用备份原文件离线重建，不能把已修改的线上包当作原输入。
4. 在尚未进入地图的隔离客户端运行 `tools/probe_country_bundles.py --pid <QA进程>
   --release <输出目录> --inventory <input-inventory.json> --out <原生结果.json>`。
5. `tools/publish_country_fix.py --release <输出目录> --assets <assets/pc> --backup-root <备份目录>`
   仅替换精确匹配旧摘要的文件，保存备份，异常时回滚已替换文件；不会运行数据库写入或服务重启。

回退应先退出使用新包的客户端，停止新旧包在同一进程混用，再按备份清单恢复原文件；
恢复前应核对当前文件仍为本次发布摘要，防止覆盖后续更新。27 国缺图需要真实资源来源补齐。
