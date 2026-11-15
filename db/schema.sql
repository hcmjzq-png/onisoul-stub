-- OniSoul Stub MySQL schema (MySQL 8.x)
-- 与旧 SQLite 版字段对齐：时间一律存 epoch 秒（DOUBLE，time.time()），便于迁移。
-- 字符集 utf8mb4。仅定义表，不切换数据库。
-- python -m app.main --init-schema 按 ONI_DB_NAME 建库并选择目标库。
-- 手动导入时先建库，再用 mysql --database=<目标库> < db/schema.sql。

-- 账号 ↔ 玩家
CREATE TABLE IF NOT EXISTS accounts (
  account_key VARCHAR(128) NOT NULL,
  player_id   VARCHAR(64)  NOT NULL,
  created_at  DOUBLE       NOT NULL,
  last_seen  DOUBLE       NOT NULL,
  PRIMARY KEY (account_key),
  UNIQUE KEY uk_account_player (player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Private transaction receipts, quotas and snapshot pointers. NULL reserves a key.
CREATE TABLE IF NOT EXISTS shared_records (
  namespace   VARBINARY(64)  NOT NULL,
  record_key  VARBINARY(128) NOT NULL,
  state_json  JSON          NULL,
  revision    BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at  DOUBLE        NOT NULL,
  PRIMARY KEY (namespace, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 登录会话
CREATE TABLE IF NOT EXISTS sessions (
  token       VARCHAR(128) NOT NULL,
  account_key VARCHAR(128) NOT NULL,
  player_id   VARCHAR(64)  NOT NULL,
  created_at  DOUBLE       NOT NULL,
  last_seen   DOUBLE       NOT NULL,
  expires_at  DOUBLE       NOT NULL,
  PRIMARY KEY (token),
  KEY idx_session_account (account_key),
  KEY idx_session_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 玩家状态：整份嵌套状态按 player_id 存为一行 JSON。
-- 业务层仍按 dict 操作，持久层只负责整行序列化/反序列化，避免把状态表拆成多张关系表。
CREATE TABLE IF NOT EXISTS players (
  player_id  VARCHAR(64) NOT NULL,
  state_json JSON       NOT NULL,
  updated_at DOUBLE     NOT NULL,
  PRIMARY KEY (player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
