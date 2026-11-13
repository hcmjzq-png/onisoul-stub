# OniSoul Stub

鬼武者魂（Onimusha Soul / OniSoul）PC 版复刻用 Stub 服务端。客户端经 80 端口代理转发到本 Stub；接口与响应字段待从客户端 bundle 实测反推，当前为分层骨架。

> 当前状态：**运行时基础层已接通**。402 个端点契约占位、普通/裸映射响应形态、
> PC 静态资源路由和 108 张配置表加载器已落地；业务语义仍为空，真实 handler
> 逐个覆盖同名注册项即可（见 `docs/analysis/`）。

## 目录

```
onisoul-stub/
├── app/
│   ├── main.py               # 服务入口
│   ├── config.py             # 环境变量配置
│   ├── db.py                 # MySQL 连接层
│   ├── protocol/            # 信封解析、统一响应、错误码
│   ├── transport/           # HTTP 路由分发
│   ├── sessions/            # 账号 / 会话表
│   ├── state/               # 玩家状态（整行 JSON）
│   ├── tables.py            # 按 108 张表清单加载 / 校验 / 热重载
│   └── business/            # 注册表、契约读取、占位响应
│       ├── registry.py      # api 路径 → handler，可批量登记契约占位
│       ├── contract.py      # 直接读 docs/analysis 的 tsv（唯一事实来源）
│       ├── response_shapes.py # 普通 envelope / 裸映射
│       └── placeholders.py  # 按契约类型生成「形状合法、语义为空」的响应
├── db/schema.sql            # MySQL 建库建表
├── config/                  # 响应模板（示例）
├── tools/proxy80.py         # 80 → 18080 转发代理
├── tools/contract_check.py  # 契约一致性检查（端点 / 边 / 批次 / 类型覆盖）
├── tools/import_tables.py   # 只导入清单内的 108 张配置表
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

## 契约层

`app/business/contract.py` **直接解析** `docs/analysis/` 下的三份 tsv，不落中间产物：

| 文件 | 用途 |
|---|---|
| `api_contract.tsv` | 402 个端点：发送方法 / 请求参数 / 响应键与类型 |
| `api_call_graph.tsv` | 388 条端点→端点调用边 |
| `behavior_contract.tsv` | 场景切换 / 键守卫 |

`build_registry()` 会把这 402 个端点全部登记为占位响应：按源码里**取到类型**的键填默认值
（`int→0`、`double→0.0`、`bool→false`、`string→""`、`Hashtable→{}`），没取到类型的键不猜。
这样客户端请求任何已知接口都拿到 200 + 结构合法的 JSON，可以继续走下一批请求，而不是撞 404。
真实实现只要 `registry.register(api, handler)` 覆盖同名项即可。

已验证会被客户端逐项遍历根表的接口必须返回裸映射，不能注入
`succeeded` / `now`；清单与客户端读取点见 `docs/response-shapes.md`。

批次定义（`contract.batches()`，共 108 个）：

- `scene:<name>`：5 个。触发该场景切换的端点 + 它切换后一帧内会连带的端点。
- `fanout:<endpoint>`：103 个。一个有出边的端点 + 它的全部出边，用于验证「一次回包连发多请求」不会 404。

```bash
python3 tools/contract_check.py     # 端点/边/批次/类型覆盖的只读检查
```

## 测试

```bash
PYTHONPATH=. python -m unittest discover -s tests
```

`tests/test_contract_batches.py` 覆盖：402 个端点全部 200、未知路径 404、已声明类型的响应键
存在且 Python 类型一致、388 条边两端都已登记、108 个批次成员全部已知。

静态资源与配置表：

```bash
python tools/import_tables.py --source /path/to/extracted/tables
```

资源目录通过 `ONI_PC_WEB_DIR`、`ONI_PC_BUNDLE_DIR`、`ONI_PC_CACHE_DIR`、
`ONI_TABLE_DIR` 配置，目录内容不入库。当前清单 108 张表中客户端包内实测
只有 105 张，缺 `assetbundle.json`、`combo.json`、`strategy_battlefield.json`；
见 `docs/tables.md`。

## 部署

见 `deploy/` 的 systemd 单元与 `docs/architecture.md`。Stub 绑定 `127.0.0.1:18080`，对外由 `tools/proxy80.py` 在 80 端口转发。

## 协作

分支、PR 审批、提交规范与字段来源纪律见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
