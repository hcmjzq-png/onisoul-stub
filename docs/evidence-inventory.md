# PC 客户端素材证据记录

- 盘点时间：2026-11-13
- 唯一可信来源：`OniSoul_Setup_20140712.exe`（用户提供的 PC 客户端安装包）
- 方式：只读解包（innoextract 1.9 / UnityPy 1.25.4），未改动客户端文件。

> 本文件只记录从上述安装包直接实测得到的事实。响应字段来源纪律见 `CONTRIBUTING.md`。

## 1. 客户端安装包实测

### 1.1 文件与壳结构

- 文件：`OniSoul_Setup_20140712.exe`，653,677,906 字节，MD5 `EB3FAE6F7C785736C0211278FCC8DA29`。
- 安装器：Inno Setup 5.2.0。解包后判定为 **Unity WebPlayer 网页端封装壳**：Qt4（QtCore4 / QtGui4 / QtNetwork4 / QtWebKit4）+ WebKitBrowser + UnityWebPlayer + Mono 运行时（Alpha3.x.x / Stable3.x.x 双版本）。
- 包内**无独立业务 PE 程序集**；本地 dll 全为框架 / 运行时（Qt、WebKit、ICU、Mono mscorlib/System、UnityEngine、CrossDomainPolicyParser）。业务 C# 元数据以 MonoScript 形式存在于主 bundle `app.unity3d`，IL 不随安装包以独立 PE 分发。
- `app\data.bin`（503 MiB）：本轮未纳入。

### 1.2 渠道与入口配置（包内原始文件）

| 文件 | 字段 | 值 |
|---|---|---|
| `app\config.ini`（正式） | FinalUrl | `http://game-onisoul.86joy.com/client/app.html` |
| `app\config.ini`（正式） | StartUrl | `http://passport.86joy.com/index.php/gwz/client/login/` |
| `app\Cantainer\config.ini`（测试容器） | FinalUrl | `http://114.141.133.203/client/app.html` |
| `app\Cantainer\config.ini`（测试容器） | StartUrl | `http://test12242013.86joy.com/index.php/gwz/client/login/` |

- cache 159 个 WebPlayer 缓存条目（41.0 MiB），下载主机：`client-onisoul.86joy.com` 129、`game-onisoul.86joy.com` 18、`passport.86joy.com` 9、`static.86joy.com` 2、Unity 修订检查 1。
- 资源路径前缀 `/client/pc/jp/assets/<bgm|building|cch|chara|item|mission|pbg|pbm|product|questBanner|scene|scr|se|vse>/<md5>.unity3d?r=306620`；主 bundle `http://game-onisoul.86joy.com/client/app.unity3d?revision=30662007`。
- 时间戳：app.html URL `now=1405175929` = 2014-07-12 22:38:49 +08（与安装包名 `20140712` 吻合）；WebPlayer 缓存 `__info` `1416209126` = 2014-11-17 15:25:26（缓存写入时间，晚于打包日）。
- 运行时版本（WebPlayer 播放器 info.plist，非游戏工程版本）：loader 4.3.5f1；mono / player Alpha 4.3.6f1、Stable 4.3.7f1。

### 1.3 主 bundle 指纹

- 2383 对象、1958 MonoScript；程序集分布：`Assembly-CSharp.dll` 1869、`Assembly-CSharp-firstpass.dll` 73、`Assembly-UnityScript.dll` 12、`PlayMaker.dll` 3、`bgmusic.dll` 1。

## 2. 采信边界

- 除本安装包直接解出的内容外，其他目录与来源的 PE、bundle、JSON、日志、数据库、脚本、截图等素材一律不采信、不迁移、不入仓。
- 接口路径、参数字段、响应结构与初始数值只以客户端 bundle 实测为准；bundle 未核对前标注「待验证」，不写成事实。

## 3. 硬限制

- 未发现官方服务器原始抓包（har / pcap）；响应结构只能从客户端 bundle 反推，真实返回值、服务端校验与结算规则缺少证据。
- 接口字段、初始数值未从客户端原始 bundle 核对前不写死；推测项显式标「待验证」。
- 游戏自身版本号（1.00.x）未在包内直读；`revision=30662007` 是资源修订号，非客户端版本号。
