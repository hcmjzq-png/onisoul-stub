"""登录会话：token ↔ account_key ↔ player_id。

表结构见 db/schema.sql 的 accounts / sessions。
时间一律 epoch 秒；会话 TTL 见 SESSION_TTL。
"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from app import db

DEFAULT_PLAYER_ID = "1"
DEFAULT_ACCOUNT_KEY = "default"
DEFAULT_TOKEN = "stub-token-0001"
SESSION_TTL = 12 * 60 * 60


def _account_key(value: str) -> str:
    key = " ".join(str(value or "").strip().split())
    return key or DEFAULT_ACCOUNT_KEY


def _player_id(account_key: str) -> str:
    if account_key.casefold() in {DEFAULT_ACCOUNT_KEY, "player1", "pyddev1"}:
        return DEFAULT_PLAYER_ID
    digest = hashlib.sha1(account_key.casefold().encode("utf-8")).hexdigest()[:16]
    return f"p_{digest}"


def _ensure_account(con, account_key: str) -> str:
    now = time.time()
    player_id = _player_id(account_key)
    con.execute(
        """
        INSERT INTO accounts (account_key, player_id, created_at, last_seen)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE last_seen = VALUES(last_seen)
        """,
        (account_key, player_id, now, now),
    )
    return player_id


def issue(account_key: str, token: str | None = None) -> dict[str, Any]:
    """创建会话；传入已有 token 则刷新该 token 对应账号。"""
    key = _account_key(account_key)
    now = time.time()
    token = str(token or secrets.token_urlsafe(24))
    with db.connection() as con:
        with con.cursor() as cur:
            player_id = _ensure_account(cur, key)
            cur.execute(
                """
                INSERT INTO sessions (token, account_key, player_id, created_at,
                                      last_seen, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    account_key = VALUES(account_key),
                    player_id   = VALUES(player_id),
                    last_seen   = VALUES(last_seen),
                    expires_at  = VALUES(expires_at)
                """,
                (token, key, player_id, now, now, now + SESSION_TTL),
            )
    return {
        "token": token,
        "playerId": player_id,
        "accountKey": key,
        "expiresAt": now + SESSION_TTL,
    }


def resolve(token: str | None, *, touch: bool = True) -> dict[str, Any] | None:
    """按 token 解析会话；过期返回 None。touch=True 时刷新 last_seen 与过期时间。"""
    token = str(token or "").strip()
    if not token:
        return None
    now = time.time()
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
            cur.execute(
                """
                SELECT token, account_key, player_id, created_at, last_seen, expires_at
                  FROM sessions
                 WHERE token = %s
                """,
                (token,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if touch:
                cur.execute(
                    "UPDATE sessions SET last_seen=%s, expires_at=%s WHERE token=%s",
                    (now, now + SESSION_TTL, token),
                )
                cur.execute(
                    "UPDATE accounts SET last_seen=%s WHERE account_key=%s",
                    (now, row["account_key"]),
                )
    return {
        "token": row["token"],
        "accountKey": row["account_key"],
        "playerId": row["player_id"],
        "createdAt": row["created_at"],
        "lastSeen": row["last_seen"],
        "expiresAt": row["expires_at"],
    }


def revoke(token: str) -> bool:
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (str(token or ""),))
            return cur.rowcount > 0


def list_sessions() -> list[dict[str, Any]]:
    now = time.time()
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (now,))
            cur.execute(
                """
                SELECT token, account_key, player_id, created_at, last_seen, expires_at
                  FROM sessions
                 ORDER BY last_seen DESC
                """
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]
