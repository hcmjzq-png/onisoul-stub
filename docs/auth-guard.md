# 鉴权闸门（AUTH_MODE）

给 Stub 的 402 个端点加一层统一的会话校验。此前只有 13 个真实业务 handler 自己
调 `_session_player()` 做校验，其余 389 个端点由 `placeholders.make_handler()` 兜底，
**完全不读 session**，未登录也能拿到 200 + 结构合法的空响应。

## 放行名单与依据

无会话可调的端点共 8 个，逐条都有客户端调用点作依据（反编译树 `WebApiClient.cs`）：

| 端点 | 依据 |
|---|---|
| `common/getRevisions` | `WebApiClient.cs:363` `httpCall("common/getRevisions", null, responder)` —— 全客户端唯一显式传 `null` 参数、连 token 都没有的调用；`TableLoad.cs:45` 在版本表加载阶段就发，早于登录 |
| `debug/devLogin` | `WebApiClient.cs:372`、`:2118`；`BootUp.cs:129`、`SceneResources.cs:125` 启动期自动登录 |
| `debug/debugLogin` | `WebApiClient.cs:444`；`SceneResources.cs:132` |
| `debug/debugLoginCog` | `WebApiClient.cs:462`，账号密码登录，同样在拿 token 之前 |
| `auth/login` | `WebApiClient.cs:405`（入参 `sessionKey`） |
| `auth/gameLogin` | `WebApiClient.cs:417`（入参旧 `token`） |
| `auth/guestLogin` | `WebApiClient.cs:480`（入参 `loginHash`） |
| `auth/refreshToken` | `WebApiClient.cs:383`（换票，入参是旧 token） |

`auth/createPlayer`、`auth/registerName`、`auth/keepAliveContainer` **不在**名单里：
客户端都是 `hashtable.Add("token", token_)` 之后才调用，必须有会话。

## 两种模式

| `AUTH_MODE` | 行为 |
|---|---|
| `strict`（默认） | 无有效会话 + 非放行名单 → 直接拒绝，不执行 handler |
| `observe` | 照旧执行 handler，只按端点累计计数并在首次命中时打一行 stderr，用于排查「客户端到底有哪些接口在没登录时会打」 |

拒绝响应：HTTP 状态仍是 **200**（客户端 `_httpCall` 按 body 判断成败，见
`WebApiClient.cs:299-340`），body 按端点根形态给：

- 普通 endpoint：`{"succeeded": false, "error": "UNAUTHORIZED", "message": "...", "now": ...}`
- 裸映射 endpoint（`response_shapes.BARE_MAP_ENDPOINTS`）：只给 `{"errorReason": "..."}`

带 token 但解析不到会话时 `message` 为 `invalid token`，与「压根没带 token」的
`authentication required` 区分，便于抓包定位。

## 会话库不可用时的取舍

`http_server.do_POST` 里 `sessions.resolve` 抛异常时不再静默降级：

- 打一行 `[stub][auth] 会话解析失败 <api>: <Exception>`；
- strict 模式下这次请求必然被判为未认证（**fail-closed**）；
- 需要「DB 挂了也别掐连接」的可用性优先，把 `AUTH_MODE` 设成 `observe`。

## 调试登录口令

`debug/devLogin`、`debug/debugLogin` 只要求 `username` 就能签发 token，传入已存在的
`account_key` 等于直接接管该玩家。现在支持口令：

```
STUB_DEBUG_LOGIN_KEY=<任意口令>
```

设置后两个端点要求入参带 `key` 且值相等，否则返回 `debug login key mismatch`；
不设置则维持原行为（仅限本机 loopback 使用）。

## 仍未做

- **logout / 会话吊销**：`sessions.revoke` 有实现但没接端点（契约里也没有 logout 端点），
  过期只能靠 12h TTL 和 `resolve` 时的惰性清理。
- **token 轮换**：`auth/refreshToken` 返回同一个 token 只延期（`gameplay.py:496-512`）。
- **传输安全**：客户端 `base_ = "http://127.0.0.1"`（`WebApiClient.cs:50`），token 走
  `params` 表单字段而非 header，无签名、无 TLS；`tools/proxy80.py` 也是明文转发。
- **`auth/login` 的 `sessionKey` 校验**：任意非空串直接签发 `passport:{key}`，未验证
  真实票据。

## 复跑

```
PYTHONPATH=. python3 -m unittest discover -s tests     # 100 tests
python3 tools/contract_check.py                        # 402 / 1116 / 765 / 0
```
