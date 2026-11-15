"""Uninstalled, bounded main-city errantry lifecycle.

No default intelligence/probability engine. A trusted planner must compute the
real deck and select original result rows; tests supply an explicitly synthetic
planner. Only fixed purple-soul/skill-jewel rewards are delivered. First journey
only: send3/receive3 carry no journey nonce, so a completed tombstone prevents a
late replay from starting/claiming a different journey. This is local policy.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import partial
import time
from typing import Any, Callable

from app.business import response_shapes
from app.business.decks import character_id
from app.business.player_services import PlayerServices, integer


STATE_KEY = "economyErrantryV1"
PURPLE = "item11_0001101"
JEWEL = "item07_0070001"


@dataclass(frozen=True)
class TradeMember:
    slot: str
    character_id: str
    intelligence: int
    result_id: str


@dataclass(frozen=True)
class DeparturePlan:
    """Internal planner output, never accepted from RPC parameters.

    total_intelligence includes authoritative effects; it is not inferred by
    summing base card stats. evidence identifies the rule implementation/version.
    """
    members: tuple[TradeMember, ...]
    total_intelligence: int
    evidence: str


def assert_errantry_unlocked(player: dict, *, building_id: str | None = None,
                             politic_deck: bool = False) -> None:
    """Integration guard for A's building writes and shared setDecks path."""
    record = player.get(STATE_KEY)
    if record is None:
        return
    if not isinstance(record, dict) or record.get("phase") not in ("travelling", "received"):
        raise ValueError("no stub response: invalid persisted errantry record")
    if record["phase"] == "travelling" and (politic_deck or record.get("buildingId") == building_id):
        raise ValueError("errantry holds this building/politic deck until receipt")


class EconomyTradeServices(PlayerServices):
    def __init__(self, service: Any, *, planner: Callable[[dict, dict], DeparturePlan] | None = None,
                 deck_provider: Callable[[dict], dict] | None = None,
                 clock: Callable[[], int] | None = None) -> None:
        super().__init__(service)
        self.planner = planner
        self.deck_provider = deck_provider
        self.clock = clock or (lambda: int(time.time()))

    def register(self, registry: Any) -> None:
        for name, action in (("send3", self.send), ("getStatus3", self.status), ("receive3", self.receive)):
            api = "politic/errantry/" + name
            registry.register(api, self.service._guard(api, partial(self.call_trade, api, action)))

    def call_trade(self, api: str, action: Any, params: dict, session: dict | None) -> dict:
        found = self.service._session_player(api, session)
        if isinstance(found, dict):
            return found
        player_id, loaded, _ = found
        player = copy.deepcopy(loaded)
        try:
            if player["entity"].get("created") is not True:
                raise ValueError("created player required")
            payload = action(player, params)
            if player != loaded:
                self.service._save(player, player_id)
            return response_shapes.success(api, copy.deepcopy(payload))
        except ValueError as exc:
            return self.service._failure(api, str(exc))

    def row(self, name: str, key: Any) -> dict:
        if not isinstance(key, str) or not isinstance(self.table(name).get(key), dict):
            raise ValueError(f"no stub response: invalid {name} row reference")
        return self.table(name)[key]

    @staticmethod
    def main_map(params: dict) -> None:
        if integer(params.get("mapId")) != 0:
            raise ValueError("no stub response: only main-map errantry supported")

    @staticmethod
    def deck(player: dict, *, allow_empty: bool = False) -> dict[str, str]:
        deck = player.get("decks", {}).get("politic", {}).get("0", {})
        ids = deck.get("ids")
        if not isinstance(ids, dict):
            raise ValueError("no stub response: missing politic deck")
        result = {}
        for slot, value in ids.items():
            if slot not in ("0", "1", "2", "3", "4"):
                raise ValueError("invalid politic deck slot")
            if value == "empty":
                continue
            key = character_id(value)
            if key not in player.get("characters", {}) or key in result.values():
                raise ValueError("invalid/unowned/duplicate politic deck member")
            result[slot] = key
        if not result and not allow_empty:
            raise ValueError("politic deck is empty")
        return result

    def deck_view(self, player: dict) -> dict:
        """getStatus3 also feeds PoliticDeckTableAccessor (not a separate API)."""
        if self.deck_provider is None:
            raise ValueError("no stub response: authoritative politic deck stats not integrated")
        view = self.deck_provider(copy.deepcopy(player))
        deck = self.deck(player, allow_empty=True)
        if (not isinstance(view, dict) or set(view) != {"politicDeck", "totalIntelligence"}
                or not isinstance(view["politicDeck"], dict) or set(view["politicDeck"]) != set(deck)):
            raise ValueError("no stub response: invalid politic deck projection")
        total = integer(view["totalIntelligence"])
        if not deck and total != 0:
            raise ValueError("invalid empty-deck total intelligence")
        result = {}
        for slot, key in deck.items():
            row, card = view["politicDeck"][slot], player["characters"][key]
            if not isinstance(row, dict) or set(row) != {"int", "intAdd", "baseId", "grade", "voice"}:
                raise ValueError("no stub response: invalid politic member projection")
            for name in ("baseId", "voice"):
                if not isinstance(row[name], str) or not row[name] or row[name] != card.get(name):
                    raise ValueError("politic member identity differs from owned card")
            if integer(row["grade"], 1) != integer(card.get("grade"), 1):
                raise ValueError("politic member grade differs from owned card")
            base = integer(row["int"])
            added = integer(row["intAdd"], -2147483647)
            integer(base + added)
            result[slot] = {**row, "int": base, "intAdd": added, "grade": int(row["grade"])}
        return {"politicDeck": result, "totalIntelligence": total}

    def fixed_rewards(self, result_table: str, result_id: str) -> dict[str, int]:
        selected = self.row(result_table, result_id)
        reward = self.row("reward07_errantry", selected.get("rewardId"))
        groups, amounts = set(), {}
        for i in range(1, 11):
            item = reward.get(f"itemId{i}")
            if item == "none":
                continue
            group = reward.get(f"group{i}")
            low, high = reward.get(f"count{i}min"), reward.get(f"count{i}max")
            if (not isinstance(group, str) or group == "none" or group in groups
                    or reward.get(f"ratio{i}min") != 1 or reward.get(f"ratio{i}max") != 1
                    or low != high):
                raise ValueError("no stub response: non-fixed errantry reward selection")
            groups.add(group)
            if item not in (PURPLE, JEWEL):
                raise ValueError("no stub response: errantry delivery category not implemented")
            item_row = self.row(item[:6], item)
            if item_row.get("enable") is not True:
                raise ValueError("no stub response: disabled errantry reward item")
            amounts[item] = integer(amounts.get(item, 0) + integer(low, 1), 1)
        if not amounts:
            raise ValueError("no stub response: empty errantry reward rule")
        return amounts

    def record(self, player: dict) -> dict | None:
        record = player.get(STATE_KEY)
        if record is None:
            return None
        if (not isinstance(record, dict) or record.get("phase") not in ("travelling", "received")
                or record.get("catalog") != "errantry" or not isinstance(record.get("evidence"), str)
                or not record["evidence"] or not isinstance(record.get("results"), dict)
                or not isinstance(record.get("errantryId"), str)):
            raise ValueError("no stub response: invalid persisted errantry record")
        character_id(record.get("buildingId"))
        created = integer(record.get("createdTime"), maximum=2**53 - 1)
        if integer(record.get("dueTime"), maximum=2**53 - 1) <= created:
            raise ValueError("no stub response: invalid errantry due time")
        if not isinstance(record.get("deck"), dict) or set(record["results"]) != set(record["deck"]):
            raise ValueError("no stub response: invalid errantry result slots")
        if not record["deck"] or any(s not in ("0", "1", "2", "3", "4") for s in record["deck"]):
            raise ValueError("no stub response: invalid errantry stored deck")
        for member in record["deck"].values():
            character_id(member)
        for outcome in record["results"].values():
            if not isinstance(outcome, dict) or not isinstance(outcome.get("resultId"), str):
                raise ValueError("no stub response: invalid errantry outcome")
            rewards = outcome.get("reward")
            if not isinstance(rewards, dict) or not rewards or not set(rewards) <= {PURPLE, JEWEL}:
                raise ValueError("no stub response: invalid persisted errantry reward")
            for amount in rewards.values():
                integer(amount, 1)
        return record

    @staticmethod
    def projection(record: dict) -> dict:
        # UserStatus.TravelCommerce:603-624 requires numeric buildingId.
        return {"isActive": record["phase"] == "travelling", "dueTime": record["dueTime"],
                "errantryId": record["errantryId"], "buildingId": int(record["buildingId"])}

    def status(self, player: dict, params: dict) -> dict:
        record = self.record(player)
        # PoliticMissionProgressList.cs:316-321 / PluginPoliticDataManager:157-162
        # send the SAME response to both UserStatus and PoliticDeckTableAccessor.
        return {"0": {"errantry": self.projection(record) if record else {"isActive": False},
                      **self.deck_view(player)}}

    def send(self, player: dict, params: dict) -> dict:
        self.main_map(params)
        if self.record(player) is not None:
            # Returning success would make the original client subtract costs again.
            raise ValueError("no stub response: errantry already started; subsequent journeys need retry identity")
        if self.planner is None:
            raise ValueError("no stub response: verified errantry intelligence/result planner not integrated")
        if player["entity"].get("currentMapKey") != "map001":
            raise ValueError("main map must be selected")
        building_id = character_id(params.get("buildingId"))
        building = player.get("buildings", {}).get(building_id)
        if (not isinstance(building, dict) or building.get("deployedMapKey") != "map001"
                or building.get("status") not in ("none", "waiting")
                or building_id in player.get("produce", {})):
            raise ValueError("errantry requires an owned idle main-map building")
        kind = building.get("buildingTypeId")
        self.row("building", kind)
        catalogue = self.row("building_errantry", kind).get("map0")
        if catalogue != "errantry":
            raise ValueError("no stub response: regional errantry catalogue unsupported")
        code = params.get("errantryId")
        rule = self.row(catalogue, code)
        if rule.get("costTypes") != ["item11_0000701", "item11_0000101"]:
            raise ValueError("no stub response: unsupported errantry cost types")
        amounts = rule.get("costAmounts")
        if not isinstance(amounts, list) or len(amounts) != 2:
            raise ValueError("no stub response: invalid errantry cost amounts")
        pp, gold = (integer(n, 1) for n in amounts)
        points, money = player["actionPoints"]["politicPoint"], player["resources"]["gold"]
        if integer(points["point"]) < pp or integer(money["amount"]) < gold:
            raise ValueError("insufficient errantry points/gold")
        deck = self.deck(player)
        view = self.deck_view(player)
        plan = self.planner(copy.deepcopy(player), copy.deepcopy(rule))
        if (not isinstance(plan, DeparturePlan) or not isinstance(plan.members, tuple)
                or not isinstance(plan.evidence, str) or not plan.evidence
                or any(not isinstance(m, TradeMember) for m in plan.members)):
            raise ValueError("no stub response: invalid errantry planner output")
        if integer(plan.total_intelligence) < integer(rule.get("leastTotalIntelligence")):
            raise ValueError("insufficient total errantry intelligence")
        if plan.total_intelligence != view["totalIntelligence"]:
            raise ValueError("planner total differs from authoritative deck projection")
        if (len(plan.members) != len(deck)
                or {m.slot: m.character_id for m in plan.members} != deck):
            raise ValueError("no stub response: planner deck differs from owned politic deck")
        results = {}
        for member in plan.members:
            projected = view["politicDeck"][member.slot]
            if integer(member.intelligence) != projected["int"] + projected["intAdd"]:
                raise ValueError("planner member intelligence differs from deck projection")
            results[member.slot] = {"resultId": member.result_id,
                                    "reward": self.fixed_rewards(rule.get("result"), member.result_id)}
        now = integer(self.clock(), maximum=2**53 - 1)
        due = integer(now + integer(rule.get("dueInterval"), 1), maximum=2**53 - 1)
        record = {"phase": "travelling", "catalog": catalogue, "errantryId": code,
                  "buildingId": building_id, "createdTime": now, "dueTime": due,
                  "deck": deck, "results": results, "evidence": plan.evidence,
                  "totalIntelligence": plan.total_intelligence, "costs": {"PP": pp, "gold": gold}}
        # Preflight all rule/plan validation before the first mutation. The call
        # wrapper saves the record and both debits in the same CAS operation.
        points["point"] -= pp
        money["amount"] -= gold
        player[STATE_KEY] = record
        return self.projection(record)

    def receive(self, player: dict, params: dict) -> dict:
        self.main_map(params)
        record = self.record(player)
        if record is None or record["phase"] != "travelling":
            raise ValueError("no unreceived errantry journey")
        if integer(self.clock(), maximum=2**53 - 1) < record["dueTime"]:
            raise ValueError("errantry is not due")
        if self.deck(player) != record["deck"]:
            raise ValueError("no stub response: politic deck changed during errantry")
        totals = {PURPLE: 0, JEWEL: 0}
        for outcome in record["results"].values():
            for item, amount in outcome["reward"].items():
                totals[item] = integer(totals[item] + integer(amount, 1))
        soul = integer(player.get("souls", {}).get("purple", 0)) + totals[PURPLE]
        limit = integer(self.row("defines", "soul_limit").get("value"), 1)
        if soul > limit:
            raise ValueError("no stub response: errantry soul overflow delivery unsupported")
        jewel = integer(integer(player.get("items", {}).get(JEWEL, 0)) + totals[JEWEL])
        count = integer(integer(player.get("counters", {}).get("errantryTimes", 0)) + 1)
        player.setdefault("souls", {})["purple"] = soul
        player.setdefault("items", {})[JEWEL] = jewel
        player.setdefault("counters", {})["errantryTimes"] = count
        record["phase"] = "received"
        record["receivedTime"] = integer(self.clock(), maximum=2**53 - 1)
        # No extra resources/counters fields: original consumers add reward/count.
        return {"catalog": record["catalog"], "errantryId": record["errantryId"],
                "results": copy.deepcopy(record["results"])}
