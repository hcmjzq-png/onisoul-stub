# 架构说明

## 运行拓扑

```
客户端 ──HTTP:80──▶ tools/proxy80.py ──▶ app.main (stub) :18080 ──▶ MySQL game_db
                          │                        │
                          └─ 抓包日志 logs/         └─ 静态资源 assets/（映射待接入）
```

- stub 只监听 `127.0.0.1:18080`，不直接公网可达；对外仅 80 端口代理。
- MySQL 仅监听 `127.0.0.1:3306`；账号 `game_app`，库 `game_db`。

## 分层（app/）

| 层 | 模块 | 职责 |
|---|---|---|
| transport | `transport/http_server.py` | HTTP 路由、请求体读取、会话解析、响应写出 |
| protocol | `protocol/envelope.py` | 参数解析（JSON body / 表单 `params`）、统一响应、错误码 |
| sessions | `sessions/sessions.py` | token ↔ account ↔ player；过期清理；`accounts` / `sessions` 表 |
| state | `state/player.py` | 玩家状态整行 JSON 读写；`players` 表 |
| business | `business/registry.py` | api 路径 → handler 注册表；业务规则在此逐个实现 |
| 装配 | `main.py` | 读配置、建注册表、起 HTTP 服务；可选 `--init-schema` 建表 |

## 数据流（POST /api/<api>）

1. `http_server` 读 body，`envelope.parse_params` 解析参数字典。
2. 取 `token`，`sessions.resolve` 校验会话（过期返回 None）。
3. `Registry.dispatch(api, params, session)` 找 handler；未知接口 404，未实现 501，异常 500。
4. handler 返回响应 dict，`envelope` 已统一注入 `succeeded` / `now`。

## 持久层模型

- `accounts(account_key PK, player_id UNIQUE, created_at, last_seen)`
- `sessions(token PK, account_key, player_id, created_at, last_seen, expires_at)`
- `players(player_id PK, state_json JSON, updated_at)`

玩家状态是嵌套 dict，按 `player_id` 整行序列化为 JSON 存储；业务层仍按 dict 操作，
持久层不拆关系表。时间字段统一 epoch 秒（DOUBLE）。

## 未决 / TODO

- 响应二进制编码（msgpack / igbinary）尚未实现，当前仅 JSON。
- 静态资源（assets/web、bundles、cache）目录映射未接入。
- 业务接口字段需对照抓包日志与反汇编补齐；见任务 #7。
- 已装 Redis 但 Stub 未使用；是否引入缓存会话/快照暂未决定。
