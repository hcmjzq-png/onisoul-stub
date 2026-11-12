"""玩家状态存取。

存储模型：players 表每行一个 player_id，整份嵌套状态序列化为 state_json。
业务层拿到的仍是 dict；持久层只负责整行读 / 整行写，不把状态拆成关系表。

TODO(待客户端 dump / 抓包补齐)：初始状态的业务字段（行动点、资源、武将、
建筑、任务进度、编成等）目前只给最小占位，不得在未核对官方数据前编造初始数值。
"""
from __future__ import annotations

import json
import time
from typing import Any

from app import db

DEFAULT_PLAYER_ID = "1"


def _default_state(player_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "entity": {
            "playerId": str(player_id or DEFAULT_PLAYER_ID),
            "created": False,
            "username": "",
            "country": "",
            "level": 1,
        },
        # TODO: 按官方表补齐 actionPoints / resources / counters / buildings /
        #       occupiedGrids / produce / items / drafts / missions / characters / decks 等键。
    }


def load(player_id: str = DEFAULT_PLAYER_ID) -> dict[str, Any]:
    """读玩家状态；无存档返回默认占位。JSON 损坏时同样退回默认，不带崩服务。"""
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
    except (ValueError, TypeError):
        return _default_state(pid)
    if not isinstance(data, dict):
        return _default_state(pid)
    data.setdefault("entity", {})["playerId"] = pid
    return data


def save(state: dict[str, Any], player_id: str = DEFAULT_PLAYER_ID) -> None:
    """整行 upsert。"""
    pid = str(player_id or DEFAULT_PLAYER_ID)
    now = time.time()
    payload = json.dumps(state, ensure_ascii=False)
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                INSERT INTO players (player_id, state_json, updated_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    state_json = VALUES(state_json),
                    updated_at = VALUES(updated_at)
                """,
                (pid, payload, now),
            )
