"""幸运用户展示队列（show_off）。

客户端在主城会周期轮询 ``common/periodicInquiry``（``PeriodicRounder.refresh`` /
``PeriodicChecking``），并从回包根表的 ``show_off`` 数组里取「幸运用户」条目，交给
``ShowOffDataHandler`` 排队，由 ``ShowOffMsg`` 浮层在主城画面上飘过（字段 UserName /
CharacterId / SkillId，见客户端 ``ShowOffData`` 类成员与格式串
``ShowOffData, UserName:{0}, CharacterId:{1}, SkillId:{2}``）。

客户端对这个字段没有「空」这个合法状态：
    字段缺失 → There's no "show_off" field in return payload
    数组为空 → There's no data in "show_off" field
两者都会抛异常，异常被 WebApiClient 捕获后弹「联机中断(1)」。因此本模块对外只承诺一件事：
**永远至少给一条**。

取值顺序：
    1. 有待播事件 → 取最早的一条（FIFO），并记为「最近已播」；
    2. 队列空、但播过 → 回最近一条；内容与上次完全相同，客户端按条目哈希去重，不会重复飘；
    3. 队列空、且从未播过 → 回内置占位条目。

真实触发点是抽卡命中稀有武将（契约表 ``politic/lottery/lot``）。本 Stub 还没有抽卡实现，
所以目前只有 ``push()`` 这个入口；接上抽卡后在该处调用 ``push()`` 即可，本模块不用改。

限制（已知、可接受）：
    * 队列在内存里，进程重启后待播事件丢失（展示型数据，不影响存档）；
    * 条目引用的武将必须在服务端有对应 AssetBundle，否则客户端播浮层时会加载失败，
      因此 ``push()`` 先用 ``bundle_exists()`` 校验，缺包直接拒绝入队。
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Any

from app import paths

# 待播队列上限：展示型数据，超出后丢最早的，避免无界增长。
MAX_PENDING = 32

# 队列空且从未播过时的占位条目。武将取服务端确实有包的 chara1_00726_01，
# 技能取 skill 表里存在的 skill1_01002_01（表内 4129 条）。
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
    """构造一条展示条目。

    键名同时给 camelCase 与 PascalCase 两份：客户端是按成员名反射映射的，多给的键会被
    忽略；这样无论它取 `userName` 还是 `UserName` 都能命中，省掉一次「猜错大小写 →
    用户重跑一轮游戏」的成本。
    """
    return {
        "userName": user_name,
        "UserName": user_name,
        "characterId": character_id,
        "CharacterId": character_id,
        "skillId": skill_id,
        "SkillId": skill_id,
    }


def default_entry() -> dict[str, Any]:
    return make_entry(DEFAULT_USER_NAME, DEFAULT_CHARACTER_ID, DEFAULT_SKILL_ID)


def push(user_name: str, character_id: str, skill_id: str) -> dict[str, Any]:
    """入队一条待播事件；武将缺包时拒绝（返回 ValueError 由调用方决定是否忽略）。"""
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
    """取本轮要下发的条目：待播 → 最近已播 → 内置占位。"""
    global _last_delivered
    with _LOCK:
        if _pending:
            entry = _pending.pop(0)
            _last_delivered = entry
            return dict(entry)
        if _last_delivered is not None:
            return dict(_last_delivered)
        return default_entry()


def pending_count() -> int:
    with _LOCK:
        return len(_pending)


def reset() -> None:
    """清空队列与最近已播（测试用）。"""
    global _last_delivered
    with _LOCK:
        _pending.clear()
        _last_delivered = None
