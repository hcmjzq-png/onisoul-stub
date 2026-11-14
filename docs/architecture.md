# 架构说明

## 运行拓扑

```
客户端 ──HTTP:80──▶ tools/proxy80.py ──▶ app.main (stub) :18080 ──▶ MySQL game_db
                          │                        │
                          └─ 代理调试日志 logs/      └─ PC Web / bundle / cache / tables
```

- stub 只监听 `127.0.0.1:18080`，不直接公网可达；对外仅 80 端口代理。
- MySQL 仅监听 `127.0.0.1:3306`；账号 `game_app`，库 `game_db`。

## 分层（app/）

| 层 | 模块 | 职责 |
|---|---|---|
| transport | `transport/http_server.py` | HTTP 路由、请求体读取、会话解析、响应写出 |
| transport | `transport/static.py` | PC Web、AssetBundle、缓存包与 crossdomain 静态路由 |
| protocol | `protocol/envelope.py` | 参数解析（JSON body / 表单 `params`）、统一响应、错误码 |
| sessions | `sessions/sessions.py` | token ↔ account ↔ player；过期清理；`accounts` / `sessions` 表 |
| state | `state/player.py` | 玩家状态整行 JSON 读写；`players` 表 |
| business | `business/registry.py` | api 路径 → handler 注册表；业务规则在此逐个实现 |
| business | `business/response_shapes.py` | 区分普通 envelope 与客户端要求的裸映射响应 |
| business | `business/gameplay.py` | 登录、玩家、主城、建造与新手任务 1～4 |
| business | `business/mission_chain.py` | 按 `politicMission.json` 计算任务状态与解锁位 |
| tables | `tables.py` | 按 108 张表清单加载 JSON，校验 root key 并热重载 |
| 装配 | `main.py` | 读配置、建注册表、起 HTTP 服务；可选 `--init-schema` 建表 |

## 数据流（POST /api/<api>）

1. `http_server` 读 body，`envelope.parse_params` 解析参数字典。
2. 取 `token`，`sessions.resolve` 校验会话（过期返回 None）。
3. `Registry.dispatch(api, params, session)` 找 handler；未知接口 404，未实现 501，异常 500。
4. handler 返回最终响应 dict；普通接口经 `response_shapes.success` 注入
   `succeeded` / `now`，裸映射接口不注入。

生产注册表先登记真实玩法 handler，再用契约占位补齐全量 402 端点。
登录与玩家状态依据账号对应的 `players.state_json`，不使用全局新号/老号开关。

## 静态请求

- `/client/app.html`、`/client/UnityObject.js` 等映射到 `ONI_PC_WEB_DIR`。
- `/client/pc/jp/assets|assets2/...` 优先查 `ONI_PC_BUNDLE_DIR`，再查
  `ONI_PC_CACHE_DIR`；支持多级路径、根级 bundle 与 `<category>__<name>` 缓存命名。
- `/crossdomain.xml` 没有本地覆盖文件时返回内建 Unity Web Player 策略。
- `/`、`/app.html` 映射到 PC Web 的 `client/app.html`；GET/HEAD 均支持
  `Last-Modified`、`If-Modified-Since` 与单段 `Range`。
- 所有路径都解析后校验仍在配置根目录内，目录穿越返回 400。

## 持久层模型

- `accounts(account_key PK, player_id UNIQUE, created_at, last_seen)`
- `sessions(token PK, account_key, player_id, created_at, last_seen, expires_at)`
- `players(player_id PK, state_json JSON, updated_at)`

玩家状态是嵌套 dict，按 `player_id` 整行序列化为 JSON 存储；业务层仍按 dict 操作，
持久层不拆关系表。时间字段统一 epoch 秒（DOUBLE）。状态 JSON 带 `_revision`，
`save()` 使用行锁和版本比较拒绝陈旧快照。
调用方的 `_revision` 仅在提交成功后更新。序列化、SQL 写入或提交抛异常时保留
原版本号，避免一次失败保存让下一次重试误报版本冲突。若提交结果因连接中断
而不确定，需重新加载数据库状态后判断，不能把此保证理解为业务操作可以盲目重放。

## 未决 / TODO

- 响应二进制编码（msgpack / igbinary）尚未实现，当前仅 JSON。
- 客户端包内无法取得的配置表仍需外部证据：`combo.json`、
  `strategy_battlefield.json`。
- 业务接口字段需对照客户端 bundle 实测补齐；见任务 #7。
- 已装 Redis 但 Stub 未使用；是否引入缓存会话/快照暂未决定。
