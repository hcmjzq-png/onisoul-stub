-- OniSoul Stub MySQL schema (MySQL 8.x)
-- 与旧 SQLite 版字段对齐：时间一律存 epoch 秒（DOUBLE，time.time()），便于迁移。
-- 字符集 utf8mb4。

CREATE DATABASE IF NOT EXISTS game_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE game_db;

-- 账号 ↔ 玩家
CREATE TABLE IF NOT EXISTS accounts (
  account_key VARCHAR(128) NOT NULL,
  player_id   VARCHAR(64)  NOT NULL,
  created_at  DOUBLE       NOT NULL,
  last_seen  DOUBLE       NOT NULL,
  PRIMARY KEY (account_key),
  UNIQUE KEY uk_account_player (player_id)
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
