"""幸运用户展示队列（show_off）。

客户端主城周期轮询 ``common/periodicInquiry``，从回包根表的 ``show_off`` 取「幸运用户」
广播条，交给 ``ShowOffDataHandler`` 排队，由 ``ShowOffMsg`` 浮层飘过。

协议形状由客户端 IL 反汇编确定（``ShowOffDataParser.ParseSingleData`` /
``ShowOffManager.PeriodicChecking``，见 docs/repro-launcher-login.md 第十二节）：

    show_off 必须是**对象（map）**，不是数组；键是序号字符串，值是条目对象；
    条目键是 snake_case 的三个字段：username / character_id / skill_id。

    // PeriodicChecking
    if (!p_hash.ContainsKey("show_off"))  → warning「There's no "show_off" field in return payload」
    var table = (Hashtable)p_hash["show_off"];      // 数组在这里 isinst 失败 → null
    if (table == null)                    → warning「There's no data in "show_off" field」
    foreach (DictionaryEntry e in table) { ParseSingleData((Hashtable)e.Value) → AddToQueue }

    // ParseSingleData：按 key 走 switch 表（编译器 <switch$map39>）
    "username" → UserName, "character_id" → CharacterId, "skill_id" → SkillId

所以数组和非空都解决不了问题：形状必须是 map。客户端对「没人抽到」没有合法表达，
因此这里永远至少给一条。

取值顺序：待播（FIFO）→ 最近已播（内容不变，客户端重复收也只是同一个条目）→ 内置占位。
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Any

from app import paths

MAX_PENDING = 32

DEFAULT_USER_NAME = "onn"
DEFAULT_CHARACTER_ID = "chara1_00726_01"
DEFAULT_SKILL_ID = "skill1_01002_01"

_LOCK = threading.Lock()
_pending: list[dict[str, Any]] = []
_last_delivered: dict[str, Any] | None = None


def bundle_exists(character_id: str) -> bool:
    """武将包是否已在服务端：bundle 文件名 = md5(UTF-16LE(characterId))。"""
    digest = hashlib.md5(character_id.encode("utf-16-le")).hexdigest()
    return os.path.isfile(os.path.join(paths.PC_BUNDLE_DIR, "chara", digest + ".unity3d"))


def make_entry(user_name: str, character_id: str, skill_id: str) -> dict[str, Any]:
    """一条展示条目。键名用客户端 switch 表里的 snake_case，多一个少一个都不行。"""
    return {
        "username": user_name,
        "character_id": character_id,
        "skill_id": skill_id,
    }


def default_entry() -> dict[str, Any]:
    return make_entry(DEFAULT_USER_NAME, DEFAULT_CHARACTER_ID, DEFAULT_SKILL_ID)


def push(user_name: str, character_id: str, skill_id: str) -> dict[str, Any]:
    """入队一条待播事件；武将缺包时拒绝（否则浮层加载武将图会再报错）。"""
    if not user_name or not character_id or not skill_id:
        raise ValueError("show_off 条目字段不能为空")
    if not bundle_exists(character_id):
        raise ValueError(f"武将包缺失，无法上广播条: {character_id}")
    entry = make_entry(user_name, character_id, skill_id)
    with _LOCK:
        if len(_pending) >= MAX_PENDING:
            _pending.pop(0)
        _pending.append(entry)
    return dict(entry)


def next_entry() -> dict[str, Any]:
    """取本轮要下发的那一条：待播 → 最近已播 → 内置占位。"""
    global _last_delivered
    with _LOCK:
        if _pending:
            entry = _pending.pop(0)
            _last_delivered = entry
            return dict(entry)
        if _last_delivered is not None:
            return dict(_last_delivered)
        return default_entry()


def next_payload() -> dict[str, Any]:
    """包装成客户端要的 map 形状：{"0": 条目}，绝不返回空 map 或数组。"""
    return {"0": next_entry()}


def pending_count() -> int:
    with _LOCK:
        return len(_pending)


def reset() -> None:
    global _last_delivered
    with _LOCK:
        _pending.clear()
        _last_delivered = None
