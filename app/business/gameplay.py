"""First playable slice: login, player bootstrap, main map, and missions 1-4."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from app import sessions, state
from app.business import placeholders, response_shapes
from app.business.mission_chain import MissionChain, SYSTEM_MISSION, STATE_TO_LETTER
from app.business.registry import Registry
from app.tables import TableCatalog, TableError, default_catalog

StateLoader = Callable[[str], dict[str, Any]]
StateSaver = Callable[[dict[str, Any], str], None]

# The official reset table has no readable starting draft inventory. Novice
# mission 2 requires one castle, so this is the minimum task-specific grant.
STARTER_DRAFT_ID = "draft2000002"
DEFAULT_COUNTRY = "country01"
DEFAULT_NAVIGATOR = "navi8000101"
DEFAULT_COLOR = "color1"

ITEM_TO_RESOURCE = {
    "item11_0000101": "gold",
    "item11_0000201": "wood",
    "item11_0000301": "food",
    "item11_0000401": "iron",
    "item11_0000801": "credit",
    "item11_0000802": "credit",
}


def _now() -> float:
    return float(int(time.time()))


def _deep(value: Any) -> Any:
    return copy.deepcopy(value)


def _merge_defaults(default: dict[str, Any], current: Any) -> dict[str, Any]:
    if not isinstance(current, dict):
        return _deep(default)
    result = _deep(default)
    for key, value in current.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge_defaults(result[key], value)
        else:
            result[key] = _deep(value)
    return result


def _coord(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        value = [value.get("0", value.get("x")), value.get("1", value.get("y"))]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _coord_key(x: int, y: int) -> str:
    return f"{x},{y}"


def _parse_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        except ValueError:
            pass
    return [item for item in re.split(r'[,\s\[\]"]+', text) if item]


class GameplayService:
    """Table-driven handlers with injectable persistence for tests."""

    def __init__(
        self,
        *,
        catalog: TableCatalog | None = None,
        load_state: StateLoader | None = None,
        save_state: StateSaver | None = None,
        session_store: Any | None = None,
    ) -> None:
        self.catalog = catalog or default_catalog()
        self.load_state = load_state or state.load
        self.save_state = save_state or state.save
        self.session_store = session_store or sessions
        self.missions = MissionChain(self.catalog)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def register(self, registry: Registry) -> Registry:
        handlers = {
            "auth/createPlayer": self.create_player,
            "auth/gameLogin": self.game_login,
            "auth/guestLogin": self.guest_login,
            "auth/login": self.auth_login,
            "auth/refreshToken": self.refresh_token,
            "auth/registerName": self.register_name,
            "common/getPlayerParams": self.get_player_params,
            "debug/debugLogin": self.debug_login,
            "debug/devLogin": self.dev_login,
            "deck/getAvatarCharacters": self.get_avatar_characters,
            "politic/map/getMapData": self.get_map_data,
            "politic/building/getBuildCounts": self.get_build_counts,
            "politic/building/getDrafts": self.get_drafts,
            "politic/mission/changeState": self.change_mission_state,
            "politic/mission/getMissionsInProgress": self.get_missions_in_progress,
            "politic/mission/getStatesFromAllMissions": self.get_mission_states,
            "politic/mission/setWorkingValue": self.set_working_value,
            "politic/task/completeTasks": self.complete_tasks,
            "politic/task/progressBuildTask": self.progress_build_task,
            "politic/task/submitBuildAndComplete": self.submit_build_and_complete,
            "politic/task/submitBuildTask": self.submit_build_task,
        }
        for api, handler in handlers.items():
            registry.register(api, self._guard(api, handler))
        return registry

    def _lock_for(self, player_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(player_id, threading.RLock())

    def _guard(self, api: str, handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        def guarded(
            params: dict[str, Any], session: dict[str, Any] | None
        ) -> dict[str, Any]:
            player_id = self._player_id(session)
            if not player_id:
                return handler(params, session)
            with self._lock_for(player_id):
                try:
                    return handler(params, session)
                except state.StateConflictError:
                    return self._failure(api, "state changed concurrently; retry")

        return guarded

    def _failure(
        self,
        api: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if response_shapes.shape_for(api) is response_shapes.ResponseShape.BARE_MAP:
            return {"errorReason": message}
        body = placeholders.payload(api)
        body.update(payload or {})
        body.update(
            {
                "succeeded": False,
                "errorReason": message,
                "message": message,
            }
        )
        return response_shapes.success(api, body)

    def _success(
        self, api: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = placeholders.payload(api)
        body.update(payload or {})
        return response_shapes.success(api, body)

    @staticmethod
    def _player_id(session: dict[str, Any] | None) -> str:
        return str((session or {}).get("playerId") or "")

    def _load(self, player_id: str) -> tuple[dict[str, Any], bool]:
        raw = self.load_state(player_id)
        merged = self._prepare_state(raw, player_id)
        return merged, merged != raw

    def _save(self, player: dict[str, Any], player_id: str) -> None:
        self.save_state(player, player_id)

    def _level_row(self, level: int = 1) -> dict[str, Any]:
        rows = self._table("playerLevel")
        return rows.get(str(level)) or {}

    def _max_level(self) -> int:
        levels = []
        for key in self._table("playerLevel"):
            try:
                levels.append(int(key))
            except (TypeError, ValueError):
                continue
        return max(levels, default=1)

    def _table(self, name: str) -> dict[str, Any]:
        try:
            return self.catalog.load(name)
        except TableError:
            return {}

    def _default_state(self, player_id: str) -> dict[str, Any]:
        level = self._level_row(1)
        return {
            "version": 2,
            "entity": {
                "playerId": player_id,
                "created": False,
                "username": "",
                "country": "",
                "level": 1,
                "exp": 0,
                "cap": self._max_level(),
                "currentMapKey": "map001",
                "maxMapCount": 1,
            },
            "actionPoints": {
                "politicPoint": {
                    "point": int(level.get("PP") or 0),
                    "maxPoint": int(level.get("PP") or 0),
                    "confirmTime": 0.0,
                },
                "missionPoint": {
                    "point": int(level.get("MP") or 0),
                    "maxPoint": int(level.get("MP") or 0),
                    "confirmTime": 0.0,
                },
                "battlePoint": {
                    "point": int(level.get("BP") or 0),
                    "maxPoint": int(level.get("BP") or 0),
                    "confirmTime": 0.0,
                },
            },
            # beginning_equipment.common.gold is not applied here: the observed
            # novice flow receives its 5000 gold from mission 1's reward.
            "resources": {
                key: {"amount": 0, "maxAmount": int(level.get(field) or 0)}
                for key, field in (
                    ("gold", "maxGold"),
                    ("wood", "maxWood"),
                    ("food", "maxFood"),
                    ("iron", "maxIron"),
                    ("stone", 0),
                    ("credit", 0),
                )
            },
            "kokudaka": 0,
            "navigator": {"id": "", "colorIndex": DEFAULT_COLOR},
            "counters": {
                "buildingCount": 0,
                "characterCount": 0,
                "equipCount": 0,
                "errantryTimes": 0,
                "nextBuildingId": 1,
            },
            "buildings": {},
            "occupiedGrids": {},
            "produce": {},
            "items": {},
            "drafts": {STARTER_DRAFT_ID: 1},
            "missions": self.missions.baseline_states(),
            "missionProgress": {},
            "missionRewards": {},
            "unlockBits": self.missions.unlock_bits(self.missions.baseline_states()),
            "characters": {},
            "decks": {},
            "lessonsDone": [],
        }

    def _prepare_state(self, raw: dict[str, Any], player_id: str) -> dict[str, Any]:
        result = _merge_defaults(self._default_state(player_id), raw)
        if isinstance(raw.get("drafts"), dict):
            result["drafts"] = _deep(raw["drafts"])
        result["entity"]["playerId"] = player_id
        if not isinstance(result.get("missions"), dict):
            result["missions"] = {}
        result["missions"].setdefault("0", "C")
        result["unlockBits"] = self._unlock_bits(result)
        for key in ("buildings", "occupiedGrids", "produce", "items", "characters", "decks"):
            if not isinstance(result.get(key), dict):
                result[key] = {}
        result["counters"]["buildingCount"] = len(result["buildings"])
        result["counters"]["characterCount"] = len(result["characters"])
        self._apply_limits(result)
        return result

    def _apply_limits(self, player: dict[str, Any]) -> None:
        level = self._level_row(int(player["entity"].get("level") or 1))
        if not level:
            return
        for point_key, level_key in (
            ("politicPoint", "PP"),
            ("missionPoint", "MP"),
            ("battlePoint", "BP"),
        ):
            box = player["actionPoints"][point_key]
            cap = int(level.get(level_key) or box.get("maxPoint") or 0)
            box["maxPoint"] = cap
            box["point"] = min(int(box.get("point") or 0), cap)
        for resource_key, level_key in (
            ("gold", "maxGold"),
            ("wood", "maxWood"),
            ("food", "maxFood"),
            ("iron", "maxIron"),
        ):
            player["resources"][resource_key]["maxAmount"] = int(
                level.get(level_key) or 0
            )
        player["entity"]["cap"] = self._max_level()
        map_count = sum(bool(level.get(f"mapSize{i}")) for i in range(5))
        player["entity"]["maxMapCount"] = max(1, map_count)

    def _map_size(self, player: dict[str, Any]) -> tuple[int, int]:
        level = self._level_row(int(player["entity"].get("level") or 1))
        size = level.get("mapSize0") or [30, 30]
        return int(size[0]), int(size[1])

    def _initial_characters(self, country: str) -> dict[str, dict[str, Any]]:
        equipment = self._table("beginning_equipment")
        row = equipment.get(country) or equipment.get(DEFAULT_COUNTRY) or {}
        item_ids: list[str] = []
        for key in ("questCharacters", "attackCharacters", "defenseCharacters"):
            item_ids.extend(str(item) for item in row.get(key) or [])
        items = self._table("item01")
        characters = self._table("character")
        result: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for item_id in item_ids:
            base_id = str((items.get(item_id) or {}).get("parameterId") or "")
            if not base_id or base_id in seen:
                continue
            seen.add(base_id)
            source = characters.get(base_id) or {}
            result[str(len(result) + 1)] = {
                "atk": float(source.get("atk") or 0),
                "def": float(source.get("def") or 0),
                "int": float(source.get("int") or 0),
                "atkAdd": 0.0,
                "defAdd": 0.0,
                "intAdd": 0.0,
                "grade": 1.0,
                "level": 1.0,
                "baseId": base_id,
                "exp": 0.0,
                "combinedPoint": 0.0,
                "purchasedVoiceId": "",
                "voice": str(source.get("voice") or ""),
                "skills": {},
            }
        return result

    def _create_player(
        self,
        player_id: str,
        *,
        username: str = "",
        country: str = "",
        navigator_id: str = "",
        color_index: str = "",
    ) -> dict[str, Any]:
        player = self._default_state(player_id)
        country = country or DEFAULT_COUNTRY
        navigator_id = navigator_id or DEFAULT_NAVIGATOR
        player["entity"].update(
            {
                "created": True,
                "username": username,
                "country": country,
            }
        )
        player["navigator"] = {
            "id": navigator_id,
            "colorIndex": color_index or DEFAULT_COLOR,
        }
        player["characters"] = self._initial_characters(country)
        player["counters"]["characterCount"] = len(player["characters"])
        return self._prepare_state(player, player_id)

    def _issue_login(
        self, account_key: str, token: str | None = None
    ) -> tuple[dict[str, Any], bool]:
        issued = self.session_store.issue(account_key, token=token)
        player_id = str(issued["playerId"])
        raw = self.load_state(player_id)
        existing = bool((raw.get("entity") or {}).get("created"))
        return issued, existing

    def dev_login(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        username = str(params.get("username") or "").strip()
        if not username:
            return self._failure("debug/devLogin", "username is required")
        issued, existing = self._issue_login(username)
        return self._success(
            "debug/devLogin",
            {
                "succeeded": existing,
                "token": issued["token"],
                "playerId": issued["playerId"],
            },
        )

    def debug_login(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        username = str(params.get("username") or "").strip()
        if not username:
            return self._failure("debug/debugLogin", "username is required")
        issued, existing = self._issue_login(username)
        return self._success(
            "debug/debugLogin",
            {
                "succeeded": existing,
                "token": issued["token"],
                "playerId": issued["playerId"],
            },
        )

    def guest_login(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        login_hash = str(params.get("loginHash") or "").strip()
        if not login_hash:
            return self._failure("auth/guestLogin", "loginHash is required")
        issued, existing = self._issue_login(f"guest:{login_hash}")
        return self._success(
            "auth/guestLogin",
            {
                "isCreatedPlayer": existing,
                "loginHash": login_hash,
                "token": issued["token"],
                "playerId": issued["playerId"],
            },
        )

    def auth_login(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        key = str(params.get("sessionKey") or "").strip()
        if not key:
            return self._failure("auth/login", "sessionKey is required")
        issued, _existing = self._issue_login(f"passport:{key}")
        return self._success(
            "auth/login",
            {"succeeded": True, "token": issued["token"], "playerId": issued["playerId"]},
        )

    def game_login(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        token = str(params.get("token") or "").strip()
        if not token:
            return self._failure("auth/gameLogin", "invalid token")
        try:
            resolved = (
                session if session is not None else self.session_store.resolve(token)
            )
        except Exception:
            resolved = None
        if resolved is None:
            return self._failure("auth/gameLogin", "invalid token")
        player_id = str(resolved["playerId"])
        raw = self.load_state(player_id)
        existing = bool((raw.get("entity") or {}).get("created"))
        return self._success(
            "auth/gameLogin",
            {
                "succeeded": existing,
                "token": token,
                "playerId": player_id,
                "certifiedInternetCafe": False,
                "container": "none",
            },
        )

    def refresh_token(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        token = str(params.get("token") or "").strip()
        if not token:
            return self._failure("auth/refreshToken", "invalid token")
        try:
            resolved = (
                session if session is not None else self.session_store.resolve(token)
            )
        except Exception:
            resolved = None
        if resolved is None:
            return self._failure("auth/refreshToken", "invalid token")
        return self._success(
            "auth/refreshToken",
            {"token": token, "playerId": resolved["playerId"]},
        )

    def create_player(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        player_id = self._player_id(session)
        if not player_id:
            return self._failure("auth/createPlayer", "authentication required")
        username = str(params.get("username") or "").strip()
        country = str(params.get("countryId") or "").strip()
        navigator_id = str(params.get("navigatorId") or "").strip()
        color_index = str(params.get("colorIndex") or DEFAULT_COLOR).strip()
        if not username:
            return self._failure("auth/createPlayer", "username is required")
        if country not in self._table("beginning_equipment"):
            return self._failure("auth/createPlayer", "invalid countryId")
        navigators = self._table("navigator")
        if navigators and navigator_id not in navigators:
            return self._failure("auth/createPlayer", "invalid navigatorId")
        if not re.fullmatch(r"color[0-9]+", color_index):
            return self._failure("auth/createPlayer", "invalid colorIndex")
        player, _dirty = self._load(player_id)
        if not player["entity"].get("created"):
            player = self._create_player(
                player_id,
                username=username,
                country=country,
                navigator_id=navigator_id,
                color_index=color_index,
            )
        self._save(player, player_id)
        return self._success("auth/createPlayer", {"playerId": player_id})

    def register_name(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        player_id = self._player_id(session)
        if not player_id:
            return self._failure("auth/registerName", "authentication required")
        username = str(params.get("username") or "").strip()
        if not username:
            return self._failure("auth/registerName", "username is required")
        player, _dirty = self._load(player_id)
        player["entity"]["username"] = username
        self._save(player, player_id)
        return self._success("auth/registerName", {"succeeded": True})

    def _session_player(
        self, api: str, session: dict[str, Any] | None
    ) -> tuple[str, dict[str, Any], bool] | dict[str, Any]:
        player_id = self._player_id(session)
        if not player_id:
            return self._failure(api, "authentication required")
        player, dirty = self._load(player_id)
        return player_id, player, dirty

    @staticmethod
    def _next_stamp() -> str:
        stamp = dt.datetime.fromtimestamp(time.time() + 86400, tz=dt.timezone.utc)
        stamp = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
        return (
            f"{stamp.year:04d}-{stamp.month:02d}-{stamp.day:02d}"
            f"T{stamp.hour}:{stamp.minute:02d}:{stamp.second:02d}+0000"
        )

    def _possession_limits(self, player: dict[str, Any]) -> dict[str, dict[str, float]]:
        level = self._level_row(int(player["entity"].get("level") or 1))
        result = {}
        for key, field in (
            ("character", "maxCharacter"),
            ("equip", "maxEquip"),
            ("building", "maxBuilding"),
        ):
            cap = float(level.get(field) or 0)
            result[key] = {"base": cap, "creditExpireAt": 0.0, "result": cap}
        return result

    def get_player_params(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("common/getPlayerParams", session)
        if isinstance(found, dict):
            return found
        player_id, player, dirty = found
        self._apply_limits(player)
        navigator = player.get("navigator") or {}
        active = {
            "id": str(navigator.get("id") or ""),
            "colorIndex": str(navigator.get("colorIndex") or DEFAULT_COLOR),
        }
        next_stamp = self._next_stamp()
        payload = {
            "entity": _deep(player["entity"]),
            "actionPoints": _deep(player["actionPoints"]),
            "resources": _deep(player["resources"]),
            "navigators": {"activeNavigator": active},
            "loginStamp": {"nextStampDate": next_stamp},
            "nextStampDate": next_stamp,
            "kokudaka": int(player.get("kokudaka") or 0),
            "buildingCount": float(player["counters"].get("buildingCount") or 0),
            "characterCount": float(player["counters"].get("characterCount") or 0),
            "equipCount": float(player["counters"].get("equipCount") or 0),
            "errantryTimes": float(player["counters"].get("errantryTimes") or 0),
            "possessionLimits": self._possession_limits(player),
        }
        if dirty:
            self._save(player, player_id)
        return self._success("common/getPlayerParams", payload)

    def get_avatar_characters(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("deck/getAvatarCharacters", session)
        if isinstance(found, dict):
            return found
        _player_id, player, dirty = found
        if dirty:
            self._save(player, _player_id)
        result = {
            character_id: _deep(record)
            for character_id, record in (player.get("characters") or {}).items()
            if isinstance(record, dict)
        }
        return response_shapes.success("deck/getAvatarCharacters", result)

    def get_mission_states(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/mission/getStatesFromAllMissions", session)
        if isinstance(found, dict):
            return found
        player_id, player, dirty = found
        states = dict(self.missions.baseline_states())
        states.update({str(key): str(value) for key, value in player["missions"].items()})
        player["missions"] = states
        unlock_bits = self._unlock_bits(player)
        if dirty or player.get("unlockBits") != unlock_bits:
            player["unlockBits"] = unlock_bits
            self._save(player, player_id)
        return self._success("politic/mission/getStatesFromAllMissions", {"states": states})

    def _unlock_bits(self, player: dict[str, Any]) -> int:
        derived = self.missions.unlock_bits(player["missions"])
        try:
            reported = int(player.get("unlockBits") or 0)
        except (TypeError, ValueError):
            reported = 0
        return (derived | reported) & 0x0FFFFFFF

    def get_missions_in_progress(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player(
            "politic/mission/getMissionsInProgress", session
        )
        if isinstance(found, dict):
            return found
        _player_id, player, _dirty = found
        missions = {
            mission_id: _deep(progress)
            for mission_id, progress in player["missionProgress"].items()
            if str((progress or {}).get("state") or "") != "closed"
        }
        missions[SYSTEM_MISSION] = {
            "state": "closed",
            "work0": self._unlock_bits(player),
            "timestamp": _now(),
        }
        return self._success(
            "politic/mission/getMissionsInProgress", {"missions": missions}
        )

    def set_working_value(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/mission/setWorkingValue", session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        if str(params.get("missionId") or "") == SYSTEM_MISSION:
            for index, value in zip(params.get("indexes") or [], params.get("values") or []):
                try:
                    if int(index) == 0:
                        player["unlockBits"] = self._unlock_bits(player) | int(value)
                except (TypeError, ValueError):
                    continue
            self._save(player, player_id)
        return self._success("politic/mission/setWorkingValue")

    def change_mission_state(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/mission/changeState", session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        mission_ids = _parse_ids(params.get("missionIds"))
        states = _parse_ids(params.get("states"))
        if not mission_ids and params.get("missionId"):
            mission_ids = [str(params["missionId"])]
        if not states and params.get("state"):
            states = [str(params["state"])]
        out: dict[str, Any] = {}
        reward_total: dict[str, int] = {}
        changed = False
        for mission_id, new_state in zip(mission_ids, states):
            letter = STATE_TO_LETTER.get(new_state)
            if not letter or mission_id not in self.missions.rows():
                continue
            progress = player["missionProgress"].setdefault(mission_id, {})
            previous = str(progress.get("state") or "")
            progress.update({"state": new_state, "timestamp": _now()})
            player["missions"][str(self.missions.row(mission_id).get("index"))] = letter
            changed = True
            reward: dict[str, float] = {}
            if new_state == "closed" and previous != "closed":
                granted = player["missionRewards"].get(mission_id)
                if not granted:
                    items = self._mission_reward(player, mission_id)
                    if items:
                        granted = {
                            "items": {str(key): int(value) for key, value in items.items()}
                        }
                        player["missionRewards"][mission_id] = granted
                        for item_id, amount in items.items():
                            reward_total[item_id] = reward_total.get(item_id, 0) + amount
                reward = {
                    str(item): float(amount)
                    for item, amount in ((granted or {}).get("items") or {}).items()
                }
            out[mission_id] = {**progress, "reward": reward}
        player["unlockBits"] = self._unlock_bits(player)
        if changed:
            self._save(player, player_id)
        return self._success(
            "politic/mission/changeState",
            {
                "mission": out,
                "reward": {key: float(value) for key, value in reward_total.items()},
                "toInbox": {},
            },
        )

    def _mission_reward(
        self, player: dict[str, Any], mission_id: str
    ) -> dict[str, int]:
        reward_id = self.missions.clear_reward(mission_id)
        if not reward_id:
            return {}
        row = self._table("reward01_politic").get(reward_id) or {}
        raw: dict[str, int] = {}
        for index in range(1, 11):
            item_id = str(row.get(f"itemId{index}") or "")
            if not item_id or item_id == "none":
                continue
            if int(row.get(f"ratio{index}max") or 0) <= 0:
                continue
            amount = int(row.get(f"count{index}min") or 0)
            if amount > 0:
                raw[item_id] = raw.get(item_id, 0) + amount
        resolved = self._resolve_country_rewards(
            raw, str(player["entity"].get("country") or "")
        )
        self._grant_items(player, resolved)
        return resolved

    def _resolve_country_rewards(
        self, items: dict[str, int], country: str
    ) -> dict[str, int]:
        country_rows = self._table("reward99_country")
        result: dict[str, int] = {}
        for item_id, amount in items.items():
            mapped = item_id
            if item_id.startswith("country_") and item_id.endswith("_self"):
                row = country_rows.get(item_id[:-5]) or {}
                candidate = str(row.get(country) or "")
                if candidate and candidate != "none":
                    mapped = candidate
            result[mapped] = result.get(mapped, 0) + int(amount)
        return result

    @staticmethod
    def _grant_items(player: dict[str, Any], items: dict[str, int]) -> None:
        for item_id, amount in items.items():
            resource = ITEM_TO_RESOURCE.get(item_id)
            if resource:
                player["resources"][resource]["amount"] = (
                    int(player["resources"][resource].get("amount") or 0)
                    + int(amount)
                )
            else:
                player["items"][item_id] = int(player["items"].get(item_id) or 0) + int(
                    amount
                )

    def _draft_amounts(self, player: dict[str, Any]) -> dict[str, float]:
        amounts = {
            str(draft_id): float(amount)
            for draft_id, amount in player.get("drafts", {}).items()
            if int(amount or 0) > 0
        }
        items = self._table("item04")
        for item_id, amount in player.get("items", {}).items():
            row = items.get(item_id) or {}
            draft_id = str(row.get("parameterId") or "")
            if row.get("category") == "draft" and draft_id and int(amount or 0) > 0:
                amounts[draft_id] = amounts.get(draft_id, 0.0) + float(amount)
        return amounts

    def get_drafts(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/building/getDrafts", session)
        if isinstance(found, dict):
            return found
        _player_id, player, dirty = found
        if dirty:
            self._save(player, _player_id)
        return {
            draft_id: {"amount": float(amount)}
            for draft_id, amount in self._draft_amounts(player).items()
        }

    def get_build_counts(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player(
            "politic/building/getBuildCounts", session
        )
        if isinstance(found, dict):
            return found
        _player_id, player, dirty = found
        counts: dict[str, float] = {}
        for record in player["buildings"].values():
            if str(record.get("status") or "") == "building":
                continue
            type_id = str(record.get("buildingTypeId") or "")
            if type_id:
                counts[type_id] = counts.get(type_id, 0.0) + 1.0
        if dirty:
            self._save(player, _player_id)
        return self._success("politic/building/getBuildCounts", {"type": counts})

    def _map_state(self, player: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        width, height = self._map_size(player)
        occupied = {
            str(coord): str(instance_id)
            for coord, instance_id in player["occupiedGrids"].items()
        }
        navigator = player.get("navigator") or {}
        active = {
            "id": str(navigator.get("id") or ""),
            "colorIndex": str(navigator.get("colorIndex") or DEFAULT_COLOR),
        }
        building_groups = {
            "buildings": _deep(player["buildings"]),
            "producings": _deep(player["produce"]),
        }
        map_data = {
            "size": {"width": float(width), "height": float(height)},
            "occupiedGrids": occupied,
        }
        return map_data, building_groups

    def get_map_data(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/map/getMapData", session)
        if isinstance(found, dict):
            return found
        player_id, player, dirty = found
        map_data, building_groups = self._map_state(player)
        navigator = player.get("navigator") or {}
        active = {
            "id": str(navigator.get("id") or ""),
            "colorIndex": str(navigator.get("colorIndex") or DEFAULT_COLOR),
        }
        payload = {
            "map": map_data,
            "occupiedGrids": map_data["occupiedGrids"],
            "buildings": _deep(player["buildings"]),
            "producings": _deep(player["produce"]),
            "buildingEvents": {},
            "tasks": {
                "buildings": _deep(player["buildings"]),
                "producings": _deep(player["produce"]),
            },
            "navigators": {
                "activeNavigator": active,
                "expiredNavigators": {},
            },
            "expiredNavigators": {},
            "deployedMapKey": str(player["entity"].get("currentMapKey") or "map001"),
            "currentMapId": 0.0,
            "buildingCount": float(len(player["buildings"])),
            "actionPoints": _deep(player["actionPoints"]),
            "resources": _deep(player["resources"]),
            "possessionLimits": self._possession_limits(player),
        }
        if dirty:
            self._save(player, player_id)
        return self._success("politic/map/getMapData", payload)

    def _building_cells(self, player: dict[str, Any]) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        buildings = self._table("building")
        for record in player["buildings"].values():
            row = buildings.get(record.get("buildingTypeId") or "") or {}
            try:
                width, height = map(int, (row.get("size") or [1, 1])[:2])
            except (TypeError, ValueError):
                width = height = 1
            x = int(record.get("x") or 0)
            y = int(record.get("y") or 0)
            cells.update(
                (dx, dy)
                for dx in range(x - width + 1, x + 1)
                for dy in range(y - height + 1, y + 1)
            )
        return cells

    def _consume_draft(self, player: dict[str, Any], draft_id: str) -> None:
        direct = int(player["drafts"].get(draft_id) or 0)
        if direct > 0:
            if direct == 1:
                player["drafts"].pop(draft_id, None)
            else:
                player["drafts"][draft_id] = direct - 1
            return
        item_rows = self._table("item04")
        for item_id, amount in list(player["items"].items()):
            row = item_rows.get(item_id) or {}
            if row.get("parameterId") != draft_id or int(amount or 0) <= 0:
                continue
            if int(amount) == 1:
                player["items"].pop(item_id, None)
            else:
                player["items"][item_id] = int(amount) - 1
            return

    def _build_from_draft(
        self,
        player: dict[str, Any],
        draft_id: str,
        position: tuple[int, int],
        *,
        completed: bool,
    ) -> dict[str, Any] | None:
        draft = self._table("draft").get(draft_id) or {}
        building_type = str(draft.get("buildType") or "")
        row = self._table("building").get(building_type) or {}
        if not draft or not row:
            return None
        if bool(draft.get("isConsume")) and not self._draft_amounts(player).get(draft_id):
            return None
        x, y = position
        width, height = self._map_size(player)
        try:
            size_x, size_y = map(int, (row.get("size") or [1, 1])[:2])
        except (TypeError, ValueError):
            size_x = size_y = 1
        cells = {
            (dx, dy)
            for dx in range(x - size_x + 1, x + 1)
            for dy in range(y - size_y + 1, y + 1)
        }
        if (
            x - size_x + 1 < 0
            or y - size_y + 1 < 0
            or x >= width
            or y >= height
            or cells & self._building_cells(player)
        ):
            return None
        costs = list(zip(row.get("costTypes") or [], row.get("costAmounts") or []))
        for resource, amount in costs:
            box = player["resources"].get(resource)
            if box is not None and int(box.get("amount") or 0) < int(amount or 0):
                return None
        for resource, amount in costs:
            box = player["resources"].get(resource)
            if box is not None:
                box["amount"] = int(box.get("amount") or 0) - int(amount or 0)
        instance_id = int(player["counters"].get("nextBuildingId") or 1)
        player["counters"]["nextBuildingId"] = instance_id + 1
        record = {
            "instanceId": instance_id,
            "buildingTypeId": building_type,
            "level": 1,
            "exp": 0,
            "x": x,
            "y": y,
            "deployedMapKey": str(player["entity"].get("currentMapKey") or "map001"),
            "status": "none" if completed else "building",
            "remainedClickCount": 0 if completed else int(draft.get("progressCount") or 0),
            "durability": int(row.get("durability") or 10001),
        }
        player["buildings"][str(instance_id)] = record
        player["occupiedGrids"][_coord_key(x, y)] = str(instance_id)
        player["counters"]["buildingCount"] = len(player["buildings"])
        if bool(draft.get("isConsume")):
            self._consume_draft(player, draft_id)
        point = player["actionPoints"].setdefault(
            "politicPoint", {"point": 0, "maxPoint": 0, "confirmTime": 0.0}
        )
        point["point"] = max(0, int(point.get("point") or 0) - 1)
        return record

    def submit_build_task(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        return self._submit_build("politic/task/submitBuildTask", params, session, False)

    def submit_build_and_complete(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        return self._submit_build(
            "politic/task/submitBuildAndComplete", params, session, True
        )

    def _submit_build(
        self,
        api: str,
        params: dict[str, Any],
        session: dict[str, Any] | None,
        completed: bool,
    ) -> dict[str, Any]:
        found = self._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        position = _coord(params.get("originCoord"))
        if position is None:
            return self._failure(api, "originCoord is required")
        record = self._build_from_draft(
            player,
            str(params.get("draftId") or ""),
            position,
            completed=completed,
        )
        if record is None:
            return self._failure(api, "draft, coordinates, or resources are invalid")
        self._save(player, player_id)
        return self._success(
            api,
            {
                "buildingId": str(record["instanceId"]),
                "building": _deep(record),
                "buildingCount": float(len(player["buildings"])),
                "autoProducings": {},
            },
        )

    def _find_building(
        self, player: dict[str, Any], value: Any
    ) -> tuple[str, dict[str, Any]] | tuple[None, None]:
        building_id = str(value or "")
        if building_id in player["buildings"]:
            return building_id, player["buildings"][building_id]
        for key, record in player["buildings"].items():
            if str(record.get("instanceId")) == building_id:
                return key, record
        return None, None

    def progress_build_task(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/task/progressBuildTask", session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        key, record = self._find_building(player, params.get("buildingId"))
        if record is None:
            return self._failure("politic/task/progressBuildTask", "building not found")
        remaining = max(0, int(record.get("remainedClickCount") or 0) - 1)
        record["remainedClickCount"] = remaining
        self._save(player, player_id)
        return self._success(
            "politic/task/progressBuildTask",
            {
                "buildings": {str(key): _deep(record)},
                "autoProducings": {},
                "producings": {},
                "remainedClickCount": remaining,
                "now": _now(),
            },
        )

    def complete_tasks(
        self, params: dict[str, Any], session: dict[str, Any] | None
    ) -> dict[str, Any]:
        found = self._session_player("politic/task/completeTasks", session)
        if isinstance(found, dict):
            return found
        player_id, player, _dirty = found
        completed: dict[str, Any] = {}
        changed = False
        for value in _parse_ids(params.get("buildingIds")):
            key, record = self._find_building(player, value)
            if record is None or str(record.get("status") or "") != "building":
                continue
            record["status"] = "none"
            record["remainedClickCount"] = 0
            completed[str(key)] = _deep(record)
            changed = True
        if changed:
            self._save(player, player_id)
        return self._success(
            "politic/task/completeTasks",
            {
                "buildings": completed,
                "autoProducings": {},
                "producings": {},
                "buildingCount": float(len(player["buildings"])),
                "kokudaka": float(player.get("kokudaka") or 0),
                "characters": {},
                "equips": {},
                "completeCount": float(len(completed)),
                "errno": 0.0,
                "now": _now(),
            },
        )
