# OniSoul Stub

鬼武者魂（Onimusha Soul / OniSoul）PC 版复刻用 Stub 服务端。客户端经 80 端口代理转发到本 Stub；协议与响应字段由客户端 `Assembly-CSharp.dll` 反汇编与抓包整理。

> 当前状态：**分层骨架**。传输 / 协议 / 会话 / 状态 / 注册表已落地并通过协议层单测；具体业务接口与响应字段待 dump / 抓包补齐（见 `docs/architecture.md` 的 TODO）。

## 目录

```
onisoul-stub/
├── app/
│   ├── main.py               # 服务入口
│   ├── config.py            # 环境变量配置
│   ├── db.py                 # MySQL 连接层
│   ├── protocol/            # 信封解析、统一响应、错误码
│   ├── transport/            # HTTP 路由分发
│   ├── sessions/             # 账号 / 会话表
│   ├── state/               # 玩家状态（整行 JSON）
│   └── business/             # 接口注册表与业务规则
├── db/schema.sql            # MySQL 建库建表
├── config/                  # 响应模板（示例）
├── tools/proxy80.py         # 80 → 18080 转发代理
├── deploy/                  # systemd 单元
├── docs/                    # 架构与接口文档
└── tests/                   # 协议层单测
```

## 快速开始

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# MySQL 就绪后初始化表（也可手动导入 db/schema.sql）
export ONI_DB_PASSWORD=你的密码
python -m app.main --init-schema

# 启动
python -m app.main
```

## 测试

```bash
PYTHONPATH=. python -m unittest discover -s tests
```

## 部署

见 `deploy/` 的 systemd 单元与 `docs/architecture.md`。Stub 绑定 `127.0.0.1:18080`，对外由 `tools/proxy80.py` 在 80 端口转发。

## 协作

分支、PR 审批、提交规范与字段来源纪律见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
