# 部署指南

目标服务器：Ubuntu 26.04 LTS，Python 3.14，MySQL 8.4（仅监听回环）。
拓扑：客户端 ──▶ `proxy80.py` :80 ──▶ stub `app.main` :18080 ──▶ MySQL `game_db`。

## 目录与凭据

```
/opt/onisoul/            # 代码（app/ db/ tools/ deploy/ docs/ config/ tests/）
/opt/onisoul/data/       # 运行数据（不入库）
/opt/onisoul/logs/       # stub-systemd.log + capture-YYYYMMDD.jsonl
/etc/onisoul/stub.env    # 环境变量（含 DB 密码），属 root:ubuntu，权限 640
```

- stub 服务以 `User=ubuntu` 运行，因此 `stub.env` 需 ubuntu 可读（`root:ubuntu 640`）。
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
sudo mysql < db/schema.sql
```

### 4. 环境变量

```bash
sudo install -o root -g ubuntu -m 640 -d /etc/onisoul
sudo tee /etc/onisoul/stub.env >/dev/null <<ENV
ONI_DB_HOST=127.0.0.1
ONI_DB_PORT=3306
ONI_DB_NAME=game_db
ONI_DB_USER=game_app
ONI_DB_PASSWORD=${PW}
STUB_HOST=127.0.0.1
STUB_PORT=18080
ENV
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
# {"succeeded": false, "error": "NOT_FOUND", "message": "未知接口: nonexistent", ...}
```

## 运维

```bash
sudo systemctl status  onisoul-stub onisoul-proxy
sudo systemctl restart onisoul-stub onisoul-proxy

journalctl -u onisoul-stub  -n 50 --no-pager
journalctl -u onisoul-proxy -n 50 --no-pager
```

- 抓包报文：`/opt/onisoul/logs/capture-YYYYMMDD.jsonl`。
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
