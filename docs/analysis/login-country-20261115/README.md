# 登录保存、身份、国家选择与 E 盘缓存审核

> 以下是首轮历史记录。后续已完成 Qt 回填验收、线上重名清理/唯一约束，
> 定位并修复 LZMA 长度头导致的 OOM，并补上线 15 国图片。
> #67 后续验收见 [FOLLOWUP.md](FOLLOWUP.md)；最新姓名回包修复及语音补齐结果见
> [跨平台转换](../name-media-20261115/README.md)。

2026-11-15，基于已合并 #66（`6bdc688801ec92013942ca9eed300b2a6ac0f3ed`）。
本轮在同一分支提交两项修复和三项诊断；没有把资源检查成功算作 Unity 验收成功。

| 用户问题 | 核查结果 | 本轮落实及边界 |
| --- | --- | --- |
| 保存账号密码无效 | 页面原来只写 document.cookie，原 Qt 进程退出后不能保留；合成存储探针也未证明 localStorage 跨进程可用 | 改为受限本机服务，Windows DPAPI 加密；Node 页面行为与 Windows 保存/重启/清除测试通过。真实 Qt 回填尚未验收 |
| 玩家名字不是唯一 ID | players.player_id 已是主键；账号关联也有唯一约束。昵称没有查重，线上 7 个角色中已有 2 组非空同名 | 保留稳定 player_id，给昵称增加精确字节比较的唯一索引；registerName/createPlayer 均处理冲突。已有重名不自动改名，迁移暂不执行 |
| 国家选择白屏/不响应 | Windows 有 17:54、17:55 的 AppHangB1；对应 Unity 日志均有内存分配失败，不只是下载失败 | 保存错误行号/分配器摘要；本机 x86 EXE 未启用 Large Address Aware。未改可执行文件，未宣称修复了客户端内存问题 |
| 47 国头像、立绘、声音不全，最终决定停住 | 服务端只有 5 国图片 URL 可用，42 国 404；所有国家都缺至少一个随机出场语音候选 | 完成 47 国图片/出场语音逐条清单；原客户端证实最终决定要等语音结束才发 createPlayer |
| E 盘工具生成 cache 能否用 | 有图片重建包、原缓存副本、改名语音和跨平台转换文件，来源不同 | 17 国图片重建候选的 manifest 哈希/4 张贴图名通过，15 国可补现有图片缺口；未部署候选、未做 Unity 加载验收。发现两条语音实为第 3 条改名 |

## 登录保存修复

原 EXE 导入 enablePersistentStorage 不代表当前登录页就有可靠的跨进程存储。
使用不含用户凭证的合成标记，在 passport.86joy.com 页面和原启动器中测试，重开仍显示 first；
另一次出现白页，没有新的探针上报，因此不能声称单用 localStorage 已修好。

新实现：

- 页面不再把账号密码放进 HTTP Cookie；清除旧 oni_login Cookie。普通登录仍走原服务器账号校验。
- `tools/login_memory.py` 只绑定 127.0.0.1:19765，凭证读写要求精确 Host、passport Origin 和自定义请求头。
  其他网页来源、无 Origin 的凭证读取均拒绝。没有向云端提供“读取保存密码”接口。
- 文件默认 `%LOCALAPPDATA%/OniSoul/login.dpapi`，按 Windows 当前用户 DPAPI 加密；代码和日志不保存明文凭证。
  取消勾选清除保存文件；关闭游戏后辅助服务可继续工作。没有创建 Windows 开机启动项。
- `tools/start_login_memory.ps1` 可单独启动；`start_cloud_client.ps1` 也调用它。
  辅助服务不可达时，页面最多等待 2 秒，继续正常提交登录，不把用户锁在登录页。
  原登录尺寸和图像布局保持，不在云端备份用户密码。

本机启动示例（在本分支/合并后代码目录运行）：

```powershell
& .\tools\start_login_memory.ps1
```

端口占用时先核对服务身份，启动脚本不会停止未知服务。此前本机 80 relay 的旧进程记录不符仍存在，
单独启动登录保存不需要替换该 relay。

Windows DPAPI/HTTP 自动测试只使用临时目录与合成凭证，测试了服务重启后解密、取消保存、错误输入和跨来源拒绝。
页面 ES5 脚本通过 Node 模型验证回填、保存、清除和离线继续登录。
**自动审批拒绝了启动辅助服务并上传真机探针的组合命令，只返回 blocked by policy，未给更具体原因；
这部分没有执行。真实 Qt 的 CORS/回填仍待验收。** 未操作真实用户的登录凭证。

## 昵称与稳定身份

player_id 是存档与会话的稳定关联，不能把会变化的显示昵称替换成主键。
原 `LoginEnvironment.registerName` 读取 succeeded，失败后原命名页面已有本地化错误提示。
因此本轮保持响应结构，只在真正冲突时返回 succeeded=false。

`db/schema.sql` 的新库定义与 `db/migrations/20261115_unique_player_names.sql` 使用同一生成列：
从 `entity.username` 提取非空名称，按 UTF-8 原字节建立唯一索引；空名称为 NULL，允许多个未命名角色。
不推测原服是否折叠大小写、重音或异体字。名字仍存在原 JSON 中，索引不会重写 player_id 或存档。

数据库约束同时覆盖两个进程抢同名以及跳过 registerName 直接 createPlayer 的请求。
普通读取和未改名的保存不会重领资源。新增索引错误与其他数据库错误分开识别，不隐藏无关 SQL 故障。

**线上只读预览发现 2 组已有非空精确重名。** 因此不能直接执行 ALTER；必须先列出这些档案并由 owner
确定保留/改名方案、备份后再迁移。该 ALTER 遇到重名会失败，不自动加后缀或删除角色。
测试验证旧重名导致 DDL 失败时存档不变，解决测试重名后才成功建索引。

## 白屏证据与内存边界

源：用户本机 UnityWebPlayer 日志目录；最小摘录与精确行号见 [oom-evidence.json](oom-evidence.json)。
其中日志 log_189375b7ba782f4c8d7fc84c4fa89f5b.txt 显示：

- DynamicHeapAllocator out of memory；申请 102400 字节失败；
- ALLOC_CACHEOBJECTS used=1019155400，reserved=1054781440 字节；
- 另两份同日客户端日志出现相同内存分配失败，Windows 报 AppHangB1。

本机 EXE 为 PE x86（0x14c），Characteristics 的大地址位为 false。原客户端 AssetCache 有引用计数与
Unload(false) 释放路径（AssetCache.cs:41,112,146,158），不能仅凭一个大内存统计就指定是哪段代码泄漏。
白屏与大量预览/资源请求有关的具体触发次数、退出引用、贴图生命周期仍需受控复现与内存采样。

可后续评估低画质、释放国家预览贴图、修正请求失败清理，以及可回退的大地址兼容启动器。
大地址位只可能增加地址空间余量，不是内存泄漏修复；本轮没有悄悄修改原版 EXE、Unity DLL 或脚本。
也不能把新图片包只有约 1 MB 解压贴图，就推断它们能解决或必然导致约 1 GB 的缓存堆占用。

## 47 国资源与最终决定

完整清单：[country-assets.json](country-assets.json)。来源链：
beginning_equipment.<country>.questCharacters[0] → item01.parameterId → character.images / voice。

- LoginBushoCheck.cs:73–105 加载选中国家的首位武将图，要求 `_1_01/_1_02/_1_03/_3_01` 四张贴图；
  图片回调才开放国家决定按钮。
- VoiceTableAccessor.VoiceScene.Appearance=12，BattleVoiceManager.cs:168–190 从第 12 列随机选一条语音。
- LoginComfirmation.cs:100–133 先播放 Appearance，waitVoiceEnd 等 decideVoice.isEnd 才调用 createNewPlayer。
  所以最后决定无反应时，可能根本没有发 auth/createPlayer，不能只改服务端接口返回。
- 请求文件哈希为原资源名的 UTF-16LE MD5；AssetPathConverter 决定目录，Loader.getHashFilePath 执行哈希。

当前 HTTP 可获取图片的国家为 18、25、36、37、39。前两包与 E 盘重建候选字节完全相同；不能把五个包都称作原版缓存。
其余 42 国图片 URL 返回 404。country37 的四条出场语音只有 `_12_03/_12_04` 可获取，
`_12_01/_12_02` 缺失；其余国家也均未凑齐整个出场候选集合。
200 只代表 URL 可获取；内部名称、音频内容、原版来源和运行兼容分别核验。

这些缺失是 **stub has no assets**；如果接口没有实现才是 **no stub response**。
禁止用统一“成功”接口、空包或关闭声音后自动跳过来冒充原版流程。

## E 盘候选审核

重点检查了 E:/oni-soul/work/generated_chara_all_20261115（78 个包）、生成脚本及 manifest，
并核对旧工程的原缓存目录、E:/oni-soul/鬼武者魂/cache（167 条 Qt .d）、recovered 工作目录（312 个包）。
E:/oni-soul/cache 本身只有图标数据库，不能只凭目录名判断“cache 资源”内容。

生成清单是 68 个 TGA 重建 + 10 个标记为原缓存携带。47 国中有 17 国的重建候选，
四张 Texture2D 名称、非空图像数据与 manifest 文件哈希均匹配；68 不等于能补 68 个国家。
17 国中 18、25 两国线上已经有相同文件，新增潜力是另外 15 国：
03、04、07、08、09、10、11、13、19、23、24、29、30、35、47。
仍有 27 国图片在当前候选集中没有可补文件，也没有因此获得完整声音。

pack_chara.py 从模板更换 TGA/DXT5 和资源名重打包，属于有来源的重建资源，不能称为原包。
manifest 带生成时像素误差检查；本轮重新检查结构/指纹，不把旧报告的视觉测试当作本次真机测试。
下一步应在隔离资源层对一个新增国家验证头像、立绘、切换、回退和峰值内存，再批量接入。

另外在 official_cache 里找到 `_12_01/_12_02` 语音候选，但两个包的 AudioClip 数据哈希都与 `_12_03` 相同：
`5879446edf4f4e9a921afaa3e16d84de21c4eb5590cfeba5eaa7998190bdde46`。
把资源名归一为 `_12_03` 后，整个解压序列化内容也逐字节相等。
见 [voice-alias-evidence.json](voice-alias-evidence.json)。这些是仅名字不同的候选，不能补齐原版三条不同台词的证据。
`tools/alias_vse.py` 确有相邻语音改名功能；目录名 official_cache 不能洗掉这个证据边界。
如果选择用它们作为等待结束的兼容替代，需要另行明确标注，当前没有部署。

复查命令（UnityPy 为可选分析依赖，本轮用 E:/oni-soul/work/py313/python.exe）：

```powershell
python tools/audit_country_assets.py --tables <table-dir> --bundles <bundle-dir> --generated <generated-dir> --server http://<server> --output work/country-assets.json
```

## #66 部署与本轮状态

服务器已部署合并提交 6bdc688；备份路径 `/var/backups/onisoul/review66-20261115-101704-6bdc688`，
完整 SQL 已恢复到临时库并比对通过，7 份玩家状态哈希不变，表文件字节不变，两个服务 active。
第一次部署检查因测试清理过期会话使 sessions 从 9 变 8 而回退代码；核对变化只在 sessions 后，
再次部署比较角色与其他表，成功上线。没有恢复旧整库覆盖新进度。

**本 PR 的登录保存与昵称索引仍未部署**；尤其已有重名必须先处理，不能无条件上线。
本轮完整隔离 MySQL 回归 621 项：618 通过，3 项因可选 IL 依赖跳过；这 3 项在分析环境补跑通过。
新增迁移失败保档、并发同名/绕过检查、DPAPI 受限来源、保存重启/清除、登录页离线继续测试。

临时存储探针网页已从服务器移除；客户端已关闭；config.ini 原字节恢复（SHA-256
1db6e36bf219e8ac5711d62729ed74dca9e375c97de257a67e44e646c39bc52f）；隔离 MySQL 已关闭。
未改 hosts/现有 relay、原客户端二进制或真实玩家姓名，未把旧 E 盘资源直接混入线上。
