"""玩家状态存取。

存储模型：players 表每行一个 player_id，整份嵌套状态序列化为 state_json。
业务层拿到的仍是 dict；持久层只负责整行读 / 整行写，不把状态拆成关系表。

TODO(待从客户端 bundle 核对)：初始状态业务字段目前只给最小占位；bundle 未核对前
不编造键名与初始数值。
"""
from __future__ import annotations

import json
import time
from typing import Any

from app import db

DEFAULT_PLAYER_ID = "1"


class StateConflictError(RuntimeError):
    """The caller attempted to save a stale player snapshot."""


def _default_state(player_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "_revision": 0,
        "entity": {
            "playerId": str(player_id or DEFAULT_PLAYER_ID),
            "created": False,
            "username": "",
            "country": "",
            "level": 1,
        },
        # TODO: 初始业务字段（行动点、资源、武将、建筑、任务、编成等）待从客户端
        #       bundle 核对后补齐；未核对前不加键、不写初始数值。
    }


def load(player_id: str = DEFAULT_PLAYER_ID) -> dict[str, Any]:
    """Only absent players receive defaults; corrupt saves must never be overwritten."""
    pid = str(player_id or DEFAULT_PLAYER_ID)
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT state_json FROM players WHERE player_id = %s", (pid,)
            )
            row = cur.fetchone()
    if not row:
        return _default_state(pid)
    try:
        data = json.loads(row["state_json"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid persisted player state") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entity", {}), dict):
        raise ValueError("invalid persisted player state")
    data.setdefault("entity", {})["playerId"] = pid
    try:
        data["_revision"] = int(data.get("_revision") or 0)
    except (TypeError, ValueError):
        data["_revision"] = 0
    return data


def save(state: dict[str, Any], player_id: str = DEFAULT_PLAYER_ID) -> None:
    """Save a player snapshot using optimistic revision checking."""
    pid = str(player_id or DEFAULT_PLAYER_ID)
    now = time.time()
    try:
        expected_revision = int(state.get("_revision") or 0)
    except (TypeError, ValueError):
        expected_revision = 0
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT state_json FROM players WHERE player_id = %s FOR UPDATE",
                (pid,),
            )
            row = cur.fetchone()
            current_revision = 0
            if row:
                raw = row["state_json"]
                current = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(current, dict):
                    try:
                        current_revision = int(current.get("_revision") or 0)
                    except (TypeError, ValueError):
                        current_revision = 0
            if row and current_revision != expected_revision:
                raise StateConflictError(
                    f"player {pid} revision changed: "
                    f"expected {expected_revision}, found {current_revision}"
                )

            next_revision = expected_revision + 1
            payload = json.dumps({**state, "_revision": next_revision}, ensure_ascii=False)
            if row:
                cur.execute(
                    "UPDATE players SET state_json = %s, updated_at = %s "
                    "WHERE player_id = %s",
                    (payload, now, pid),
                )
            else:
                cur.execute(
                    "INSERT INTO players (player_id, state_json, updated_at) "
                    "VALUES (%s, %s, %s)",
                    (pid, payload, now),
                )
    # connection() 正常退出后事务才已提交；任何失败都保留调用方的旧版本号。
    state["_revision"] = next_revision
