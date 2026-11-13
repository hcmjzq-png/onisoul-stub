"""turfWar 战况占位：给客户端一个「未参战」的合法战况，而不是空映射。

事件表里 `turfWar` 一存在，`TurfWarBriefCache.setup` 就会立刻请求
`turfWar/getWarSituation`（`TurfWarBriefCache.cs:356-359`），回调里
`(Hashtable)result["selfBelong"]` 之后直接取 `["team"]` / `["battlefield"]`，
全程无守卫（`TurfWarBriefCache.cs:362-370`）。后续 UI 继续读：

    bonus.team / bonus.endTime / bonus.battlefield   :325-338（getBonusRestTime）
    situation.global.advantage                       :203-205（Advantage）
    situation.battlefields                           :94-104（BattlefieldsInformation）
    isMovable                                        :235（IsMoveable）
    battleRules                                      :171-173、:271、:284（BattleRule*）

回调本身拿到空字典不会立刻炸（`selfBelong` 存在时取到 `null` 只是让 `team_` /
`battlefield_` 变成 `null`），但后续 UI 第一次读就会 NRE：

    BattlefieldsInformation：`situation` 缺失 -> :103
    Advantage             ：`situation` 缺失 -> :204
    IsMoveable            ：`isMovable` 缺失 -> :235（`(bool)null` 拆箱）
    IsBonusTime           ：`bonus` 缺失 -> :325
    BattleRuleId          ：`battleRules` 缺失 -> :172

所以这里回一个 `team`/`battlefield` 都为 `"none"` 的战况：客户端把 `"none"` 当
「未参战」哨兵（`TurfWarWorldMap.cs:108`、`isBonus` :194、`getBonusRestTime`
:321-330），于是 `setup` 走非入场分支，不会去调 `turfWar/entryWar`。

注意：`setup` 只在 `status_ == "open"` 且 `team == "none"` 时才自动入场
（`TurfWarBriefCache.cs:363`）。当前 `common/getEventStatuses` 的 `turfWar.status`
占位是 `""`，不会触发；若以后把它置成 `"open"`，客户端会去打 `turfWar/entryWar`，
那条链（`turfWar/entryWar` 的 `team`、`turfWar/entryBattlefield`）尚未核对。

战场名（`situation.battlefields` / `battleRules` 的键）取自 turfWar 战场表
（`TurfWarBattleFieldCatalogTableAccessor`），当前 `assets/pc/tables` 为空、表不可得，
所以只放 `"none"` 这一条与哨兵自洽的空记录；真实战场名与数值**未验证**。
"""
from __future__ import annotations

from typing import Any

from app.business import response_shapes

API = "turfWar/getWarSituation"
NONE = "none"
EVEN = "even"


def body() -> dict[str, Any]:
    """每次调用都造新 dict：返回体可能被上层改写，共享对象会串。"""
    return {
        "team": NONE,
        "battlefield": NONE,
        "isMovable": False,
        "selfBelong": {"team": NONE, "battlefield": NONE},
        "situation": {
            "global": {"advantage": EVEN},
            "battlefields": {
                NONE: {
                    "advantage": EVEN,
                    "east": 0.0,
                    "eastPoint": 0.0,
                    "west": 0.0,
                    "westPoint": 0.0,
                }
            },
        },
        "bonus": {"team": NONE, "battlefield": NONE, "endTime": 0.0},
        "battleRules": {NONE: ""},
    }


def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    return response_shapes.success(API, body())


def register(registry: Any) -> None:
    registry.register(API, handler)
