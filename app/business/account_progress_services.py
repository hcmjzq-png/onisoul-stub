"""H account APIs, explicitly registered by the integrator (not mounted here).

Protocol evidence: docs/analysis/parallel-342/h-account-progress/evidence.json.
accountProgress is INTERNAL storage, not an original protocol field. Plugin
settings/logs never execute tasks, credit rewards, or grant paid time.
"""
from __future__ import annotations

import copy
import json
import math
import time
from functools import partial
from typing import Any, Callable, Mapping

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


class AccountProgressServices(PlayerServices):
    def __init__(self, service: Any, *, revisions: Mapping[str, int] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        # Deployment-owned manifest values; never infer revisions from dates.
        self.revisions = None if revisions is None else {
            key: float(integer(revisions[key])) for key in ("server", "unity", "table", "root")}
        self.clock = clock

    def register(self, registry: Any) -> None:
        from app.business.account_progress_trophies import AccountProgressTrophies

        AccountProgressTrophies(self.service).register(registry)
        registry.register("common/getRevisions", self.get_revisions)
        registry.register("common/getPlayerCogid", self.service._guard(
            "common/getPlayerCogid", self.get_cogid))
        for api, action in {
            "plugin/getPluginData": self.plugin_data,
            "plugin/setPluginData": self.set_plugin_data,
            "plugin/getPluginLog": self.plugin_logs,
            "plugin/addPluginLog": self.add_plugin_log,
        }.items():
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
        return {"pluginData": copy.deepcopy(stored.get("pluginSetting", {})),
                "pluginTime": {"pluginTime": float(stored.get("pluginExpiresAt", 0))}}

    def set_plugin_data(self, player: dict, params: dict) -> dict:
        stored = player.get("accountProgress", {})
        if stored.get("pluginExpiresAt", 0) < self.clock():
            raise ValueError("no stub response: plugin entitlement absent or expired")
        setting = params.get("pluginSetting")
        if not isinstance(setting, dict) or set(setting) - {"politic", "battle", "potion"}:
            raise ValueError("pluginSetting must contain only client setting sections")
        # Opaque UI preferences: only flat scalar dictionaries, never state patches.
        # Size limits are local storage policy, not original server rules.
        for section in setting.values():
            if not isinstance(section, dict):
                raise ValueError("plugin setting section must be a map")
            for key, value in section.items():
                if not isinstance(key, str) or not isinstance(value, (str, bool, int, float)):
                    raise ValueError("plugin setting values must be scalars")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if abs(value) > 2147483647 or not math.isfinite(value):
                        raise ValueError("plugin setting number outside supported range")
        if len(json.dumps(setting, ensure_ascii=True)) > 65536:
            raise ValueError("plugin settings exceed local storage limit")
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
