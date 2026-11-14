"""Official politic mission-chain rules loaded from ``politicMission.json``."""
from __future__ import annotations

from typing import Any

from app.tables import TableCatalog, TableError

UNLOCK_BITS: dict[str, int] = {
    "unlockFull": 0x0FFFFFFF,
    "unlockShop": 0x00000001,
    "unlockConstruction": 0x00000002,
    "unlockInventory": 0x00000004,
    "unlockHarvest": 0x00000008,
    "unlockRemove": 0x00000010,
    "unlockPutIn": 0x00000020,
    "unlockDeck": 0x00000040,
    "unlockQuest": 0x00000080,
    "unlockVsBattle": 0x00000100,
    "unlockMyPage": 0x00000200,
    "unlockRecommendation": 0x00000400,
    "unlockKuji": 0x00000800,
    "unlockProduce": 0x00001000,
    "unlockTurfWar": 0x00002000,
    "unlockStrategy": 0x00004000,
    "unlockFriend": 0x00008000,
    "unlockMessageBoard": 0x00010000,
    "unlockAuction": 0x00020000,
    "unlockNationalPolitic": 0x00040000,
    "unlockErrantry": 0x00080000,
    "unlockPresentBox": 0x00100000,
    "unlockBooster": 0x00200000,
    "unlockMailBox": 0x00400000,
    "unlockSiege": 0x00800000,
    "unlockChangeMap": 0x01000000,
    "unlockScreenShot": 0x02000000,
    "unlockWaterMap": 0x04000000,
    "unlockGiganticRaidBoss": 0x08000000,
}

SYSTEM_MISSION = "po_mission_00000"
STATE_TO_LETTER = {
    "locked": "L",
    "opened": "O",
    "accepted": "A",
    "finished": "F",
    "closed": "C",
}


class MissionChain:
    def __init__(self, catalog: TableCatalog) -> None:
        self.catalog = catalog

    def rows(self) -> dict[str, dict[str, Any]]:
        # 表缺失不应炸整条请求链：与 GameplayService._table 同策略，缺表按空表处理。
        try:
            return self.catalog.load("politicMission")
        except TableError:
            return {}

    def row(self, mission_id: str) -> dict[str, Any]:
        return self.rows().get(mission_id) or {}

    def index_to_code(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for code, row in self.rows().items():
            try:
                result[str(int(row.get("index")))] = code
            except (TypeError, ValueError):
                continue
        return result

    def baseline_states(self) -> dict[str, str]:
        return {"0": "C"}

    def unlock_bits(self, states: dict[str, str]) -> int:
        index_map = self.index_to_code()
        bits = 0
        for key, letter in (states or {}).items():
            code = index_map.get(str(key), str(key))
            row = self.row(code)
            if not row:
                continue
            if str(letter) in {"A", "F", "C"}:
                bits |= self._bits(row.get("acceptUnlocks"))
            if str(letter) == "C":
                bits |= self._bits(row.get("clearUnlocks"))
        return bits & UNLOCK_BITS["unlockFull"]

    def clear_reward(self, mission_id: str) -> str:
        reward_id = str(self.row(mission_id).get("clearReward") or "")
        return "" if reward_id in {"", "none"} else reward_id

    @staticmethod
    def _bits(unlocks: Any) -> int:
        if not isinstance(unlocks, (list, tuple)):
            return 0
        result = 0
        for unlock in unlocks:
            result |= UNLOCK_BITS.get(str(unlock), 0)
        return result
