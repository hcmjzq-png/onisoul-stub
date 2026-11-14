"""幸运用户展示队列（show_off）。

客户端主城周期轮询 ``common/periodicInquiry``，从回包根表的 ``show_off`` 取「幸运用户」
广播条，交给 ``ShowOffDataHandler`` 排队，再由 ``ShowOffMsg`` 浮层飘过。

协议形状由客户端 IL 反汇编确定（``ShowOffDataParser.ParseSingleData`` /
``ShowOffManager.PeriodicChecking``，见 docs/repro-launcher-login.md 第十二节）：

    show_off 必须是**对象（map）**，不是数组；键是序号字符串，值是条目对象；
    条目键是 snake_case 的三个字段：username / character_id / skill_id。

    // PeriodicChecking
    if (!p_hash.ContainsKey("show_off"))  → "There's no \"show_off\" field in return payload"
    var table = (Hashtable)p_hash["show_off"];      // 数组在这里 isinst 得 null
    if (table == null)                    → "There's no data in \"show_off\" field"
    foreach (DictionaryEntry e in table) { ParseSingleData((Hashtable)e.Value) → AddToQueue }

    // ParseSingleData：按 key 走 switch 表（编译器 <switch$map39>）
    "username" → UserName, "character_id" → CharacterId, "skill_id" → SkillId

空 map ``{}`` 是合法状态：``isinst`` 通过、``foreach`` 空转、不弹窗，因此「没人抽卡
就不广播」就落在这里。只有真的有人抽到且包齐了才 ``push()`` 一条。

调试用：``ONI_SHOW_OFF_FAKE=1`` 时即使队列为空也下发一条占位条目（仅在需要肉眼确认
广播条样式时打开，默认关闭）。
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


def next_entry() -> dict[str, Any] | None:
    """取本轮要下发的那一条；真没人抽卡就返回 None（对应空 map，不广播）。"""
    with _LOCK:
        if _pending:
            return dict(_pending.pop(0))
        if os.environ.get("ONI_SHOW_OFF_FAKE") == "1":
            return default_entry()
        return None


def next_payload() -> dict[str, Any]:
    """客户端要的 map 形状；无人抽卡时是空 map，绝不返回数组。"""
    entry = next_entry()
    return {} if entry is None else {"0": entry}


def pending_count() -> int:
    with _LOCK:
        return len(_pending)


def reset() -> None:
    global _last_delivered
    with _LOCK:
        _pending.clear()
        _last_delivered = None
