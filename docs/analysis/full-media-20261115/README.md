# PS3 / Android 全量资源转换核查

2026-11-15，接续 [上一轮 151 包验证](../name-media-20261115/README.md)。
**累计完成 12,162 个 PC AssetBundle，全部在原 PC 引擎中按名称加载通过；
另完成 1 个无损 MPG 视频。媒体转换失败 0 个。**
本轮相对已转换的 147 个 PS3 / Android 对象，新增 **12,015 个 PC 包和 1 个视频**。
上一轮另有 4 张 TGA，来源不在本次 PS3 / APK 范围，未重复累加。

后续审查修复与增量发布约束见 [PR #69 审查记录](review-69.md)。下文“未上传”指首次转换阶段。

| 来源及类型 | 此次可转 / 累计已转 | 上轮已转 | 本轮新增 | 最终失败 |
| --- | ---: | ---: | ---: | ---: |
| PS3 AudioClip | 10,095 | 144 | 9,951 | 0 |
| PS3 Texture2D | 1,969 | 0 | 1,969 | 0 |
| PS3 原始 PNG | 1 | 0 | 1 | 0 |
| Android AudioClip | 14 | 1 | 13 | 0 |
| Android Texture2D | 72 | 2 | 70 | 0 |
| Android 原始 PNG | 11 | 0 | 11 | 0 |
| **PC 包合计** | **12,162** | **147** | **12,015** | **0** |
| PS3 PAMF → PC MPG，独立视频文件 | 1 | 0 | 1 | 0 |

PS3 合计 12,065 包，Android 合计 97 包。原始 PNG 本来就是通用图像格式，本次也实际
重建为 PC Texture2D 包并验证；Android nine-patch 的像素可以复用，原 Android 拉伸布局规则
没有移植。**45 段 PS3 音频源本身全静音**，已明确标记并保留原始占位，不算恢复了 45 段说话内容。

## 数量口径与来源

- PS3：`C:/RPCS3/dev_hdd0/game/NPJB00304/USRDIR/Media/Raw`，10,462 包：
  10,114 个 vse 包、288 个建筑包、60 个 scene 目录包；另有 PAMF 视频及存档图标 PNG。
- Android：`E:/oni-soul/downloads` 下 `gwzsoul_1.00.15_20140217.apk`、
  `onisoul_1.00.13.apk`、`onisoul_1.00.18.apk`；指纹见 [summary.json](summary.json)。
- 按“平台 + Unity 类 + 完整序列化对象字节”去重：13,953 次媒体对象出现，得到
  12,150 个 AudioClip / Texture2D。不是按文件名去重；同名不同内容的版本均保留。
  Android 上一轮 97 条 Unity 媒体记录去掉 11 个重复对象后为 86 个，
  本轮另从 APK 提取的 11 个原始 PNG 是另一组资源，不是重复计数。
- APK 的 Data 目录去重后 102 个成员，96 个可解析为 Unity 序列化文件，
  另 6 个为配置 / XML / PNG 等非序列化文件，非 Unity 解析错误。
- 最终实际新写 12,029 个 PC 包，复用已验证原文件 133 个；其中 14 个此前已转换对象
  因此次去重选到场景内副本重新生成，因此“新写文件”比“新增独立资源”多 14。

## 哪些尚不能作为完整 PC 资源使用

| 范围 | 数量 / 单位 | 原因与已完成部分 |
| --- | --- | --- |
| PS3 建筑整包 | 288 包 | 已提取贴图；尚未重建网格、动画、材质及组件引用 |
| PS3 scene 目录整包 | 60 包 | 已提取其中可用媒体；场景对象图、脚本绑定和平台 Shader 尚未重建 |
| Android 完整客户端 | 3 个 APK | APK、Android 原生 `.so` 与启动运行环境不能直接供 PC Qt / x86 WebPlayer 使用；本次只重建其媒体 |
| PAMF 的 Unity MovieTexture 包 | 1 个视频 | 已生成可解码的 PC MPG；未取得并验证 PC MovieTexture 模板，不能把 MPG 算作已移植的 Unity 视频包 |

**348 个 PS3 完整容器和 3 个 APK 尚未整包移植**，不是 351 个损坏媒体。
这些容器已经贡献了上表转换成功的音频 / 贴图，不能与媒体对象数相加或相减。
“未实现整包转换”也不意味着以后无法重建。

例如 PS3 仍有 Mesh 5,850 次、AnimationClip 2,652 次、Material 1,605 次、Shader 27 次、
TextAsset 301 次；Android 仍有 Mesh 84 次、Shader 83 次、TextAsset 5 次、Font 1 次等。
这是对象出现次数，完整类别统计在 summary.json。文本、字体和二进制附属数据未冒充成已完成
的 PC 对象图；文本可能可复用，但建筑 `.bin` 等内容的 PC 解释尚未验证。

按上一轮 PC 表构造的 268 个国别 / 小姓目标图片名，在此次完整媒体目录中精确命中 **0**。
上一轮的 **27 国图片、36 种小姓立绘、35 个头像**缺口仍未从这些来源补齐，属于
**stub has no assets**。本次没有发现或修复 **no stub response**。

## 实际修复和验证

转换沿用原 PC 3.5.6f4 模板、平台 7、确定长度 UnityWeb/LZMA，实际解码音频 / 图像后重建，
不是只改平台号。新增以下批量转换修复：

1. 用 path ID 区分同一序列化文件中的同名对象；输出 archive 标识同时包含内容，保留不同版本。
2. 修正旧 PC `AssetBundle.Load` 的小写索引规则，保留对象原始大小写。
   首次原生验证有 762 个名称查找失败，修正后全部通过。
3. 17 张 BC3 压缩误差超阈值的贴图改用 RGBA32，回读像素误差为 0；保留原尺寸。
4. 短 Vorbis 音频依据 Ogg EOS granule 核对样本数，单独记录 FFmpeg 额外尾块，
   完整有效信号仍须通过 SNR 检查；非静音音频最低 SNR 31.325 dB。
5. 原生探针使用二进制传输及最多 4 个并行加载请求，按独立 ID 关联乱序结果。
   12,162 个包均验证名称、类及尺寸 / 声道 / 采样率 / 样本数。

原生引擎为 Unity **4.3.7f1 x86**，SHA-256 为
`0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5`。
7 段音频完成静音播放起止验证（包括不同版本同名片段）；不是所有音频均完整播放。
另 1 个包首次出现引擎加载失败，在新 QA 进程中**同字节**重试通过；初次失败原因未完全确定。
[首次失败及最终状态](native-initial-failures.tsv) 保留全部 763 条记录。

`movie.pam` 文件头为 PAMF0041，在偏移 2048 有 MPEG program stream。
强制 MPEG 解复用后将 MPEG-2 视频流复制到 MPG；源与输出 **3,707 帧的解码摘要及时间戳完全一致**，
见 [movie.json](movie.json)。探索生成的 Theora 文件没有作为最终交付物或成功的 Unity 视频包。

所有验证使用独立 QA 客户端，不调用存档写入接口；诊断资源卸载，Frida 会话结束后脱离。
未修改 hosts、本机 / 局域网配置、正式客户端或游戏原始尺寸。
原生加载验证不等于所有页面、建筑或场景都已经显示验收。

## 清单、产物与复现

本次工作树：`D:/onisoul-worktrees/full-media-port-20261115`。
最终 PC 包清单为 `work/full-media/final-manifest.json`，原始 PNG 清单为
`work/full-media/raw-conversion-manifest.json`，视频为 `work/full-media/final-movie.mpg`。
清单记录每个最终文件的绝对路径；目录中保留的初次转换版本不算最终产物。
**资源二进制留本地，不入 Git；本次未上传服务器，线上覆盖率未重新测量。**

可审查证据：

- [media.tsv](media.tsv)：12,150 个独立 Unity 媒体的源指纹、输出指纹、质量指标及最终原生结果。
- [raw-images.tsv](raw-images.tsv)：12 张原始 PNG 转 PC 包的独立结果。
- [packages.tsv](packages.tsv)、[occurrences.tsv](occurrences.tsv)：全部源容器、类别与重复对象位置。
- [unported-containers.tsv](unported-containers.tsv)：348 个未整包移植容器。
- [summary.json](summary.json)：汇总和来源指纹。

依赖为 `requirements-media.txt`，另需带 libvorbis 的 FFmpeg；原生验证另需 Frida 17。
设置 `$py` 为安装了这些依赖的 Python 3.12+，`$ps3` 为上述 Raw 目录，`$apks` 为三个 APK 路径，
`$audio` / `$texture` 为上一轮清单中的原 PC 模板，`$ffmpeg` 为 FFmpeg 路径后：

```powershell
& $py tools/audit_legacy_media.py scan --ps3-root $ps3 --apk $apks[0] --apk $apks[1] --apk $apks[2] --output work/audit/inventory.json
& $py tools/audit_legacy_media.py port --inventory work/audit/inventory.json --audio-template $audio --texture-template $texture --ffmpeg $ffmpeg --output-root work/audit/converted --output work/audit/manifest.json --workers 8 --allow-silent
& $py tools/audit_legacy_media.py raw --ps3-root $ps3 --apk $apks[0] --apk $apks[1] --apk $apks[2] --texture-template $texture --output-root work/audit/raw --output work/audit/raw-manifest.json
& $py tools/port_ps3_movie.py --source "$ps3/Movies/movie.pam" --output work/audit/movie.mpg --proof work/audit/movie.json --ffmpeg $ffmpeg
```

原生探针使用 `tools/probe_legacy_media.py --pid <独立QA进程> --manifest <清单> --output <新结果文件> --timeout 1800`。
全量测试在当前 Windows 环境运行；外部服务 / Linux 专用集成用例按其条件跳过，详见 PR 验证结果。
