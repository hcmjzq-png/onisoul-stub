"""Verified mypage/playerLevel first-tier claim only; not mounted in production.

Evidence and local compatibility decisions: H deep-review.json / README.md.
The original request identifies a category, NOT a tier or operation nonce.
Never advance repeated requests to another tier. Unsupported categories fail.
"""
from __future__ import annotations

import copy
from functools import partial
from typing import Any

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


class AccountProgressTrophies(PlayerServices):
    CATEGORY = "playerLevel"
    FIRST = "playerLevel_001"

    def register(self, registry: Any) -> None:
        for api, action in {
            "trophy/getTrophyProgress": self.progress,
            "trophy/completeTrophy": self.claim,
            "trophy/messageWindowTrophy": self.acknowledge,
        }.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def call(self, api: str, action: Any, params: dict, session: dict | None) -> dict:
        # Endpoint-local shape correction: shared response_shapes is integrator-owned.
        player_id = self.service._player_id(session)
        if not player_id:
            return {"errorReason": "authentication required"}
        player, dirty = self.service._load(player_id)
        staged = copy.deepcopy(player)
        try:
            if params.get("access") != "mypage":
                raise ValueError("no stub response: only mypage trophy access is supported")
            if not staged["entity"].get("created"):
                raise ValueError("player must be created")
            payload = action(staged, params)
        except ValueError as exc:
            return {"errorReason": str(exc)}
        if dirty or staged != player:
            self.service._save(staged, player_id)
        if api == "trophy/getTrophyProgress":
            return copy.deepcopy(payload)  # both original mypage consumers enumerate root
        return response_shapes.success(api, copy.deepcopy(payload))

    def rules(self) -> list[dict]:
        setting = self.table("trophy_setting").get(self.CATEGORY)
        if not isinstance(setting, dict) or setting.get("access") != "mypage":
            raise ValueError("no stub response: invalid playerLevel trophy setting row")
        maximum = integer(setting.get("maxLevel"), 2, 100)
        table = self.table("mypage_trophy")
        rows = []
        previous = 0
        for index in range(1, maximum + 1):
            key = f"{self.CATEGORY}_{index:03}"
            row = table.get(key)
            if not isinstance(row, dict) or row.get("id") != key or row.get("category") != self.CATEGORY:
                raise ValueError(f"no stub response: invalid trophy row reference {key}")
            threshold = integer(row.get("clearAmount"), 1)
            if threshold <= previous:
                raise ValueError("no stub response: non-increasing trophy thresholds")
            previous = threshold
            rows.append(row)
        return rows

    def progress(self, player: dict, params: dict) -> dict:
        rows = self.rules()
        stored = player.get("accountProgress", {})
        claimed = self.FIRST in stored.get("trophyClaims", {})
        index = 1 if claimed else 0
        qualified = integer(player["entity"]["level"], 1) >= integer(rows[index]["clearAmount"], 1)
        # Local notification policy: only the supported first tier may notify.
        window = 1 if qualified and not claimed and not stored.get("levelTrophyNoticeSeen", False) else 0
        return {self.CATEGORY: {"level": float(index + 1),
                               "status": "complete" if qualified else "accept", "window": float(window)}}

    def require_category(self, params: dict) -> None:
        if params.get("category") != self.CATEGORY:
            raise ValueError("no stub response: only playerLevel first-tier trophy is supported")

    def acknowledge(self, player: dict, params: dict) -> dict:
        self.require_category(params)
        current = self.progress(player, params)[self.CATEGORY]
        stored = player.get("accountProgress", {})
        if stored.get("levelTrophyNoticeSeen", False):
            return {}  # repeated notification confirmation, never a reward operation
        if current["window"] != 1:
            raise ValueError("no stub response: no supported trophy notification to acknowledge")
        player.setdefault("accountProgress", {})["levelTrophyNoticeSeen"] = True
        return {}

    def reward(self, rule: dict) -> dict[str, int]:
        code = rule.get("clearReward")
        if code != "reward06_playerLevel_001":
            raise ValueError("no stub response: unsupported first-tier reward reference")
        row = self.table("reward06_trophy").get(code)
        if not isinstance(row, dict):
            raise ValueError("no stub response: trophy reward row reference is missing")
        amounts: dict[str, int] = {}
        groups = set()
        for index in range(1, 11):
            item = row.get(f"itemId{index}")
            if item in (None, "", "none"):
                continue
            group = row.get(f"group{index}")
            low, high = row.get(f"count{index}min"), row.get(f"count{index}max")
            if (not isinstance(group, str) or group in ("", "none") or group in groups
                    or row.get(f"ratio{index}min") != 100 or row.get(f"ratio{index}max") != 100
                    or low != high):
                raise ValueError("no stub response: non-fixed trophy reward selection")
            if item not in ("item11_0000101", "item08_0102701") or item in amounts:
                raise ValueError("no stub response: unsupported trophy reward item")
            groups.add(group)
            amounts[item] = integer(low, 1)
        if set(amounts) != {"item11_0000101", "item08_0102701"}:
            raise ValueError("no stub response: incomplete first-tier reward")
        jewel = self.table("item08").get("item08_0102701")
        if not isinstance(jewel, dict) or jewel.get("category") != "jewel" or jewel.get("enable") is not True:
            raise ValueError("no stub response: unsupported jewel definition")
        return amounts

    def claim(self, player: dict, params: dict) -> dict:
        self.require_category(params)
        stored = player.get("accountProgress", {})
        if self.FIRST in stored.get("trophyClaims", {}):
            # No tier/nonce on the wire: replay must not claim tier 2 by accident.
            raise ValueError("no stub response: first trophy already claimed; subsequent tiers unsupported")
        rule = self.rules()[0]
        if integer(player["entity"]["level"], 1) < integer(rule["clearAmount"], 1):
            raise ValueError("trophy level requirement not met")
        amounts = self.reward(rule)
        gold = player["resources"]["gold"]
        total_gold = integer(gold["amount"]) + amounts["item11_0000101"]
        if total_gold > integer(gold["maxAmount"]):
            raise ValueError("no stub response: trophy overflow/inbox delivery unsupported")
        jewel_id = "item08_0102701"
        total_jewels = integer(player["items"].get(jewel_id, 0)) + amounts[jewel_id]
        integer(total_jewels)
        # All validations precede mutation; the claim ledger and assets share one save/CAS.
        gold["amount"] = total_gold
        player["items"][jewel_id] = total_jewels
        stored = player.setdefault("accountProgress", {})
        stored.setdefault("trophyClaims", {})[self.FIRST] = {"rewards": copy.deepcopy(amounts)}
        stored["levelTrophyNoticeSeen"] = True
        return {"progress": self.progress(player, params),
                "rewards": {item: float(count) for item, count in amounts.items()},
                "characters": {}, "equips": {}, "toInBox": {}}
