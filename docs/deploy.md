# 部署指南

> 本页的“首次部署”是环境搭建步骤，包含账号密码和环境文件写入。
> 已有服务器更新按对应 PR 的迁移、资源发布和回退计划执行，不重复初始化。
> 当前功能与最新验收记录从 [文档导航](README.md) 进入；代码、SQL、资源和本机助手分别发布。

目标服务器：Ubuntu 26.04 LTS，Python 3.14，MySQL 8.4（仅监听回环）。
拓扑：客户端 ──▶ `proxy80.py` :80 ──▶ stub `app.main` :18080 ──▶ MySQL `game_db`。

## 目录与凭据

```
/opt/onisoul/            # 代码（app/ db/ tools/ deploy/ docs/ tests/）
/opt/onisoul/data/       # 运行数据（不入库）
/opt/onisoul/logs/       # stub-systemd.log + capture-YYYYMMDD.jsonl
/etc/onisoul/stub.env    # 环境变量（含 DB 密码），属 root:root，权限 600
```

- systemd 的系统管理器读取 EnvironmentFile，再以 `ubuntu` 启动进程；环境文件无需开放给 ubuntu。
- 数据库密码只写 `stub.env`，不进代码仓库；`.env`、`*.env` 已在 `.gitignore`。

## 首次部署

### 1. 传代码

把仓库代码放到 `/opt/onisoul/`（git clone 或解压 tar 包均可），目录属主 `ubuntu:ubuntu`。

### 2. 安装依赖

```bash
sudo python3 -m pip install --break-system-packages 'pymysql>=1.1.0'
python3 -c "import pymysql; print(pymysql.__version__)"
```

### 3. 数据库

MySQL 已存在库 `game_db` 与账号 `game_app@127.0.0.1`、`game_app@localhost`。

重置账号密码（密码不回显），并导入 schema：

```bash
PW=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 28)
sudo mysql <<SQL
ALTER USER 'game_app'@'127.0.0.1' IDENTIFIED BY '${PW}';
ALTER USER 'game_app'@'localhost'    IDENTIFIED BY '${PW}';
SQL
sudo mysql --database=game_db < db/schema.sql
```

`db/schema.sql` 只包含表定义，手动导入时必须选定已有目标库。使用自定义库名时，
导入目标与 `ONI_DB_NAME` 保持一致。也可由有建库/建表权限的账号运行
`python -m app.main --init-schema`：它先连接 MySQL 服务，按 `ONI_DB_NAME` 建库，
再导入表定义并启动 Stub；新库不存在时也能初始化。MySQL DDL 会隐式提交，
失败后可重跑 `IF NOT EXISTS` 语句，但不能依赖事务回滚已执行的 DDL。

### 4. 环境变量

```bash
sudo install -o root -g root -m 750 -d /etc/onisoul
sudo tee /etc/onisoul/stub.env >/dev/null <<ENV
ONI_DB_HOST=127.0.0.1
ONI_DB_PORT=3306
ONI_DB_NAME=game_db
ONI_DB_USER=game_app
ONI_DB_PASSWORD=${PW}
STUB_HOST=127.0.0.1
STUB_PORT=18080
AUTH_MODE=strict
STUB_DEBUG_LOGIN_KEY=
ENV
sudo chmod 600 /etc/onisoul/stub.env
```

### 5. systemd 单元

```bash
sudo cp deploy/onisoul-stub.service deploy/onisoul-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now onisoul-stub.service
sudo systemctl enable --now onisoul-proxy.service
```

### 6. 冒烟

```bash
# 直连 stub（回环）
curl -s http://127.0.0.1:18080/client/status
# 经代理（80）
curl -s http://127.0.0.1/client/status
# 公网
curl -s http://<服务器公网IP>/client/status
```

期望返回：`{"succeeded": true, "now": ..., "service": "onisoul-stub", "status": "up"}`。

未知接口经代理应返回 404 信封：

```bash
curl -s -X POST http://127.0.0.1/api/nonexistent -d 'params=%7B%7D'
# {"succeeded": false, "error": "NOT_FOUND", "message": "no stub response: nonexistent", ...}
```

## 运维

```bash
sudo systemctl status  onisoul-stub onisoul-proxy
sudo systemctl restart onisoul-stub onisoul-proxy

journalctl -u onisoul-stub  -n 50 --no-pager
journalctl -u onisoul-proxy -n 50 --no-pager
```

- 代理调试报文：`/opt/onisoul/logs/capture-YYYYMMDD.jsonl`。
- 会话 / 玩家表：`accounts`、`sessions`、`players`（见 `db/schema.sql`）。

## 回滚

1. `sudo systemctl stop onisoul-proxy onisoul-stub`
2. 恢复上一版代码到 `/opt/onisoul/`（或 `git checkout <上一提交>`）
3. `sudo systemctl start onisoul-stub onisoul-proxy`
4. schema 向后兼容时无需回滚表结构；否则按 `db/schema.sql` 对应版本处理。

## 安全边界

- stub 只绑 `127.0.0.1:18080`，公网仅暴露代理 80。
- MySQL 只监听 `127.0.0.1:3306`，不对外开放。
- 新增配置（密码、主机）一律走环境变量，不硬编码进代码。
