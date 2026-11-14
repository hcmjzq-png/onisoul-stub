# 本地复现：鬼武者魂.exe → 登录页 → 注册账号 → 开战

本文让人在自己机器上把**启动器到打开游戏页**这一段跑起来。所有页面与脚本都来自客户端自带 WebKit 缓存里的原版字节，不是我凭空写的；下面每个文件都标了它在缓存里的记录名，可以逐字节对回去。

## 一、这一版能复现到哪一步

| 环节 | 状态 |
|---|---|
| 双击 鬼武者魂.exe，容器内出现登录页 | 可以（原版三张图 + 原版 CSS 数值） |
| 登录页六个入口（官网/公告/注册/充值/客服、顶部菜单）在窗口内换页 | 可以 |
| 注册账号 → 原版 `the37.alert` 弹层提示 | 可以（提示文案走缓存里的 `alertPlugin.js`） |
| 开战 → 302 → `/client/app.html` → 原版 app 页 | 可以（页面与脚本都是原件） |
| 真正进入游戏画面 | **不行**。`app.unity3d` 未入库，且容器 Qt WebKit 没有 Unity WebPlayer 插件 |

## 二、文件清单与证据来源

缓存解析方式：WebKit 的 `.d` 是一条完整 HTTP 事务（头 + 响应体）。文本/样式体多为 zlib（`78 9c` 起），图片取 `FFD8…FFD9`（JPEG）或 `89 50 4E 47 … IEND`（PNG）。记录名对应 `cache/data7/<md5首字符>/<记录名>.d`。

### 登录页（服务器下发，路径 `/index.php/gwz/client/login/`）

| 仓库路径 | 大小 | 缓存记录 |
|---|---|---|
| `assets/pc/web/client/login/wrap_bg.jpg` | 64054 | `38o89qw0.d` |
| `assets/pc/web/client/login/spt-index.png` | 118465 | `1jh1nvsg.d` |
| `assets/pc/web/client/login/start.png` | 67121 | `8e3ohvlu.d` |
| `assets/pc/web/client/login/wrap_bg_sub.jpg` | 70000 | **修补件，非原件**（见第五节第 3 条） |
| `assets/pc/web/client/login/js/jquery-1.7.2.min.js` | 94843 | `2qzg5nif.d` |
| `assets/pc/web/client/login/js/jquery.blockUI.js` | 19277 | `3q38dc2n.d` |
| `assets/pc/web/client/login/js/alertPlugin.js` | 2174 | `awnxane5.d` |
| `assets/pc/web/client/login/js/dialog.css` | 4729 | `14cwjsst.d` |

### app 页（`/client/app.html`）

| 仓库路径 | 大小 | 缓存记录 |
|---|---|---|
| `assets/pc/web/client/app.html` | 6502 | `2kwvyad3.d`（zlib，解压后 6541B 原文，减 1 处改动） |
| `assets/pc/web/client/app.css` | 2494 | `2l7v1vpi.d` |
| `assets/pc/web/client/js/jquery-1.7.2.min.js` | 94844 | `qfrkajch.d` |
| `assets/pc/web/client/js/jquery.cookie.js` | 1950 | `39sof5oa.d` |
| `assets/pc/web/client/js/UnityObject.js` | 21469 | `1uahvf53.d` |
| `assets/pc/web/client/js/login.js` | 3229 | `nf7kpngg.d` |
| `assets/pc/web/client/js/app.js` | 7112 | `1ks5jx17.d` |
| `assets/pc/web/client/js/commontool.js` | 6614 | `1ez9vc11.d` |
| `assets/pc/web/client/js/unityProxy.js` | 3244 | `3vrkhdsj.d` |
| `assets/pc/web/client/js/social.js` | 646 | `d9ghgrba.d` |
| `assets/pc/web/client/js/revision.js` | 34 | `3ar1l1in.d`（正文 `var ONI_SOUL_REVISION='30662007';`） |
| `assets/pc/web/client/img/getunity.png` | 5572 | `gyqmwqiu.d` |
| `assets/pc/web/client/img/logo.png` | 31042 | `12dlozfq.d` |
| `assets/pc/web/client/img/progressBar.png` | 2935 | `3dq73m4i.d` |
| `assets/pc/web/client/img/progressFrame.png` | 2939 | `h0u2d57l.d` |
| `assets/pc/web/client/img/bg_body.jpg` | 143538 | `1ddu8kvs.d`（app.html 的 body 背景，2500×800） |

## 三、复现步骤（Windows）

**前提**：Python 3.12+；该客户端为 `Cantainer` 外壳版本；需要管理员权限（占 80 端口）。

1. 取仓库并装依赖（登录链路不碰 MySQL，不配 `ONI_DB_*` 也能起）：

```powershell
git clone git@github.com:hcmjzq-png/onisoul-stub.git
cd onisoul-stub
pip install -r requirements.txt
```

2. 加 hosts（管理员打开 `C:\Windows\System32\drivers\etc\hosts`）：

```
127.0.0.1 passport.86joy.com
127.0.0.1 game-onisoul.86joy.com
127.0.0.1 client-onisoul.86joy.com
```

3. 起 stub（18080，绑回环）：

```powershell
$env:ONI_ROOT = (Get-Location).Path
python -m app.main --host 127.0.0.1 --port 18080
```

4. 起 80 端口转发（管理员，仓库自带脚本）：

```powershell
python tools\proxy80.py --listen 80 --upstream 18080
```

5. 双击 **鬼武者魂.exe**。

`Cantainer\config.ini` 与根目录 `config.ini` 保持默认即可，不要改：
- `StartUrl=http://passport.86joy.com/index.php/gwz/client/login/`
- `FinalUrl=http://game-onisoul.86joy.com/client/app.html`

## 四、预期结果与验收命令

登录页出现 5 个金边菜单 + 中间公告栏 + 用户名/密码 + 圆形「開戰」+ 三个小金按钮，右侧立绘完整。

```powershell
# 登录页
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" "http://passport.86joy.com/index.php/gwz/client/login/"
# 期望 200 7604

# 注册子页
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" "http://passport.86joy.com/index.php/gwz/client/login/?page=register"
# 期望 200 6554

# 注册提交（账号任意，密码 ≥3 位）
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" -d "account=demo&password=pass" "http://passport.86joy.com/index.php/gwz/client/login/?page=register"
# 期望 200 5932，页面自身加载后弹「完成了」

# 开战
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" -d "account=demo&password=pass" "http://passport.86joy.com/index.php/gwz/client/login/"
# 期望 302，Location 含 /client/app.html?token=…&id=…

# app 页
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" "http://game-onisoul.86joy.com/client/app.html"
# 期望 200 6502
```

服务端日志（`logs/stub-systemd.log` 或控制台）会打出：

```
[stub][login] GET ua=Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/534.34 …
[stub][login] 容器视口 inner=680x510 screen=1920x1080
[stub][register] account=demo
[stub][login] account=demo token=… id=… -> http://game-onisoul.86joy.com/client/app.html?token=…
```

## 五、与原版的差异（逐条，别当成还原度）

1. **`app.html` 改了一行**：body 背景 `url(http://static.86joy.com/gameweb/gwz/images/bg_body.jpg)` → `url(img/bg_body.jpg)`。该域名现返回 502，原件已从缓存取出放 `img/`。其余字节未动。
2. **登录页 HTML 本身没有原件**：原站模板已删（现返回 ThinkPHP「模板不存在 [AUCenter/Tpl/Gwz/Default/Client_login.html]」），页面 HTML 也不会进 WebKit 缓存（响应带 `Cache-Control: no-store`）。所以页面结构是按缓存里 `passport` 侧 CSS 数值 + 三张原图重建的。
3. **入口不能用 `<a href>`**：exe 内嵌 `linkClicked(QUrl)` / `QDesktopServices::openUrl`，容器会把链接点击交给系统浏览器；裸 `<a>` 点了没反应。因此入口元素全部改成 `<span>` + `location.href` 跳转（已真机验证在窗口内换页）。
4. **`wrap_bg_sub.jpg` 是修补件**：原 `wrap_bg.jpg` 里 y=83~113 那 31 行把「游戏公告」四个字烘进像素。子页要显示各自标题，只能用镜像填充把那 31 行抹掉，再叠一条自绘的暗底金字标签。接缝处有一道很淡的水平痕迹，那块也没有原始卷轴饰带可用。
5. **注册不落库**：`register_submit` 只校验（账号非空 ≤32、密码 ≥3）并写日志，不写 users 表；登录校验同样不查库，任意账号密码 ≥3 位都能拿到 302。页面底部那行「stub 不落库，注册仅演示流程」就是这事。
6. **开战到不了游戏画面**：`app.unity3d` 未入库（缓存里有 4.0MB，属资源包，按仓库约定不入库），容器也没有 Unity WebPlayer 插件，页面会停在原版自带的「安装 Unity Web Player」缺省提示（`img/getunity.png`），这正是原页面在缺插件时的行为。

## 六、出问题怎么查

| 现象 | 先看什么 |
|---|---|
| 登录页白屏 | `curl` 登录页是否 200/7604；日志有没有 `[stub][login] GET ua=…` |
| 页面出来但样式全乱 | `/client/login/wrap_bg.jpg`、`spt-index.png`、`start.png` 是否 200 |
| 点入口没反应 | 页面里入口是不是被改回 `<a href>` 了（见第五节第 3 条） |
| 开战 404 | `assets/pc/web/client/app.html` 是否落位；`app/paths.py` 的 `ONI_PC_WEB_DIR` 是否指对 |
| 端口占用 | `netstat -ano | findstr ":80"` |

## 七、没做、也不打算在这版做的

- 游戏本体资源（`app.unity3d` 及 `assets/pc/jp/assets/**` 数百个 bundle）、`globalAssets` / `tableAssets`
- 真实账号体系（注册/登录落库、token 校验、`/api/` 闸门）
- 子页版式与原版注册/找回页对照（原件不存在，当前统一用金色面板版式）
