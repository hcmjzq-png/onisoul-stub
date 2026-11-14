"""H account APIs; only the reviewed subset is mounted by GameplayService.

Protocol evidence: docs/analysis/parallel-342/h-account-progress/evidence.json.
accountProgress is INTERNAL storage, not an original protocol field. Plugin
settings/logs never execute tasks, credit rewards, or grant paid time.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
from functools import partial
from typing import Any, Callable, Mapping

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


# Original PluginPoliticSetting / PluginBattleSetting use HashAccessor's typed
# casts. Scalar-only validation is insufficient: e.g. a string cannot be a bool.
SETTING_FIELDS = {
    "politic": {
        "bool": set("Map0 Map1 Map2 LevelUp PoliticBattle Mail Trade Harvest Manual AutoPoliticQuest".split()),
        "number": {"PoliticPointKeep", "HarvestCount"},
        "string": {"TradeType"},
    },
    "battle": {
        "bool": set("OniQuest OniQuestHigh Event DreamSpace RaidBoss Battle BattleNormal BattleTenka BattleSiege".split()),
        "number": set("OniQuestStory OniQuestChapter OniQuestEpisode BattleMoney".split()),
        "string": {"EventType"},
    },
    "potion": {
        "bool": set("PoliticPotion QuestPotion RaidbossPotion AllPotion".split()),
        "number": set("PoliticPoint QuestPoint RaidbossPoint AllPotionPoint".split()),
        "string": set("PoliticPotionID QuestPotionID RaidBossPotionID AllPotionID".split()),
    },
}


def validate_plugin_setting(setting: Any) -> None:
    """Validate client serialization, not task eligibility or original rules."""
    if not isinstance(setting, dict) or set(setting) - SETTING_FIELDS.keys():
        raise ValueError("pluginSetting must contain only client setting sections")
    for name, section in setting.items():
        if not isinstance(section, dict):
            raise ValueError("plugin setting section must be a map")
        # PluginBattleSetting dereferences this unconditionally and indexes the
        # two-element PluginMisc.getDreamSpaceName array. Missing is unsafe too.
        if name == "battle":
            value = section.get("DreamSpaceType")
            if not ((type(value) is str and value in {"0", "1"}) or
                    (type(value) in (int, float) and value in (0, 1))):
                raise ValueError("battle.DreamSpaceType must be 0 or 1")
        for key, value in section.items():
            if not isinstance(key, str):
                raise ValueError("plugin setting key must be a string")
            if name == "battle" and key == "DreamSpaceType":
                continue
            kind = next((kind for kind, keys in SETTING_FIELDS[name].items() if key in keys), None)
            if name == "politic" and re.fullmatch(r"Manual(Building|Produce|Count)\d+", key):
                kind = "number" if key.startswith("ManualCount") else "string"
            if kind == "bool" and type(value) is bool:
                continue
            if kind == "string" and isinstance(value, str):
                continue
            if kind == "number" and type(value) in (int, float):
                if -2147483648 <= value <= 2147483647 and math.isfinite(value):
                    continue
            raise ValueError("unknown plugin setting field or invalid client type: " + name + "." + key)
    # Local storage limit, not an original server rule.
    if len(json.dumps(setting, ensure_ascii=True)) > 65536:
        raise ValueError("plugin settings exceed local storage limit")


class AccountProgressServices(PlayerServices):
    def __init__(self, service: Any, *, revisions: Mapping[str, int] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        # Deployment-owned manifest values; never infer revisions from dates.
        self.revisions = None if revisions is None else {
            key: float(integer(revisions[key])) for key in ("server", "unity", "table", "root")}
        self.clock = clock

    def register(self, registry: Any, *, apis: frozenset[str] | None = None) -> None:
        if apis is None or "common/getRevisions" in apis:
            registry.register("common/getRevisions", self.get_revisions)
        if apis is None or "common/getPlayerCogid" in apis:
            registry.register("common/getPlayerCogid", self.service._guard(
                "common/getPlayerCogid", self.get_cogid))
        for api, action in {
            "plugin/getPluginData": self.plugin_data,
            "plugin/setPluginData": self.set_plugin_data,
            "plugin/getPluginLog": self.plugin_logs,
            "plugin/addPluginLog": self.add_plugin_log,
        }.items():
            if apis is None or api in apis:
                registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def get_revisions(self, params: dict, session: dict | None) -> dict:
        # TableLoad requests this BEFORE authentication.
        api = "common/getRevisions"
        if self.revisions is None:
            return self.service._failure(api, "no stub response: deployment revisions not configured")
        return response_shapes.success(api, copy.deepcopy(self.revisions))

    def get_cogid(self, params: dict, session: dict | None) -> dict:
        api = "common/getPlayerCogid"
        player_id = self.service._player_id(session)
        if not player_id:
            return self.service._failure(api, "authentication required")
        # Configs.GetUserInfo consumes playerId.ToString. Stub account ID is a
        # compatibility identity, not a recovered external COG account binding.
        return response_shapes.success(api, {"playerId": player_id})

    @staticmethod
    def plugin_data(player: dict, params: dict) -> dict:
        stored = player.get("accountProgress", {})
        setting = stored.get("pluginSetting", {})
        # Reject unsafe old/imported saves too; never return data that crashes
        # the typed client callback, and do not silently rewrite the save.
        validate_plugin_setting(setting)
        expires = integer(stored.get("pluginExpiresAt", 0), maximum=9007199254740991)
        return {"pluginData": copy.deepcopy(setting),
                "pluginTime": {"pluginTime": float(expires)}}

    def set_plugin_data(self, player: dict, params: dict) -> dict:
        stored = player.get("accountProgress", {})
        if integer(stored.get("pluginExpiresAt", 0), maximum=9007199254740991) < self.clock():
            raise ValueError("no stub response: plugin entitlement absent or expired")
        setting = params.get("pluginSetting")
        validate_plugin_setting(setting)
        player.setdefault("accountProgress", {})["pluginSetting"] = copy.deepcopy(setting)
        return {}

    @staticmethod
    def plugin_logs(player: dict, params: dict) -> dict:
        return {"logdatas": copy.deepcopy(player.get("accountProgress", {}).get("pluginLogs", {}))}

    def add_plugin_log(self, player: dict, params: dict) -> dict:
        log = params.get("logdata")
        if not isinstance(log, dict) or not {"action", "reward"} <= set(log) or set(log) - {"action", "reward", "time"}:
            raise ValueError("logdata requires action and reward")
        if not isinstance(log["action"], str) or len(log["action"]) > 4096:
            raise ValueError("invalid diagnostic action")
        reward = log["reward"]
        if not isinstance(reward, dict) or len(reward) > 256:
            raise ValueError("invalid diagnostic reward map")
        for key, value in reward.items():
            if not isinstance(key, str) or len(key) > 128:
                raise ValueError("invalid diagnostic item key")
            integer(value)
        stored = player.setdefault("accountProgress", {})
        sequence = int(stored.get("pluginLogSequence", 0)) + 1
        logs = stored.setdefault("pluginLogs", {})
        logs[str(sequence)] = {"action": log["action"], "reward": copy.deepcopy(reward),
                               "time": float(self.clock())}
        stored["pluginLogSequence"] = sequence
        # Bounded diagnostic history; retries append, never grant rewards.
        for key in sorted(logs, key=int)[:-200]:
            del logs[key]
        return {}
