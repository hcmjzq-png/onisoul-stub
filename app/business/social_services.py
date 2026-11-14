"""Limited original-client friend lifecycle; deliberately NOT mounted in production.

Sources and unsupported expiry/HTML rules: docs/analysis/parallel-342/e-social/.
Cross-player writes require an atomic adapter for the SAME player store. Never
implement that adapter by calling GameplayService._save twice. The adapter must
lock/revision-check both rows, roll back on exceptions and commit both or neither.
friends (accepted IDs -> {}) and socialOffers (ID -> status/createdAt) are internal
storage decisions, not original response records. No mail, gifts or visit rewards.
"""
from __future__ import annotations

import copy
import time
from contextlib import ExitStack
from functools import partial
from typing import Any, Callable, ContextManager, Protocol

from app import state
from app.business import response_shapes
from app.business.decks import character_id
from app.business.player_services import PlayerServices


class AtomicPlayers(Protocol):
    def __call__(self, player_ids: tuple[str, ...]) -> ContextManager[dict[str, dict]]:
        """Yield isolated existing player rows; atomically commit on normal exit."""
        ...


class SocialServices(PlayerServices):
    MUTATIONS = ("sendFriendOffer", "feedbackFriendOffer", "cancelFriendOffer", "dissolutionFriend")

    def __init__(self, service: Any, *, atomic_players: AtomicPlayers | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        self.atomic_players = atomic_players
        self.clock = clock

    def register(self, registry: Any) -> None:
        for name, action in (("getFriends", self.friends), ("updateFriendData", self.counts),
                             ("getFriendProfile", self.friend_profile)):
            api = "friend/" + name
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))
        for name in self.MUTATIONS:
            # Do not acquire actor lock before the pair's ordered locks: deadlock.
            registry.register("friend/" + name, partial(self.mutate, name))

    @staticmethod
    def require_player(player: dict) -> None:
        if not (player.get("entity") or {}).get("created"):
            raise ValueError("created player required")

    @staticmethod
    def target_id(params: dict) -> str:
        value = params.get("friendPlayerId")
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError("friendPlayerId must be a nonempty string")
        return value

    def offers(self, player: dict) -> dict:
        offers = player.get("socialOffers") or {}
        if offers:
            row = self.table("defines").get("friendoffer_expire_time")
            if not row or "value" not in row:
                raise ValueError("no stub response: missing friend expiry table row")
            for offer in offers.values():
                if (offer.get("status") not in ("send", "receive")
                        or not isinstance(offer.get("createdAt"), (int, float))):
                    raise ValueError("no stub response: social offer migration required")
                # Original cleanup timing/removal reason is not established. Fail
                # closed instead of granting a stale offer or inventing cleanup.
                if self.clock() - offer["createdAt"] >= row["value"]:
                    raise ValueError("no stub response: expired friend offer cleanup is not implemented")
        return offers

    def relation(self, player: dict, target: str) -> str:
        if target in (player.get("friends") or {}):
            return "ok"
        return self.offers(player).get(target, {}).get("status", "")

    def counts(self, player: dict, params: dict) -> dict:
        self.require_player(player)
        offers = self.offers(player)
        return {"count": {"ok": float(len(player.get("friends") or {})),
                          **{s: float(sum(o["status"] == s for o in offers.values()))
                             for s in ("send", "receive")}}, "remove": {}}

    def summary(self, player: dict, status: str) -> dict:
        self.require_player(player)
        entity = player["entity"]
        avatar = (player.get("decks") or {}).get("avatar") or {}
        card = (player.get("characters") or {}).get(character_id(avatar.get("id")))
        if not card or "baseId" not in card or "grade" not in card:
            raise ValueError("no stub response: saved avatar is unavailable")
        return {"name": entity["username"], "country": entity["country"],
                "level": float(entity["level"]), "baseId": card["baseId"],
                "grade": float(avatar.get("grade", card["grade"])), "status": status}

    def friends(self, player: dict, params: dict) -> dict:
        self.require_player(player)
        option = params.get("option")
        if option not in ("", "ok", "send", "receive"):
            raise ValueError("unsupported friend option")
        relations = {key: value["status"] for key, value in self.offers(player).items()}
        relations.update({key: "ok" for key in (player.get("friends") or {})})
        return {key: self.summary(self.service.load_state(key), status)
                for key, status in sorted(relations.items()) if option in ("", status)}

    def friend_profile(self, player: dict, params: dict) -> dict:
        self.require_player(player)
        if params.get("forHTML") is not False:
            raise ValueError("no stub response: HTML profile presentation is not implemented")
        target = self.target_id(params)
        other = self.service.load_state(target)
        result = self.summary(other, self.relation(player, target))
        intro = other.get("selfIntroduction") or {}
        result.update({"username": other["entity"]["username"],
                       "friendCount": float(len(other.get("friends") or {})),
                       "guildName": str(other.get("guildName") or ""),
                       "post": str(other.get("post") or ""),
                       "lastLogin": float(other.get("lastLogin") or 0),
                       "rank": str(other.get("countryRankId") or ""),
                       "kokudaka": float(other.get("kokudaka") or 0),
                       "selfIntroduction": {"message": intro.get("message", ""),
                           "habits": copy.deepcopy(intro.get("habits") or
                               {"0": "none", "1": "none", "2": "none"})}})
        return result

    def limit(self, player: dict) -> int:
        row = self.table("playerLevel").get(str(player["entity"]["level"]))
        if not row or "friend" not in row:
            raise ValueError("no stub response: missing playerLevel friend row")
        return int(row["friend"])

    def offer_limit(self, kind: str) -> int:
        row = self.table("defines").get("friendoffer_" + kind + "_max")
        if not row or "value" not in row:
            raise ValueError("no stub response: missing friend offer limit row")
        return int(row["value"])

    def mutate(self, name: str, params: dict, session: dict | None) -> dict:
        api = "friend/" + name
        actor = self.service._player_id(session)
        try:
            if not actor:
                raise ValueError("authentication required")
            target = self.target_id(params)
            if actor == target:
                raise ValueError("cannot change friendship with self")
            if self.atomic_players is None:
                raise ValueError("no stub response: atomic player storage adapter required")
            ids = tuple(sorted((actor, target)))
            with ExitStack() as stack:
                for player_id in ids:
                    stack.enter_context(self.service._lock_for(player_id))
                rows = stack.enter_context(self.atomic_players(ids))
                left, right = rows.get(actor, {}), rows.get(target, {})
                self.require_player(left)
                self.require_player(right)
                self.transition(name, params, actor, target, left, right)
            return response_shapes.success(api, {"result": True})
        except (ValueError, state.StateConflictError) as exc:
            # FriendConfirmationWindow restores its optimistic counter on result=false.
            # detail[0] is a native failure field; free text is our diagnostic policy.
            return response_shapes.success(api, {"result": False, "detail": {"0": str(exc)}})

    def transition(self, name: str, params: dict, actor: str, target: str,
                   left: dict, right: dict) -> None:
        lo, ro = self.offers(left), self.offers(right)
        a, b = self.relation(left, target), self.relation(right, actor)
        if (a, b) not in (("", ""), ("send", "receive"), ("receive", "send"), ("ok", "ok")):
            raise ValueError("no stub response: inconsistent friend relationship requires repair")
        if name == "sendFriendOffer":
            if a in ("send", "ok"):
                return  # Retry policy: no duplicate entry or timestamp refresh.
            if a:
                raise ValueError("incoming offer must be explicitly accepted")
            if any(len(p.get("friends") or {}) >= self.limit(p) for p in (left, right)):
                raise ValueError("friend capacity reached")
            if sum(o["status"] == "send" for o in lo.values()) >= self.offer_limit("send"):
                raise ValueError("already reached send count")
            if sum(o["status"] == "receive" for o in ro.values()) >= self.offer_limit("receive"):
                raise ValueError("already reached receive count")
            timestamp = float(self.clock())
            left.setdefault("socialOffers", {})[target] = {"status": "send", "createdAt": timestamp}
            right.setdefault("socialOffers", {})[actor] = {"status": "receive", "createdAt": timestamp}
            return
        if name == "feedbackFriendOffer":
            reply = params.get("reply")
            if reply not in ("ok", "excuse"):
                raise ValueError("reply must be ok or excuse")
            if reply == "ok" and a == "ok":
                return
            if a != "receive":
                raise ValueError("incoming offer required")
            if reply == "ok":
                if any(len(p.get("friends") or {}) >= self.limit(p) for p in (left, right)):
                    raise ValueError("friend capacity reached")
                left.setdefault("friends", {})[target] = {}
                right.setdefault("friends", {})[actor] = {}
        elif name == "cancelFriendOffer":
            if not a:
                return
            if a != "send":
                raise ValueError("outgoing offer required")
        elif name == "dissolutionFriend":
            if not a:
                return
            if a != "ok":
                raise ValueError("accepted friendship required")
            left["friends"].pop(target)
            right["friends"].pop(actor)
        else:
            raise ValueError("unsupported friend transition")
        left.get("socialOffers", {}).pop(target, None)
        right.get("socialOffers", {}).pop(actor, None)
