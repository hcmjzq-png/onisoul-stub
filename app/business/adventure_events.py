"""Table-driven, bounded story producer: tutorial steps 1..5, no combat solver.

StepIntent is an INTERNAL transport contract, not an original request field.
The original client sends neither a nonce nor the expected step. Consequently
executeQuestEx is deliberately NOT registered by this module. An adapter must
retain one intent across retries and issue a new one only for a new user action.
Never derive it from the current save, time, a random ID per HTTP arrival, or a
hash of the original parameters (which are identical for successive steps).

Grade-1 reward initialization and once-only tutorial access are explicit local
compatibility policies. See research-331/results/b-adventure/integration-notes.md.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import partial
import hashlib
import json
import time
from typing import Any

from app.business import response_shapes
from app.business.adventure_obstacle_services import displayed_cost, section_at
from app.business.adventure_services import AdventureServices, mapping
from app.business.player_services import integer


PRODUCER = "research331-story-prefix-v1"
QUEST = "quest_1_0000"
TUTORIAL_BATTLE_POLICY = "qa-tutorial-first-turn-v1"


@dataclass(frozen=True)
class StepIntent:
    player_id: str
    operation_id: str
    expected_step: int


class AdventureEvents(AdventureServices):
    """Uses the existing player lock and single-save revision/CAS boundary."""

    def register(self, registry: Any, *, apis: frozenset[str] | None = None) -> None:
        super().register(registry, apis=apis)
        for name, action in {"openQuest": self.open_story,
                             "getQuestEncount": self.encounters}.items():
            api = "quest/" + name
            if apis is None or api in apis:
                registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def call(self, api: str, action: Any, params: dict, session: dict | None) -> dict:
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, original, dirty = found
        staged = copy.deepcopy(original)
        try:
            payload = action(staged, params)
        except ValueError as exc:
            # Do not replay placeholder reward/event structures on failure.
            return response_shapes.success(api, {"succeeded": False, "errorReason": str(exc)})
        if dirty or staged != original:
            self.service._save(staged, player_id)
        return response_shapes.success(api, copy.deepcopy(payload))

    def open_story(self, player: dict, params: dict) -> dict:
        if self.quest_type(params) != "story":
            raise ValueError("no stub response: event/random schedules are not authorized")
        if not mapping(player.get("entity")).get("created"):
            raise ValueError("created player required")
        if "adventureV1" in player:
            self.lifecycle(player)  # no migration/reset of existing or imported histories
            return {"addWork": False}
        row = self.index_row("story", 0, 1)
        if row.get("areaCount") != 1 or row.get("areaStep1") != 10 or row.get("raidBossEncountId") != "none":
            raise ValueError("no stub response: unsupported tutorial index")
        first = self.table(QUEST).get("1_1_1")
        if not isinstance(first, dict):
            raise ValueError("no stub response: missing tutorial section reference")
        items = {str(i): 0 for i in range(1, 5) if first.get(f"item{i}") not in (None, "", "none")}
        location = {"quest": 0, "chapter": 1, "area": 1, "step": 0}
        player["adventureV1"] = {
            "version": 1, "progress": {"story": {"last": dict(location), "current": dict(location)}},
            "quests": {QUEST: {
                "completeFlags": {f"chapter{i}": 0 for i in range(1, 6)},
                "rewardOpenFlags": {f"chapter{i}": False for i in range(1, 6)},
                "chapters": {"1": {"complete": 0, "clearCount": 0,
                                     "areas": {"1": {"complete": 0, "step": 0, "items": items}}}}}},
            "storyLifecycle": {"producer": PRODUCER, "events": {}, "receipts": {}}}
        return {"addWork": True}

    def lifecycle(self, player: dict) -> dict:
        saved = self.snapshot(player)
        life = mapping(saved.get("storyLifecycle"))
        if life.get("producer") != PRODUCER:
            raise ValueError("no stub response: story history needs explicit migration")
        mapping(life.get("events"))
        mapping(life.get("receipts"))
        # Also validate all existing projection fields; malformed records never
        # become a new tutorial or receive a second first-time reward.
        super().progress(player, {})
        chapter = super().chapter(player, {"questType": "story", "questId": 0, "chapterId": 1})
        reward_flags = super().reward_flags(player, {"questType": "story", "questId": 0})
        current = mapping(mapping(saved["progress"]["story"]).get("current"))
        step = integer(current.get("step"), 0, 5)
        if (current != {"quest": 0, "chapter": 1, "area": 1, "step": step}
                or saved["progress"]["story"]["last"] != current
                or set(life["events"]) != {str(i) for i in range(1, step + 1)}
                or len(life["receipts"]) != step or chapter["area1"]["step"] != step
                or chapter["complete"] != 0 or chapter["clearCount"] != 0 or chapter["area1"]["complete"] != 0
                or any(saved["quests"][QUEST]["completeFlags"].values()) or any(reward_flags.values())):
            raise ValueError("no stub response: inconsistent story event ledger")
        for key, event in life["events"].items():
            event = mapping(event)
            settlement = event.get("battle")
            terminal = key == "5" and isinstance(settlement, dict)
            if terminal and (settlement.get("policy") != TUTORIAL_BATTLE_POLICY
                             or settlement.get("encountId") != 5 or settlement.get("winner") != "attacker"
                             or settlement.get("originOperationId") != event.get("operationId")):
                raise ValueError("no stub response: inconsistent tutorial battle receipt")
            if (event.get("step") != int(key) or not isinstance(event.get("operationId"), str)
                    or life["receipts"].get(event["operationId"]) != int(key)
                    or event.get("status") != ("pending" if key == "5" and not terminal else "resolved")):
                raise ValueError("no stub response: inconsistent story event receipt")
        return life

    def progress(self, player: dict, params: dict) -> dict:
        self.lifecycle(player)
        return super().progress(player, params)

    def chapter(self, player: dict, params: dict) -> dict:
        self.lifecycle(player)
        return super().chapter(player, params)

    def complete_flags(self, player: dict, params: dict) -> dict:
        self.lifecycle(player)
        return super().complete_flags(player, params)

    def reward_flags(self, player: dict, params: dict) -> dict:
        self.lifecycle(player)
        return super().reward_flags(player, params)

    def execute_trusted(self, params: dict, session: dict | None, intent: StepIntent | None) -> dict:
        """Internal integration entry, intentionally not a Registry handler."""
        api = "quest/executeQuestEx"

        def action(player: dict, request: dict) -> dict:
            if (not isinstance(intent, StepIntent) or not intent.player_id
                    or intent.player_id != self.service._player_id(session)):
                raise ValueError("no stub response: authenticated stable step intent required")
            return self.step(player, request, intent)

        return self.service._guard(api, partial(self.call, api, action))(params, session)

    def step(self, player: dict, params: dict, intent: StepIntent) -> dict:
        if (self.quest_type(params) != "story" or integer(params.get("questId")) != 0
                or integer(params.get("chapterId"), 1) != 1 or integer(params.get("areaId"), 1) != 1
                or params.get("assets") != "map0"):
            raise ValueError("no stub response: only story tutorial prefix is supported")
        if not isinstance(intent.operation_id, str) or not 1 <= len(intent.operation_id) <= 128:
            raise ValueError("no stub response: invalid stable operation identity")
        expected = integer(intent.expected_step, 0, 4)
        life = self.lifecycle(player)
        if intent.operation_id in life["receipts"]:
            # RewardProcessor / PluginQuestStepHelper add rewards on each callback.
            # Even a lost first response must recover by authoritative reads.
            raise ValueError("no stub response: step already committed; reload authoritative state")
        saved = self.snapshot(player)
        progress = saved["progress"]["story"]
        location = {"quest": 0, "chapter": 1, "area": 1, "step": expected}
        if progress["last"] != location or progress["current"] != location:
            raise ValueError("no stub response: stale story step intent")
        area = saved["quests"][QUEST]["chapters"]["1"]["areas"]["1"]
        if area["step"] != expected or area["complete"] != 0:
            raise ValueError("no stub response: inconsistent tutorial state")
        if set(life["events"]) != {str(i) for i in range(1, expected + 1)}:
            raise ValueError("no stub response: missing committed step history")
        if any(event.get("status") != "resolved" for event in life["events"].values()):
            raise ValueError("no stub response: unresolved encounter blocks progression")
        self.index_row("story", 0, 1)
        rows = self.table(QUEST)
        section, _ = section_at(rows, 1, 1, expected)
        source = rows[f"1_1_{section}"]
        if section != expected + 1 or source.get("stepCount") != 1:
            raise ValueError("no stub response: unsupported tutorial section")
        candidates = []
        for slot in range(1, 16):
            event = source.get(f"event{slot}", [0])
            if not isinstance(event, list) or not event:
                raise ValueError("no stub response: invalid event row")
            if integer(event[0]) > 0:
                candidates.append((slot, event))
        if len(candidates) != 1 or candidates[0][1][0] != 100 or len(candidates[0][1]) != 7:
            raise ValueError("no stub response: probabilistic encounters unsupported")
        slot, event = candidates[0]
        event_type = integer(event[1])
        if event_type != (1, 1, 3, 2, 6)[expected] or event[5:] != ["none", "none"]:
            raise ValueError("no stub response: unsupported tutorial event")
        cost = displayed_cost(rows, 1, 1, section)
        if cost < 0:
            raise ValueError("no stub response: unknown mission-point cost")
        points = mapping(mapping(player.get("actionPoints")).get("missionPoint"))
        balance = integer(points.get("point"))
        if balance < cost:
            raise ValueError("no stub response: insufficient mission points")
        reward: dict[str, int] = {}
        event_info = {"eventType": float(event_type), "eventScript": event[2]}
        if not isinstance(event[2], str) or not event[2] or event[2] == "none":
            raise ValueError("no stub response: missing tutorial script reference")
        encounter = None
        if event_type == 1:
            if event[3:5] != ["none", "none"]:
                raise ValueError("no stub response: unsupported story disposition")
        elif event_type in (2, 3):
            if event[4] != "none":
                raise ValueError("no stub response: unexpected direct reward parameter")
            reward = self.direct_reward(event[3], event_type)
        else:
            # Original monster table carries presentation/maxHp, not damage rules.
            monster = self.table("monster_story_1").get(event[3])
            if event[3] != "q_mons_0000_01" or not isinstance(monster, dict):
                raise ValueError("no stub response: unsupported monster reference")
            integer(monster.get("maxHp"), 1)
            reward_row = self.table(QUEST + "_reward").get(event[4])
            if not isinstance(reward_row, dict):
                raise ValueError("no stub response: missing battle reward reference")
            encounter = {"encountId": expected + 1, "monsterId": event[3],
                         "monster": copy.deepcopy(monster), "winRewardId": event[4],
                         "lossRewardId": event[5], "overKillRewardId": event[6]}
            event_info["encountInfo"] = {"encountId": float(expected + 1), "monsterId": event[3]}
        # Stage all changes so validation failures leave even direct callers intact.
        staged = copy.deepcopy(player)
        grants = self.grant_direct(staged, reward)
        next_step = expected + 1
        staged["actionPoints"]["missionPoint"]["point"] = balance - cost
        record = staged["adventureV1"]
        for key in ("last", "current"):
            record["progress"]["story"][key]["step"] = next_step
        next_area = record["quests"][QUEST]["chapters"]["1"]["areas"]["1"]
        next_area["step"] = next_step
        for item_slot in next_area["items"]:
            if rows["1_1_1"].get(f"item{item_slot}") in reward:
                next_area["items"][item_slot] = 1
        now = int(time.time())
        payload = {"executeInfo": {"step": float(next_step), "missionPoint": float(balance - cost),
                                   "now": float(now)}, "eventInfo": event_info,
                   "rewardInfo": {key: float(value) for key, value in reward.items()}, "bonusInfo": {}}
        history = record["storyLifecycle"]
        history["events"][str(next_step)] = {
            "operationId": intent.operation_id, "step": next_step, "section": section, "eventSlot": slot,
            "sourceDigest": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
            "cost": cost, "reward": reward, "grants": grants, "encounter": encounter,
            "status": "pending" if encounter else "resolved", "createdAt": now,
            "response": copy.deepcopy(payload)}
        history["receipts"][intent.operation_id] = next_step
        player.clear()
        player.update(staged)
        return payload

    def direct_reward(self, reward_id: str, event_type: int) -> dict[str, int]:
        supported = {"quest_1_0000_03_002": (3, "item01_0032401"),
                     "quest_1_0000_03_003": (2, "item08_0102701")}
        if reward_id not in supported or supported[reward_id][0] != event_type:
            raise ValueError("no stub response: direct reward outside verified prefix")
        row = self.table(QUEST + "_reward").get(reward_id)
        if not isinstance(row, dict):
            raise ValueError("no stub response: missing direct reward row")
        if any(row.get(f"itemId{i}") not in ("", "none", 0) for i in range(2, 11)):
            raise ValueError("no stub response: multi-outcome reward unsupported")
        item = supported[reward_id][1]
        if (row.get("group1") != "A" or row.get("itemId1") != item
                or row.get("ratio1min") != 10 or row.get("ratio1max") != 10
                or row.get("count1min") != 1 or row.get("count1max") != 1):
            raise ValueError("no stub response: unsupported tutorial reward distribution")
        # One positive candidate in the sole group: no random count/minimum shortcut.
        return {item: integer(row["count1min"], 1)}

    def grant_direct(self, player: dict, reward: dict[str, int]) -> dict:
        grants = {}
        for item, count in reward.items():
            if item == "item08_0102701":
                row = self.table("item08").get(item)
                if not isinstance(row, dict) or row.get("enable") is not True or row.get("category") != "jewel":
                    raise ValueError("no stub response: invalid jewel reference")
                inventory = mapping(player.get("items"))
                inventory[item] = integer(integer(inventory.get(item, 0)) + count)
            elif item == "item01_0032401":
                item_row = self.table("item01").get(item)
                if (not isinstance(item_row, dict) or item_row.get("enable") is not True
                        or item_row.get("category") != "character"):
                    raise ValueError("no stub response: invalid tutorial character item")
                base = item_row.get("parameterId")
                source = self.table("character").get(base)
                if (not isinstance(source, dict) or source.get("id") != base
                        or not isinstance(source.get("voice"), str)):
                    raise ValueError("no stub response: missing tutorial character reference")
                owned, stored = mapping(player.get("characters")), mapping(player.get("storedCharacters", {}))
                if len(owned) + count > integer(self.service._possession_limits(player)["character"]["result"]):
                    raise ValueError("no stub response: character overflow/inbox unsupported")
                ids = set(owned) | set(stored)
                if any(not isinstance(key, str) or not key.isascii() or not key.isdecimal() for key in ids):
                    raise ValueError("no stub response: invalid saved character identity")
                instance = str(integer(max((int(key) for key in ids), default=0) + 1, 1))
                # Same bounded grade-1 schema as GameplayService._initial_characters.
                # No skill lottery or stat growth is inferred from the reward row.
                owned[instance] = {**{key: float(integer(source.get(key))) for key in ("atk", "def", "int")},
                                   "atkAdd": 0.0, "defAdd": 0.0, "intAdd": 0.0,
                                   "grade": 1.0, "level": 1.0, "baseId": base, "exp": 0.0,
                                   "combinedPoint": 0.0, "purchasedVoiceId": "",
                                   "voice": source["voice"], "skills": {}}
                mapping(player.get("counters"))["characterCount"] = len(owned)
                grants[item] = {"characterId": instance}
            else:
                raise ValueError("no stub response: unsupported tutorial grant")
        return grants

    def encounters(self, player: dict, params: dict) -> dict:
        life = self.lifecycle(player)
        pending = [row for row in life["events"].values() if row.get("status") == "pending"]
        if not pending:
            return {}
        if len(pending) != 1 or not isinstance(pending[0].get("encounter"), dict):
            raise ValueError("no stub response: inconsistent pending encounter")
        event = pending[0]
        last = self.snapshot(player)["progress"]["story"]["last"]
        if last != {"quest": 0, "chapter": 1, "area": 1, "step": event["step"]}:
            raise ValueError("no stub response: encounter location mismatch")
        return {"story": {"questId": QUEST, "chapter": 1.0, "area": 1.0, "step": float(event["step"])}}
