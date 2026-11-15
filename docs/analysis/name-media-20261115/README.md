# 姓名回包、服务端边界与跨平台素材转换

2026-11-15，接续已合并的 PR #67。本目录为最新结果，上一目录中的缺失数量是历史快照。

| 项目 | 已上线结果 | 验证边界 |
| --- | --- | --- |
| 姓名重复时联机中断 | registerName 改回布尔拒绝，不附 errorReason | 线上原会话重放 HTTP 200、存档指纹不变；真实 MySQL 并发唯一性及 HTTP 重试回归通过 |
| 国别选择的随机出场语音 | **47/47 国**的候选均可获取 | 表内共用 104 个唯一音频名；不是全游戏语音已恢复 |
| 小姓初次问候 | **40/40** | 8 名小姓，包含男女；每名 5 段随机候选 |
| 国别武将图片 | **20/47** | 本次未增加国别图片 |
| 小姓立绘 / 头像 | **4/40 / 5/40** | 按 40 种配色统计；立绘新增两张，头像未增加 |
| Android 转 PC | ETC 纹理、ARGB4444 界面图、音效各一项实际转换成功 | 3 项原生加载通过；音效完成静音播放。不表示安卓整个客户端或场景已移植 |

本次发布 **142 段语音、2 张立绘**。已有的 2 段 PC 语音和 2 张 PC 立绘保留原件。
全部新增文件经过线上 HTTP GET 回读及 SHA-256 校验。见 [发布清单](published-assets.json)
与 [完整表关联及 HTTP 状态](country-assets.json)。

## 姓名确认为什么显示联机中断

线上 19:52:30 的 auth/registerName 已经过客户端 → hosts → proxy80 → stub。
姓名已占用，数据库唯一索引正常拒绝；旧回包是 HTTP 200，但正文含
`{"succeeded":false,"errorReason":"player name is already in use",...}`。

直接核对原始 PC Assembly-CSharp.dll 的 IL（SHA-256
`b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e`）：

- GameRestarter.isError，RVA 0x70C60：包含 errorReason 即交给全局错误处理。
- WebApiClient.<_httpCall>.MoveNext，RVA 0x1F7B58：先错误过滤，再调用业务回调。
- LoginEnvironment.<registerName>.<>m__7EE，RVA 0x2300F8：读取布尔 succeeded。
- LoginTransNameEntry.<onResult>.MoveNext，RVA 0x20ED88：false 显示
  SYSTEM_MSG_LOGIN_ERR_NAME，关闭后清除 bNowRequesting，允许重新输入。

只修 registerName 的重名业务结果，保留唯一索引和 createPlayer 的二次保护。
这是接口回包不兼容，不能归为 no stub response，也不是资源请求失败。
旧错误窗口已被客户端暂停，需要关闭重开再试。
线上修复版本 955cdb9c64284b10267d35790b3a732cd4d704b0，备份
`/var/backups/onisoul/name-dialog-20261115-200756`。

## 本对话修改位置

| 改动 | 执行位置与服务端实现边界 |
| --- | --- |
| 登录路由、姓名回包、唯一索引、存档修复 | 服务端，无需修改游戏程序 |
| LZMA 长度修复、TGA / Android / PS3 转换 | 离线生成 PC 包后由服务端下发，无需修改游戏程序 |
| 登录页保存脚本 | 源码在服务端，下发后在客户端 Qt 网页中执行 |
| DPAPI 密码保存助手、启动脚本 | **本机辅助程序**；没有改 EXE、Unity DLL 或游戏程序集 |
| Frida 取证和资源验证 | 临时诊断，结束后撤销注入；测试对象停止、销毁、资源卸载，不写存档 |

原 Qt 壳的 cookie jar / localStorage 已做跨进程实验，没有保持登录凭据。
服务端无法在重开后识别一个不携带持久标识的客户端。安全等价的“记住密码”仍需本机保存，
或换成支持持久 cookie 的容器；不能仅凭 IP 识别同一用户，局域网尤其不能这样替代。
因此保留 DPAPI 辅助方案，游戏协议与资源修复均不依赖它。

## 来源与转换

上一轮只遍历 E 盘，遗漏 RPCS3 解包目录
`C:/RPCS3/dev_hdd0/game/NPJB00304/USRDIR/Media/Raw`。
目录共有 10,462 个 Unity 包：10,114 个语音、288 个建筑、60 个场景。
与 PC 表按 UTF-16LE 名称 MD5 匹配，得到 144 个精确同名语音，平台均为 10（PS3）。
旧 assets_serve/client/android 目录中的副本不能据目录名判为 Android。

音频链：嵌入音频 → FFmpeg 解码 → Ogg Vorbis quality 10 → 原 PC 3.5.6f4 AudioClip
模板（平台 7、MPEG 改 OGGVORBIS、内存加载）→ 重建对象大小/偏移/容器引用 →
确定长度的 UnityWeb/LZMA。每个包使用独立 archive 名，防止共用模板 GUID 冲突。
没有用改平台号、假音频别名或静音文件冒充转换。

三个 Android APK 去重后识别出 97 个媒体对象。实转 ui0_050_003_1 来自平台 13 的
ETC_RGB4，解码后编码 PC DXT5；server_comu 为 133×95 ARGB4444，使用 PC RGBA32
保留原尺寸；cancel 走音频链。这些是启动/UI 素材，不能替代缺失的国别或小姓图像。
另外重建 4 张同名 TGA 立绘，已有原版包的两张不覆盖。
检查 PS3 60 个场景、1,773 张纹理，没有当前所需国别或小姓图像的同名命中。

## 验证、限制和复用

[转换清单](conversion-manifest.json) 记录全部 151 包：144 PS3 语音、3 个 Android 示例、
4 张 TGA 立绘。145 段 AudioClip 在原 PC 引擎中时长/采样率/声道有效，6 张 Texture2D
尺寸正确。抽测 PS3 问候、PS3 出场和 Android cancel，静音 AudioSource 的 isPlaying
均从 true 自然变为 false。[原生结果](native-results.json) 不等于所有页面已经渲染验收。

引擎是 Unity 4.3.7f1 x86，SHA-256
`0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5`。
工具 tools/port_legacy_media.py 负责转换，tools/probe_legacy_media.py 仅接受此引擎指纹。
离线依赖见 requirements-media.txt，另需带 libvorbis 的 FFmpeg；Frida 17 仅用于原生验证。
所有源文件保留，命令行输出拒绝覆盖原文件及已有输出。

这是有损转码：最低解码 SNR 31.325 dB；142/145 段样本数完全一致，另 3 段少 128 样本
（48 kHz 下约 2.7 ms）。已有两段 PC 音频与 PS3 源对齐后的相关系数为 0.9799 / 0.9775，
见 [比较记录](original-pc-ps3-comparison.json)；没有称为原 PC 字节级还原。

Unity [3.5 音频文档](https://docs.unity3d.com/352/Documentation/Manual/AudioFiles.html)
支持 PC/WebPlayer 的 Ogg Vorbis 路径；[AssetBundle 平台说明](https://docs.unity.cn/520/Documentation/Manual/abfaq.html)
记录平台构建限制。文档支持转换方法，不提供缺失图片。网上资料尚未补齐图片，
**27 国图片、36 种小姓立绘、35 个小姓头像仍是 stub has no assets**。

空缓存测试还发现 /client/app.unity3d 404，已补上传未修改原始缓存包：
4,011,230 bytes，SHA-256 a374083f4662a5e3d2480058cbd2712d43c29035699b8d453dd749d19a45e9ce；
内含上述原始 b27be699… 程序集。HTTP 下载已验证，独立空缓存副本的完整启动仍未验收。
E 盘另有修改版启动包，本次上传没有采用那份。

资源回滚清单：`/var/backups/onisoul/media68-20261115-203539`。
本轮不改 hosts、本机/局域网配置和游戏原始尺寸，资源二进制不入 Git。
