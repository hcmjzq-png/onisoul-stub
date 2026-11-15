"""Original-client friend lifecycle; registration is an integration opt-in.

Evidence/policies: docs/analysis/research-331/results/e-social/.
Cross-player writes require an atomic adapter for the SAME player store. Never
implement that adapter by calling GameplayService._save twice. The adapter must
lock/revision-check both rows, roll back on exceptions and commit both or neither.
friends (accepted IDs -> {}) and socialOffers (ID -> status/createdAt) are internal
storage decisions, not original response records. No mail, gifts or visit rewards.
"""
from __future__ import annotations

import copy
import math
import time
from contextlib import ExitStack
from functools import partial
from typing import Any, Callable, ContextManager, Protocol

from app import state
from app.business import response_shapes
from app.business.decks import character_id
from app.business.player_services import PlayerServices, integer


class AtomicPlayers(Protocol):
    def __call__(self, player_ids: tuple[str, ...]) -> ContextManager[dict[str, dict]]:
        """Yield isolated existing player rows; atomically commit on normal exit."""
        ...


class _ChangedScope(Exception):
    """Discovery raced another transaction; release all locks and rediscover."""


class SocialServices(PlayerServices):
    MUTATIONS = ("sendFriendOffer", "feedbackFriendOffer", "cancelFriendOffer", "dissolutionFriend")

    def __init__(self, service: Any, *, atomic_players: AtomicPlayers | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        self.atomic_players = atomic_players
        self.clock = clock

    def register(self, registry: Any) -> None:
        for name in ("getFriends", "updateFriendData", "getFriendProfile"):
            # Reads may expire a pair: never enter a single actor lock first.
            registry.register("friend/" + name, partial(self.read, name))
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
        offers = player.get("socialOffers", {})
        if not isinstance(offers, dict):
            raise ValueError("no stub response: social offer migration required")
        if offers:
            row = self.table("defines").get("friendoffer_expire_time")
            if not row or "value" not in row:
                raise ValueError("no stub response: missing friend expiry table row")
            integer(row["value"], 1)
            now = self.clock()
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                raise ValueError("no stub response: invalid social clock")
            for offer in offers.values():
                if (not isinstance(offer, dict) or offer.get("status") not in ("send", "receive")
                        or type(offer.get("createdAt")) not in (int, float)
                        or not math.isfinite(offer["createdAt"])
                        or not 0 <= offer["createdAt"] <= now):
                    raise ValueError("no stub response: social offer migration required")
        return offers

    @staticmethod
    def accepted(player: dict) -> dict:
        value = player.get("friends", {})
        if (not isinstance(value, dict) or any(not isinstance(k, str) or not k
                or not isinstance(v, dict) for k, v in value.items())):
            raise ValueError("no stub response: friend migration required")
        return value

    @staticmethod
    def removals(player: dict) -> dict:
        value = player.get("socialRemovals", {})
        if (not isinstance(value, dict) or any(not isinstance(k, str) or not k
                or v not in ("expired", "rejected", "cancelled", "dissolved")
                for k, v in value.items())):
            raise ValueError("no stub response: removal notice migration required")
        return value

    def related_ids(self, player: dict) -> set[str]:
        self.require_player(player)
        offers = self.offers(player)
        friends = self.accepted(player)
        self.removals(player)
        if (any(not isinstance(k, str) or not k or k.strip() != k for k in offers)
                or offers.keys() & friends.keys()):
            raise ValueError("no stub response: overlapping or invalid friend records")
        return set(offers) | set(friends)

    def pair_status(self, actor: str, target: str, left: dict, right: dict) -> str:
        """A may call inside its SAME transaction; this is not a visit permit."""
        self.require_player(left)
        self.require_player(right)
        lo, ro = self.offers(left), self.offers(right)
        if (self.accepted(left).keys() & lo.keys()
                or self.accepted(right).keys() & ro.keys()):
            raise ValueError("no stub response: overlapping friend records")
        a, b = self.relation(left, target), self.relation(right, actor)
        if actor == target or (a, b) not in (("", ""), ("send", "receive"),
                                              ("receive", "send"), ("ok", "ok")):
            raise ValueError("no stub response: inconsistent friend relationship requires repair")
        if a in ("send", "receive") and lo[target]["createdAt"] != ro[actor]["createdAt"]:
            raise ValueError("no stub response: friend offer timestamps require repair")
        return a

    def expire(self, seeds: tuple[str, ...], rows: dict[str, dict]) -> set[tuple[str, str]]:
        """Lazy, bilateral expiry at >= lifetime is an explicit local policy."""
        expired = set()
        now = self.clock()
        for actor in seeds:
            left = rows[actor]
            for target in self.related_ids(left):
                self.pair_status(actor, target, left, rows[target])
            offers = self.offers(left)
            lifetime = (integer(self.table("defines")["friendoffer_expire_time"]["value"], 1)
                        if offers else 0)
            for target, offer in list(offers.items()):
                if now - offer["createdAt"] >= lifetime:
                    right = rows[target]
                    del left["socialOffers"][target]
                    del right["socialOffers"][actor]
                    left.setdefault("socialRemovals", {})[target] = "expired"
                    right.setdefault("socialRemovals", {})[actor] = "expired"
                    expired.update(((actor, target), (target, actor)))
        return expired

    def transact(self, seeds: tuple[str, ...], action: Callable[..., dict]) -> dict:
        if self.atomic_players is None:
            raise ValueError("no stub response: atomic player storage adapter required")
        seeds = tuple(sorted(set(seeds)))
        for _ in range(4):
            ids = set(seeds)
            for key in seeds:
                ids.update(self.related_ids(self.service.load_state(key)))
            try:
                with ExitStack() as stack:
                    for key in sorted(ids):
                        stack.enter_context(self.service._lock_for(key))
                    rows = stack.enter_context(self.atomic_players(tuple(sorted(ids))))
                    for key in seeds:
                        if not self.related_ids(rows[key]) <= ids:
                            raise _ChangedScope()
                    expired = self.expire(seeds, rows)
                    payload = action(rows, expired)
                # Only publish after the storage context committed all rows.
                return copy.deepcopy(payload)
            except _ChangedScope:
                continue
        raise state.StateConflictError("social lock scope changed; retry")

    def read(self, name: str, params: dict, session: dict | None) -> dict:
        api = "friend/" + name
        actor = self.service._player_id(session)
        try:
            if not actor:
                raise ValueError("authentication required")
            target = self.target_id(params) if name == "getFriendProfile" else None

            def action(rows: dict, expired: set) -> dict:
                player = rows[actor]
                if name == "getFriends":
                    result = self.friends(player, params, rows=rows)
                    # A fresh list supersedes stale UI references. Notices are
                    # otherwise durable; updateFriendData never consumes them.
                    if player.get("socialRemovals"):
                        player["socialRemovals"] = {}
                    return result
                if name == "getFriendProfile":
                    result = self.friend_profile(player, params, rows=rows)
                    player.get("socialRemovals", {}).pop(target, None)
                    return result
                return self.counts(player, params)

            payload = self.transact((actor, target) if target else (actor,), action)
            return response_shapes.success(api, payload)
        except (ValueError, state.StateConflictError) as exc:
            return self.service._failure(api, str(exc))

    def notifications(self, session: dict | None) -> dict:
        """Absolute counters for periodicInquiry; do not invent unreadMail."""
        from app.business.social_inbox_services import SocialInboxServices

        actor = self.service._player_id(session)
        if not actor:
            return {}

        def action(rows: dict, expired: set) -> dict:
            player = rows[actor]
            return {"friendOffer": self.counts(player, {})["count"]["receive"],
                    "inboxParcel": float(len(SocialInboxServices.ledger(player)["pending"]))}

        return self.transact((actor,), action)

    def relation(self, player: dict, target: str) -> str:
        if target in (player.get("friends") or {}):
            return "ok"
        return self.offers(player).get(target, {}).get("status", "")

    def counts(self, player: dict, params: dict) -> dict:
        self.require_player(player)
        offers = self.offers(player)
        return {"count": {"ok": float(len(player.get("friends") or {})),
                          **{s: float(sum(o["status"] == s for o in offers.values()))
                             for s in ("send", "receive")}},
                "remove": copy.deepcopy(self.removals(player))}

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

    def friends(self, player: dict, params: dict, *, rows: dict | None = None) -> dict:
        self.require_player(player)
        option = params.get("option")
        if option not in ("", "ok", "send", "receive"):
            raise ValueError("unsupported friend option")
        relations = {key: value["status"] for key, value in self.offers(player).items()}
        relations.update({key: "ok" for key in (player.get("friends") or {})})
        return {key: self.summary(rows[key] if rows is not None else self.service.load_state(key), status)
                for key, status in sorted(relations.items()) if option in ("", status)}

    def friend_profile(self, player: dict, params: dict, *, rows: dict | None = None) -> dict:
        self.require_player(player)
        if params.get("forHTML") is not False:
            raise ValueError("no stub response: HTML profile presentation is not implemented")
        target = self.target_id(params)
        other = rows[target] if rows is not None else self.service.load_state(target)
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
            def action(rows: dict, expired: set) -> dict:
                left, right = rows[actor], rows[target]
                if name == "feedbackFriendOffer" and (actor, target) in expired:
                    return {"result": False, "detail": {"0": "friend offer expired"}}
                self.transition(name, params, actor, target, left, right)
                return {"result": True}

            return response_shapes.success(api, self.transact((actor, target), action))
        except (ValueError, state.StateConflictError) as exc:
            # FriendConfirmationWindow restores its optimistic counter on result=false.
            # detail[0] is a native failure field; free text is our diagnostic policy.
            return response_shapes.success(api, {"result": False, "detail": {"0": str(exc)}})

    def transition(self, name: str, params: dict, actor: str, target: str,
                   left: dict, right: dict) -> None:
        lo, ro = self.offers(left), self.offers(right)
        a = self.pair_status(actor, target, left, right)
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
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("no stub response: invalid social clock")
            left.setdefault("socialOffers", {})[target] = {"status": "send", "createdAt": timestamp}
            right.setdefault("socialOffers", {})[actor] = {"status": "receive", "createdAt": timestamp}
            left.get("socialRemovals", {}).pop(target, None)
            right.get("socialRemovals", {}).pop(actor, None)
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
        reason = {"cancelFriendOffer": "cancelled", "dissolutionFriend": "dissolved"}.get(name)
        if name == "feedbackFriendOffer" and params["reply"] == "excuse":
            reason = "rejected"
        if reason:
            left.setdefault("socialRemovals", {})[target] = reason
            right.setdefault("socialRemovals", {})[actor] = reason
