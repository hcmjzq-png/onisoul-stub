# 鉴权闸门（AUTH_MODE）

正常注册器的 402 个端点经过统一闸门；业务接入数量另由路由快照统计。
当前事实以 `app/auth.py`、`admin_debug_services.py` 和正常注册器为准，
不能从“无需已有会话”推断某个登录或调试端点已经开放。

## 放行名单与依据

PRE_AUTH_APIS 共 7 个，逐条有客户端调用点依据；具体处理器仍核对票据、调试口令等前置条件：

| 端点 | 依据 |
|---|---|
| `common/getRevisions` | `WebApiClient.cs:363` `httpCall("common/getRevisions", null, responder)` —— 全客户端唯一显式传 `null` 参数、连 token 都没有的调用；`TableLoad.cs:45` 在版本表加载阶段就发，早于登录 |
| `debug/devLogin` | `WebApiClient.cs:372`、`:2118`；`BootUp.cs:129`、`SceneResources.cs:125` 启动期自动登录 |
| `debug/debugLogin` | `WebApiClient.cs:444`；`SceneResources.cs:132` |
| `auth/login` | `WebApiClient.cs:405`（入参 `sessionKey`） |
| `auth/gameLogin` | `WebApiClient.cs:417`（入参旧 `token`） |
| `auth/guestLogin` | `WebApiClient.cs:480`（入参 `loginHash`） |
| `auth/refreshToken` | `WebApiClient.cs:383`（换票，入参是旧 token） |

`auth/createPlayer`、`auth/registerName`、`auth/keepAliveContainer` **不在**名单里：
客户端都是 `hashtable.Add("token", token_)` 之后才调用，必须有会话。
`debug/debugLoginCog` 虽有原调用点，但属于 32 个刻意禁用入口，已从 pre-auth 名单排除。
禁用政策先于 session、strict/observe 判断，不能靠会话或请求字段放行。

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
- strict 模式下，非 pre-auth 且没有有效会话的请求直接拒绝；登录处理器仍核对各自前置条件；
- observe 只改变闸门诊断行为，不提供数据库故障回退，也不开放上述 32 个禁用入口。

## 调试登录口令

`debug/devLogin`、`debug/debugLogin` 在显式调试口令通过后按 `username` 签发 token，
因此不作为正式玩家的账号密码验证入口。配置为：

```
STUB_DEBUG_LOGIN_KEY=<任意口令>
```

设置后两个端点要求入参带 `key` 且值相等，否则返回 `debug login key mismatch`；
不设置或为空时，两个调试登录端点均返回 `debug login disabled`；
当前本地和云端正常登录使用网页账号校验，不依赖调试登录。

## 仍未做

- **logout / 会话吊销**：`sessions.revoke` 有实现但没接端点（契约里也没有 logout 端点），
  当前为 12h 滑动 TTL，正常 `resolve(touch=True)` 续期并清理过期记录。
- **token 轮换**：`auth/refreshToken` 保留同一 token，不生成新票据；续期沿会话解析路径完成。
- **传输安全**：原客户端和 HTTP 代理仍使用 HTTP 表单协议。可选 SSH 通道只加密本机到云端段，
  不表示原客户端已具备端到端 TLS 或 API 签名。
- **`auth/login` 的 `sessionKey` 校验**：任意非空串直接签发 `passport:{key}`，未验证
  真实票据。

## 复跑

```
PYTHONPATH=. python3 -m unittest discover -s tests
python3 tools/contract_check.py
```

不在命令旁固定旧测试数。当前契约为 402 端点、1,165 个端点-键记录、822 条带类型、结构问题 0；
完整回归还需要隔离 MySQL 和相应可选依赖，见[口径核对](project-status/documentation-alignment.md)。
