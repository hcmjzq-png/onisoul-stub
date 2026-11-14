# 本地复现：鬼武者魂.exe → 登录页 → 注册账号 → 开战

> 历史排查记录：下文早期“不依赖 MySQL”“注册仅演示”“配置保持默认”等结论
> 已被后续实现取代，不能作为当前部署步骤。当前连接配置和验收边界以
> [审核记录](audit-20261115.md) 与 [部署指南](deploy.md) 为准。

本文让人在自己机器上把**启动器到打开游戏页**这一段跑起来。所有页面与脚本都来自客户端自带 WebKit 缓存里的原版字节，不是我凭空写的；下面每个文件都标了它在缓存里的记录名，可以逐字节对回去。

## 一、这一版能复现到哪一步

| 环节 | 状态 |
|---|---|
| 双击 鬼武者魂.exe，容器内出现登录页 | 可以（原版三张图 + 原版 CSS 数值） |
| 登录页六个入口（官网/公告/注册/充值/客服、顶部菜单）在窗口内换页 | 可以 |
| 注册账号 → 原版 `the37.alert` 弹层提示 | 可以（提示文案走缓存里的 `alertPlugin.js`） |
| 开战 → 302 → `/client/app.html` → 原版 app 页 | 可以（页面与脚本都是原件） |
| 开战之后 Unity 客户端真的启动并登录 | **可以**（实测 `/api/auth/gameLogin` 200，随后 `periodicInquiry`/`getServerTime`/`politic/map/cleanup`/`quest/checkEmergencyQuest` 全 200） |
| 起角色名 → 确认设定 → 建号 | **服务端已通，真机待复验**。原先 `registerName` 500 `MissingTableError`、`createPlayer` 判 `invalid countryId`、随后又报 `state changed concurrently`，三处均为服务端缺表/版本号实现缺陷，已修（见第八节）。服务端直接调用验证：`registerName → succeeded:true`、`createPlayer → succeeded:True`；真机上尚未复验到主城 |

> 2026-11-14 18:04、18:05 两次真机实测的请求序列（`logs/capture-*.jsonl`）：
> `POST /index.php/gwz/client/login/` 302 → `GET /client/app.html` 200 → `GET /client/js/revision.js` 200
> → `POST /api/auth/gameLogin` 200 → `POST /api/common/periodicInquiry` 200 → `POST /api/common/getServerTime` 200
> → `POST /api/politic/map/cleanup` 200 → `POST /api/quest/checkEmergencyQuest` 200 → 起名 `POST /api/auth/registerName` 500 ×10。

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
6. **`app.unity3d` 不需要下发**：容器自带 Unity WebPlayer，客户端也自带 `app.unity3d`，真机从头到尾**没有请求过** `/client/app.unity3d`（capture 日志 0 条）。所以这个 4.0MB 包不入库不影响开战。
7. **起名卡点已定性为服务端缺陷，不是缺数据**：三处调用把「表里有内容」当成前提（`mission_chain.rows()` 缺表未容错、`create_player` 用 `beginning_equipment` 判国家、`_create_player` 重建默认态丢 `_revision`）。客户端只是如实把 `succeeded:false` 显示成「联机中断」。修复见第八节；`assets/pc/tables/` 仍为空，表内容缺失只影响数值与初始武将，不再打断请求。
8. **`/api/` 已通**：以前记录里「`/api/` 请求 0 条」的说法作废；现在 `gameLogin`、`periodicInquiry`、`getServerTime`、`politic/map/cleanup`、`quest/checkEmergencyQuest` 都是真实客户端发来的 200。

## 六、出问题怎么查

| 现象 | 先看什么 |
|---|---|
| 登录页白屏 | `curl` 登录页是否 200/7604；日志有没有 `[stub][login] GET ua=…` |
| 页面出来但样式全乱 | `/client/login/wrap_bg.jpg`、`spt-index.png`、`start.png` 是否 200 |
| 点入口没反应 | 页面里入口是不是被改回 `<a href>` 了（见第五节第 3 条） |
| 开战 404 | `assets/pc/web/client/app.html` 是否落位；`app/paths.py` 的 `ONI_PC_WEB_DIR` 是否指对 |
| 停在「讀取中」 | 看 capture 日志：`/api/auth/gameLogin` 是否 200；`/api/auth/registerName` 是否是 500（若是，先按第八节确认三处容错补丁还在） |
| 弹「联机中断(1)」 | 看 `POST /api/auth/createPlayer` 的 `resp_body`：`errorReason` 是 `invalid countryId` 或 `state changed concurrently; retry`，都属第八节那类缺陷 |
| 端口占用 | `netstat -ano | findstr ":80"` |

## 七、没做、也不打算在这版做的

- 108 张表 JSON 的导入（`assets/pc/tables/`）。缺表不再打断流程（第八节已容错），但初始武将、任务链、建筑等数值会是空的
- 游戏资源 bundle（`assets/pc/jp/assets/**` 数百个 `.unity3d`）；注意 `app.unity3d` 本身**不需要**，客户端自带
- 真实账号体系（登录/注册落库、token 校验）
- 子页版式与原版注册/找回页对照（原件不存在，当前统一用金色面板版式）

## 八、2026-11-14 追加：起名→建号链路上的三处服务端缺陷（已修）

三处是同一类写法：**把「服务端手里有那份客户端表」当成前提**。客户端本身从不向服务端要表（capture 日志 1185 条里 `.json` 仅 15 条，全是外部扫描器探测，游戏表请求 0 条），所以缺表时应当降级，而不是把请求打成失败。

| # | 位置 | 修复前行为 | 修复 |
|---|---|---|---|
| 1 | `app/business/mission_chain.py` 的 `rows()` | 直接 `catalog.load("politicMission")`，缺表抛 `MissingTableError` → `registerName` 500 | 与 `GameplayService._table()` 同策略：`except TableError: return {}` |
| 2 | `app/business/gameplay.py` 的 `create_player()` 国家校验 | `if country not in self._table("beginning_equipment")`，表空则任何 `countryId` 都判非法 → 客户端弹「联机中断(1)」 | 改为表非空时才校验 |
| 3 | `app/business/gameplay.py` 的 `create_player()` 保存 | `_create_player()` 用 `_default_state` 重建，丢 `_revision`；保存时期望 0、库里 1 → `StateConflictError` | 重建前取 `revision`，重建后写回 |

对应的日志原件（`logs/capture-20261114.jsonl`）：

```
19:10:20 POST /api/auth/registerName  500 {"error":"INTERNAL","message":"MissingTableError"} ×10
19:10:32 POST /api/auth/createPlayer  200 {"succeeded": false, "errorReason": "invalid countryId"}
19:13:59 POST /api/auth/createPlayer  200 {"succeeded": false, "errorReason": "state changed concurrently; retry"}
```

服务端直接调用回归（新号 `repro-0003`，先起名再建号）：

```
registerName: True
createPlayer: True
```

说明：本节只验证到「服务端不再拒绝该请求」，真机上从「最终决定」到主城是否走通，尚未复验。

## 九、2026-11-14 追加：账号鉴权改造，以及进主城后的资源卡点

### 9.1 注册落库 + 登录校验（commit `922a7d0`，PR #20）

改造前的行为是「任意账号 + 任意 ≥3 位密码都发 token」，注册页只做格式校验、不落库（页面明写「stub 不落库，注册仅演示流程」）。改造后：

- 新表 `users(account_key varchar(64) PK, password_hash varchar(128), salt varchar(64), created_at double)`，由登录页首次 GET 时惰性 `CREATE TABLE IF NOT EXISTS`，不依赖迁移脚本；
- 密码存 PBKDF2-HMAC-SHA256（12000 轮）+ 每账号 16 字节随机 salt，不存明文；
- 注册重复 → 「该账号已注册，请直接登录或换一个账号」；
- 登录未注册 → 「该账号尚未注册，请先点『注册新账号』」；密码错 → 「密码错误」；校验通过才 `sessions.issue` 发 token 并 302。

服务端 curl 实测（`http://127.0.0.1/index.php/gwz/client/login/`）：

```
1) POST account=authtest1&password=abc123  (?page=register)  → 200 页面含「账号已创建」
2) 同一账号再注册                                            → 200 页面含「该账号已注册」
3) POST account=ghost999&password=abc123                     → 200 页面含「该账号尚未注册」
4) POST account=authtest1&password=wrongpass                 → 200 页面含「密码错误」
5) POST account=authtest1&password=abc123                    → 302 → /client/app.html?token=…
```

库里 `users` 落了一行：`authtest1  aece2d94634b…  1794657595.9`。

### 9.2 「记住账号密码」勾选框（同 commit）

原页面 `#remember` 是个 `<span class="ui-radio checked">` 死图：没有 onclick，也没有任何持久化，点了没反应、下次也不记。现在：

- 点击切换 `ui-radio` / `ui-radio checked`；
- 勾着提交时把 `{a:账号, p:密码}` 写进 cookie `oni_login`（180 天），取消勾选提交则删除；
- 下次加载自动回填并置为选中；
- 用 `document.cookie` 而不是 `localStorage`——容器是 QtWebKit 4.x，localStorage 持久化没有保证。

边界：密码是明文存在客户端本机 cookie 里的，只适合本地 stub；要不要改成「只记账号」另行决定。登录页体积 7604 → 9031 字节，响应头 `Cache-Control: no-store, no-cache, must-revalidate`。

### 9.3 真机链路：建号这次真的成功了

```
20:01:16 POST /api/auth/registerName  200 {"succeeded": true}
20:01:26 POST /api/auth/createPlayer  200 {"succeeded": true, "playerId": "p_dc76e9f0c0006e8f"}
```

库里该玩家（`SELECT player_id, JSON_EXTRACT(state_json,'$.entity.created') …`）：

```
p_dc76e9f0c0006e8f   created=true   username=流音   country=country37   state 1101 字节
```

真机截图上 HUD 已渲染（编成／物语／合战／鬼签、商店／建筑／仓库／每日奖励），说明客户端已经过建号、进了主城骨架。

### 9.4 现行卡点：6 个 `chara/*.unity3d` 404 触发「联机中断(1)」

建号前后那几秒，所有 API 都是 200，唯一的失败请求是角色资源包：

```
20:01:17 404 /client/pc/jp/assets/chara/395a38ee07917a3f1342358cdb6c4fff.unity3d  ×5
20:01:18 404 /client/pc/jp/assets/chara/1450fa13b6e0098ea407efee5de253b2.unity3d  ×5
```

累计请求次数（`capture-20261114.jsonl` 全文 grep）：

```
16  chara/adab798b1a597e970fa1995aa4a9dd11.unity3d
15  chara/759f9e91a56a2aab75b1d64bf101a5ef.unity3d
11  chara/b6c88175b58f489bebf782eef21ace35.unity3d
11  chara/69e30186b8b4e5649be7b31103de7558.unity3d
10  chara/395a38ee07917a3f1342358cdb6c4fff.unity3d
 5  chara/1450fa13b6e0098ea407efee5de253b2.unity3d
```

两边都没有这些文件：

- 服务端：`PC_BUNDLE_DIR=/opt/onisoul/assets/pc/bundles`、`PC_CACHE_DIR=/opt/onisoul/assets/pc/cache` 两个目录 `exists: False`（`assets/pc` 下只有 `web`），`paths.py` 里那 6 条候选路径全部 miss；
- 客户端：`<客户端安装目录>` 按这 6 个哈希名搜索命中 0；`cache` 下只有 `data7`（16 桶 163 条 `.d`）、`prepared`（0 文件）、`WebpageIcons.db`（68608 B），`WebPlayer\Cache\Temp` 0 文件；
- 源站：`client-onisoul.86joy.com` 在服务器上 `getent hosts` 解析失败、`curl` 报 `Could not resolve host`，不可回源。

结论：这 6 个包只能从**跑过原服、缓存里有副本的机器**上取（朋友机器 `<客户端安装目录>\cache\data7` 里按哈希搜），拿到后落盘到 `assets/pc/bundles/chara/<hash>.unity3d`，「联机中断」才会消失。这是素材缺失，不是协议/逻辑错误，与第八节的三处服务端缺陷性质不同。

附带一个已知内容缺口：`createPlayer` 写入的 `characters` 是空的——`_initial_characters` 依赖 `beginning_equipment` + `item01` + `character` 三张表，表空则初始武将 0 个。所以即便资源包到位，主城／编成里的武将列表仍需要最小初始存档来填。

## 十、从客户端缓存还原 PC 资产包（方法进仓，二进制不入仓）

原站 `client-onisoul.86joy.com` 已不可访问（服务器上 `getent hosts` 解析失败、`curl` 报 `Could not resolve host`），所以 PC 版的 `.unity3d` 资产包只能从**跑过原服的机器上的缓存副本**还原。方法固化在 `tools/extract_cached_bundles.py`，二进制本身不进 git。

### 10.1 `.d` 记录格式（QtWebKit 4.x 磁盘缓存）

一条记录就是一笔 HTTP 事务：

```
偏移 0   4 字节  记录长度
偏移 4   4 字节  版本标记（观测值 0x00000007）
偏移 8   4 字节  URL 长度（大端）
偏移 12  N 字节  URL 明文（ASCII）
...              状态行 + 响应头
...              响应体
```

URL 按 MD5 首字符分到 `cache/data7/0` ~ `f` 共 16 个桶，记录文件名是 8 字符短名、与 URL 无关，因此必须逐条读 URL 才知道它是什么资源。

响应体两种形态：明文（包体以 `UnityWeb` 开头，`app.unity3d` 那 4 MB 就是这样，魔数落在记录内偏移 304 附近）或 zlib／gzip 压缩流（解压后才以 `UnityWeb` 开头）。脚本按这个顺序尝试。

### 10.2 本轮实测（2026-11-14，`<local-pc>`）

```
扫描 <客户端安装目录>\cache\data7      164 条记录，43,414,472 B
匹配 /assets/<dir>/<hash>.unity3d  130 条命中（含 6 条重复 URL）
解出文件                          124 个，38,097,726 B
命中方式                          plain 124 / zlib 0 / gzip 0 / 失败 0
包体校验                          chara/1b3772… 前 8 字节 = UnityWeb
```

按目录：

```
bgm 3 / building 4 / cch 2 / chara 15 / item 40 / mission 1 / pbg 27
pbm 1 / product 1 / scene 11 / scr 14 / se 1 / vse 4
```

### 10.3 部署与验证

产物放在服务端 `/opt/onisoul/assets/pc/bundles`，正好命中 `app/transport/paths.py` 里静态层的第 1 条候选路径 `PC_BUNDLE_DIR/<dir>/<hash>.unity3d`。实测（`curl` 打 `127.0.0.1`，带 `?r=306620`）：

```
chara/1b3772fdd4b788f942075d29d2f32423 → 200 116,984 B
scene/7bf2c1d92f87d89a4f646a9cefb8fb62 → 200 2,622,889 B
bgm/5b7ebaae6b9ea0a8e79c014237bb83cd   → 200 1,510,109 B
```

这三条以前都是 404。

### 10.4 复现步骤

```bash
# 1) 在有缓存副本的 Windows 机器上解包（--dry-run 先看统计）
python3 tools/extract_cached_bundles.py --cache-dir "D:/鬼武者魂/cache/data7" --out ./bundles --dry-run
python3 tools/extract_cached_bundles.py --cache-dir "D:/鬼武者魂/cache/data7" --out ./bundles

# 2) 把 bundles/ 下各目录拷到服务端
rsync -r ./bundles/ ubuntu@<server>:/opt/onisoul/assets/pc/bundles/

# 3) 验证
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" \
  "http://127.0.0.1/client/pc/jp/assets/chara/1b3772fdd4b788f942075d29d2f32423.unity3d?r=306620"
```

### 10.5 仍然缺的 6 个 chara 包

```
16 次请求  chara/adab798b1a597e970fa1995aa4a9dd11
15 次请求  chara/759f9e91a56a2aab75b1d64bf101a5ef
11 次请求  chara/b6c88175b58f489bebf782eef21ace35
11 次请求  chara/69e30186b8b4e5649be7b31103de7558
10 次请求  chara/395a38ee07917a3f1342358cdb6c4fff
 5 次请求  chara/1450fa13b6e0098ea407efee5de253b2
```

缓存里现有的 15 个 chara 包与这 6 个哈希**互不相同**（`c42732b9…`、`c07e9888…`、`84fa3ca2…`、`f1fc3313…`、`441147d9…`、`8b3d6b8a…`、`e2fba99c…`、`5fd8a8e6…`、`8151e5be…`、`616bf995…`、`497199bd…`、`1b3772fd…`、`58479003…`、`3e87841f…`、`5a10edfd…`），替补不了——这 6 个一直 404，失败响应不会进缓存。

要补齐只能从另一台跑过原服、缓存里有这些哈希的机器上取，再走同一套脚本。

## 十一、服务端的表从客户端包里抽（同源同版本）

服务端要自己有一套表：客户端表只服务表现层（它自己读，实测 1185 条请求里没有一条是取表的），服务端要用同一批数据做判定与发放。所以两套表必须是**同一份 JSON、同一 root_key、同一客户端版本**，不能各写一份。

抽取方法固化在 `tools/extract_tables_from_bundle.py`，表文件本身不进 git。

### 11.1 表在哪

PC 客户端的 108 张表不是独立文件，而是作为 JSON 文本内嵌在场景包里：`scene/1243ea6aa6…`（缓存记录 `1243ea6aa6…kbeizo6m` 无关，实际是 `data7` 里那一个），解压后 **100,194,188 B**，格式是

```
{"<root_key>": {"<行id>": {...}, ...}, "<另一个表>": {...}, ...}
```

`app.unity3d`（解压 19,463,656 B）里只有 `assetbundle` 这一张表（63 条，全是 `assets/scene/*.unity3d` 场景包清单），其余表都在场景包里。

### 11.2 本轮实测

```
清单条目            112（docs/analysis/table_list.tsv 108 + server_tables.tsv 4）
抽出成功            109 张（18,076,191 B）
另从 app.unity3d   assetbundle.json（63 条，11,506 B）
最终落盘            110 张，18 MB
TableCatalog 校验   110/112 通过，合计 40,160 行
```

按 `app/tables.py` 的强校验逐张加载，失败仅 2 张：

```
combo.json                MissingTableError
strategy_battlefield.json MissingTableError
```

这两张的缺失是**客户端本身没有随包**，不是抽取失败：

- 在 124 个已还原包 + `app.unity3d` 解压体里，`"combo"` 作为表名 0 命中；`app.unity3d` 里只有 `ComboTableAccessor` 类名与字段名 `comboCount`；
- `strategyBattlefield` / `strategy_battlefield` 在 `app.unity3d` 里 0 命中，任何包内也 0 命中。

### 11.3 建号回归（真表）

```
beginning_equipment  48 行，含 country37
country37            questCharacters [item01_0101201]
                     attackCharacters [item01_0936101]
                     defenseCharacters [item01_0936201 0936401 0936601 0936801 0936901]
_create_player()     characters = 7 个，counters.characterCount = 7
  1 -> chara1_01012_01  atk 1250 def 1250 int 1250
  2 -> chara1_09361_01  atk  600 def  350 int  300
  3 -> chara1_09362_01  atk  325 def  325 int  600
resources            历史观测为全 0；2026-11-15 已按原表及用户首登截图修正新角色 gold=5000（不改旧存档）
buildings 0 个，missions 1 条
```

也就是说：表到位后初始武将不再是空表结果，而是 7 个真角色；资源与建筑仍是各自逻辑的现状，不在本次改动范围。

### 11.4 复现

```bash
# 1) 解包场景包（从缓存记录里取，或直接用已还原的 scene/*.unity3d）
python3 tools/extract_tables_from_bundle.py --bundle ./scene/1243ea6aa6.unity3d \
    --out /opt/onisoul/assets/pc/tables

# 2) 校验（需要生产 env，否则连库会 1045）
sudo bash -c 'set -a; . /etc/onisoul/stub.env; set +a;
  export ONI_ROOT=/opt/onisoul ONI_TABLE_DIR=/opt/onisoul/assets/pc/tables;
  cd /opt/onisoul && python3 /tmp/verify_tables.py'

# 3) 只补缺失的表时加 --only-missing，不会覆盖已有文件
```

## 十二、2026-11-14 追加：进主城「联机中断(1)」的真因是 common/periodicInquiry

> 结论已作废，真因见第十三节。

### 12.1 怎么会看到客户端日志

Unity WebPlayer 默认写随机名日志 `log_<hash>.txt`，只有带 `UNITY_KEEP_LOG_FILES=1` 启动才会
固定写 `%TEMP%\UnityWebPlayer\log\log_debug.txt`（常量名与文件名从 `npUnity3D32.dll` 里挖出）。
带该变量启动后，进主城那一轮日志里能直接读到：

```
582:start httpCall: common/periodicInquiry
Theres no data in show_off field

## 十二、2026-11-14 追加：进主城「联机中断(1)」的真因是 common/periodicInquiry

### 12.1 怎么会看到客户端日志

Unity WebPlayer 默认写随机名日志 `log_<hash>.txt`，只有带 `UNITY_KEEP_LOG_FILES=1` 启动才会
固定写 `%TEMP%\UnityWebPlayer\log\log_debug.txt`（常量名与文件名从 `npUnity3D32.dll` 里挖出）。
带该变量启动后，进主城那一轮日志里能直接读到：

```
582:start httpCall: common/periodicInquiry
There's no data in "show_off" field
ERROR: WebAPI api = common/periodicInquiry error = exception error : {"succeeded": true, "now": 1794666426.0, "show_off": []}
```

早一轮（同一日志文件的前一个实例块）报的是另一句：

```
There's no "show_off" field in return payload
ERROR: WebAPI api = common/periodicInquiry error = exception error : {"succeeded": true, "now": 1794665756.0}
```

### 12.2 这个接口是干什么的

`common/periodicInquiry` 是主城「幸运用户」广播条的数据源：有人抽到稀有武将时，服务端把
`{UserName, CharacterId, SkillId}` 放进 show_off 队列，客户端周期轮询取一条，由 `ShowOffMsg`
浮层在主城画面上飘过几秒。证据（均在解压后的 `app_unity3d.bin` 字符串表里）：

| 证据 | 位置 |
|---|---|
| `ShowOffData, UserName:{0}, CharacterId:{1}, SkillId:{2}` | 约 5,640,374 |
| `show_off` / `Get data: ` / `There's no data in "show_off" field` | 约 5,640,574 起 |
| `There's no "show_off" field in return payload` / `Show lucky user: ` / `  time : ` | 约 5,640,686 |
| `PeriodicChecking` / `ShowOffMsg` / `Unable to create "ShowOffMsg", is it in the asset bundle?` / `POLITIC_MSG_SHOWOFF` | 约 5,640,834 |
| 成员名 `ParseSingleData / p_hash / UserName / CharacterId / SkillId / showOffData / ShowLuckyUser / StartShowing / existDuration / moveVelocity / alphaSpeed` | 程序集元数据区 5,294,047 |
| 客户端自带测试数据 `g6msg` / `test2` / `chara1_02065_01` / `skill1_01002_01` | 约 5,640,486 |

### 12.3 客户端对「没有幸运用户」没有合法表达

源码把两种「空」都当异常：字段缺失、数组为空。异常被 `WebApiClient` 捕获后统一弹
「联机中断(1)」，并关掉 plugin window。也就是说：**协议里不存在「这一轮没人抽到、什么都不显示」
这个状态**。占位响应当初只回 `{succeeded, now}`，所以第一轮就炸；改成 `show_off: []` 后炸第二条。

### 12.4 修法：永远至少给一条

`app/business/show_off.py` 提供队列，`app/business/periodic.py` 直接取一条下发：

| 状态 | 下发内容 |
|---|---|
| 有未播事件 | 取最早一条（FIFO），记为「最近已播」 |
| 队列空、播过 | 回最近一条；内容不变，客户端按条目哈希去重，不重复飘 |
| 队列空、从未播过 | 内置占位条目 `onn` + `chara1_00726_01` + `skill1_01002_01` |

两条约束写进实现里：

1. **武将必须在服务端有包**：bundle 名 = `md5(UTF-16LE(characterId))`，`push()` 先校验
   `assets/pc/bundles/chara/<md5>.unity3d` 是否存在，缺包拒绝入队，否则浮层加载武将图会再报一次错。
   实测：客户端自带测试数据里的 `chara1_02065_01` 在服务端 **没有包**（`32251c4f…` MISS），
   所以不能照抄它的测试数据；`chara1_00726_01` 有包（`1b3772fd…`，116,984 B）。
2. **键名双拼**：条目同时给 `userName`/`UserName`、`characterId`/`CharacterId`、`skillId`/`SkillId`。
   客户端按成员名反射映射，多给的键被忽略；这样避免「猜错大小写 → 用户再跑一轮」。
   全站请求键命名惯例是 lowerCamel（`mapName` / `draftId` / `characterId`，见 API 定义表
   约 5,512,000 区段），而该类成员名是 PascalCase，因此两种都发。

真实触发点留了口子：契约表里的 `politic/lottery/lot`（鬼签抽卡，返回 `characters` Hashtable）
命中稀有度时调 `show_off.push()` 即可。本 Stub 目前 **没有抽卡实现**（`app/business/` 里搜
`lottery|getSouls|onikuji` 零命中，`logs/capture-*.jsonl` 里 lottery 调用 0 次），所以现在只能
靠 `push()` 手工喂数据；抽卡实装单独一件，前提是先补武将包覆盖。

### 12.5 验证

```bash
# 单测（含新增 8 条 show_off 回归）
PYTHONPATH=/opt/onisoul python3 -m unittest discover -s tests   # Ran 116 tests OK

# 契约自检
PYTHONPATH=/opt/onisoul python3 tools/contract_check.py         # 402/392/111/0 问题

# 线上回包（用任一有效 token）
curl -s -X POST http://127.0.0.1:18080/api/common/periodicInquiry \
  -H 'Content-Type: application/json' -d '{"token":"<token>"}'
# → {"succeeded": true, "now": ..., "show_off": [{"userName": "onn", ...}]}
```

客户端侧待确认：条目被接受后是否还要求额外字段（例如时间戳）；本报文写入时尚未取得
「非空数组的一次完整主城运行」日志。

### 12.6 修正（同日）：show_off 是 map、键是 snake_case —— 由客户端 IL 反汇编确定

12.3/12.4 里「字段非空就行」和「camel/Pascal 双拼」两条都被实测推翻：回包给了非空数组，
客户端仍报 `There's no data in "show_off" field`。原因是数组和对象不通用，键名也不是驼峰。

取证方法（可复现）：`app.unity3d` 里内嵌了 12 个 .NET 程序集，但 PE 头被裁；不依赖 PE，
直接用元数据根 `BSJB`（偏移 3,778,036 处是 Assembly-CSharp）解析 `#~ / #Strings / #US` 表，
再用 `ldstr` 的 user-string token 反查字符串引用位置，得到：

```
类型 1520 ShowOffDataParser  字段 <>f__switch$map39  方法 .ctor / ParseSingleData
类型 1521 ShowOffData        字段 UserName / CharacterId / SkillId
类型 1522 ShowOffManager     方法 createTestData / ShowOffDataHandler / AddToQueue /
                                   ShowLuckyUser / PeriodicChecking / CreateMsg ...
```

`ParseSingleData` 的 IL（0x00F8C30 起，文件偏移 2,486,xxx）：

```
2485908  newobj   Hashtable::.ctor
2485915  callvirt Hashtable::GetEnumerator
2485940  call     DictionaryEntry::get_Key
2485945  callvirt Object::ToString
2485961  ldsfld   <>f__switch$map39
2485972-2486013  newobj / Add 三次
2485981  ldstr    "username"
2485994  ldstr    "character_id"
2486007  ldstr    "skill_id"
2486081  stfld    field:UserName
2486104  stfld    field:CharacterId
2486127  stfld    field:SkillId
```

`PeriodicChecking` 的 IL（文件偏移 2,486,617 起）：

```
2486617  ldstr    "show_off"
2486622  callvirt Hashtable::ContainsKey      → 假 → LogWarning "There's no "show_off" field in return payload"
2486633  ldstr    "show_off"
2486638  callvirt Hashtable::get_Item
2486643  isinst   Hashtable                   ← 数组在这里得到 null
2486662  callvirt Hashtable::GetEnumerator
2486688  call     DictionaryEntry::get_Value
2486693  isinst   Hashtable                   ← 条目必须是对象
2486698  callvirt ShowOffDataParser::ParseSingleData
2486708  call     ShowOffManager::AddToQueue
```

`ShowOffManager.createTestData` 给出客户端自己的样例，形状与上面完全一致：

```
show_off = new Hashtable();
show_off["0"] = { "username": "test",  "character_id": "chara1_02065_01", "skill_id": "skill1_01002_01" };
show_off["1"] = { "username": "test2", "character_id": "chara1_02065_01", "skill_id": "skill1_01002_01" };
```

结论（照此实现，服务端回包）：

```json
{"succeeded": true, "now": 1794668074.0,
 "show_off": {"0": {"username": "onn", "character_id": "chara1_00726_01", "skill_id": "skill1_01002_01"}}}
```

三种错误形状与客户端反应一一对应：

| 回包 | 客户端 |
|---|---|
| 无 `show_off` 键 | `There's no "show_off" field in return payload` |
| `show_off: []` / `[{...}]`（数组） | `There's no data in "show_off" field`（isinst Hashtable → null） |
| `show_off: {}`（空 map） | 同上，队列空 |
| 条目键 `UserName`/`characterId` | 条目解析后三个字段全空字符串（switch 默认分支跳过） |

## 十三、2026-11-15 追加：真因是 `ChatInfo.setOperationMessage` 读 `gmMessage` 无守卫

第十二节把原因归到 `show_off` 形状，两次实机日志已经否证：`show_off` 为 `{}`、为带条目的 map、
以及额外补 `politicPoint` / `nextTriggerPoliticPoint`，客户端都照样抛——说明异常不在 `show_off`
解析里，而在同一轮推送的另一个订阅者身上。

### 13.1 先修好 RVA → 文件偏移（此前所有偏移都错在这）

`app_unity3d.bin` 不是 PE，而是 UnityWebData 容器：头部是大端 `u32` 的条目数（本文件 25），
随后每条 `[name\0][offset u32 BE][size u32 BE]`，数据区自第 0x258 字节起。

```
Assembly-CSharp.dll  offset=1474648  size=4584448     （1474648..6059096）
PE: .text  va=0x2000  ptr=0x200
=> 文件偏移 = rva + 1466968
```

校验：元数据目录 RVA `0x23439C` 换算得 3,778,036，正好是本文件里 `BSJB` 元数据根的偏移，
所以这个换算是精确的。此前用「按 token 反查方法起点 + 区间顺序遍历」得到的偏移有错位，
把 `politic/edict/raiseMission` 的回调误当成 `periodicInquiry` 的回调——那是上一轮加
`politicPoint` 的由来，也是它被实测否证的原因。

### 13.2 periodicInquiry 的真实调用链

| 环节 | token / 文件偏移 | 做什么 |
| --- | --- | --- |
| `WebApiClient.periodicInquiry` | `0x06001110` / 1,838,464 | 只塞 `token`，挂回调 `<>m__61`，走 `httpCall` |
| `<>m__61` | 3,657,880 | 校验 `token` / `now`（都有 `ContainsKey` 守卫），可选 `left_time`，然后 `responder.Invoke(result)` |
| `PeriodicRounder.refresh` | 2,063,396 | 建 `response` 委托，交 `RpcQueue.predicable` 轮询 |
| `<>m__193` | 3,677,748 | `callCallbacks(result)`，并把 `elapsedTime_` 归零 |
| `PeriodicRounder.callCallbacks` | 2,063,284 | 遍历 `callbacks_`，逐个 `Invoke(result)` |

也就是说：**回包整体会被四个回调各自处理一遍**，任何一个抛异常都会被 `WebApiClient.Send`
的 catch 捕获，打成 `exception error : <回包原文>`。

### 13.3 四个订阅者与各自的键

`PeriodicRounder.regist`（`0x06001B79`）只有四个调用点：

| 回调 | 文件偏移 | 读的键 | 有守卫吗 |
| --- | --- | --- | --- |
| `SessionKeeper.updatePeriodic` | 1,824,708 | `token` / `now` | 有 |
| `ChatInfo.setOperationMessage` | 1,915,936 | **`gmMessage`** | **没有** |
| `ShowOffManager.ShowOffDataHandler` | 2,486,604 | `show_off` | 有（缺失 / 非 map 只 warning，不入队） |
| `SocialInformation.update` | 2,688,804 | `inboxParcel` / `friendOffer` / `unreadMail` | 有 |

`setOperationMessage` 的头几行就是异常点：

```
1915955  ldarg.1
1915960  ldstr    "gmMessage"
1915965  callvirt get_Item
1915970  castclass string        // null 也能过
1915977  ldstr    "\r"
1915987  callvirt Replace         // ← 键不存在时 NullReferenceException
```

键不存在 → `get_Item` 返回 null → `Replace` 抛 NRE。反过来，给空串是安全的：后面
`1916011 ldloc.0; call op_Equality("", s)` 命中就提前 `ret`。

### 13.4 因此最小合法回包

```json
{"succeeded": true, "now": 1794675157.0, "show_off": {}, "gmMessage": ""}
```

- `show_off` 为空 map：合法，循环零次，不打印任何 warning；
- `gmMessage` 为空串：`setOperationMessage` 直接返回；
- `now` 必须是 JSON 小数（客户端 `unbox.any System.Double` 后 `conv.u4`）。

已实现于 `app/business/periodic.py`，并在 `tests/test_periodic_inquiry.py` 里加了两条断言
（`gmMessage` 存在且是字符串、走注册表分发后仍在），本地空资产跑 134 tests OK。

### 13.5 现场自检

```bash
TOKEN=$(sudo mysql -uroot -N -e "SELECT token FROM game_db.sessions ORDER BY created_at DESC LIMIT 1")
curl -s -X POST http://127.0.0.1:18080/api/common/periodicInquiry \
  -H 'Content-Type: application/json' -d "{\"token\":\"$TOKEN\"}"
# {"succeeded": true, "now": ..., "show_off": {}, "gmMessage": ""}
```

客户端那边只要 `log_debug.txt` 里不再出现 `exception error : ...periodicInquiry` 的回包原文，
并且 `periodicInquiry` 之后仍有后续请求，就说明这条链路通了。
