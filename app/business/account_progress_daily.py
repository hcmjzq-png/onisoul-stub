"""Opt-in login stamps; no historical campaign or daily-mission rules assumed.

Wire evidence: LoginBounusMenu, PoliticFSMLogin, UserStatus in the original DLL.
The injected immutable plan is deployment policy, NOT a recovered original table.
No default plan, public configuration API, or registration in GameplayService.
See docs/analysis/research-331/results/h-account/integration-notes.md.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from functools import partial
from typing import Any, Callable

from app.business import response_shapes
from app.business.player_services import PlayerServices, integer


CLIENT_SHA256 = "b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e"
RESOURCE_ITEMS = {"item11_0000101": "gold", "item11_0000201": "wood",
                  "item11_0000301": "food", "item11_0000401": "iron"}
APIS = frozenset({"common/getLoginStampSheet", "common/stampLoginSheet"})
MAX_TIME = 253402300799  # DateTime year 9999; format must be parsable by Unity.


def timestamp(value: Any) -> int:
    return integer(value, 0, MAX_TIME)


def wire_date(value: int) -> str:
    value = timestamp(value)
    stamp = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=value)
    # Original ParseExact uses H, not HH; +0000 is a literal in that format.
    return (f"{stamp.year:04d}-{stamp.month:02d}-{stamp.day:02d}T"
            f"{stamp.hour}:{stamp.minute:02d}:{stamp.second:02d}+0000")


@dataclass(frozen=True)
class StampReward:
    item_id: str
    amount: int
    anniversary: str

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id:
            raise ValueError("stamp item ID required")
        if type(self.amount) is not int:
            raise ValueError("integer stamp amount required")
        integer(self.amount, 1)
        if self.anniversary not in ("gold", "silver"):
            raise ValueError("unsupported stamp appearance")


@dataclass(frozen=True)
class LoginStampPlan:
    campaign_id: str
    revision: str
    client_sha256: str
    evidence_ref: str
    starts_at: int
    ends_at: int
    boundary_utc_seconds: int
    missed_day_policy: str
    rewards: tuple[StampReward, ...]

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.starts_at, self.ends_at, self.boundary_utc_seconds)):
            raise ValueError("integer campaign timestamps and day boundary required")
        for value in (self.campaign_id, self.revision, self.evidence_ref):
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise ValueError("campaign identity, revision and evidence reference required")
        if self.client_sha256 != CLIENT_SHA256:
            raise ValueError("no stub response: unreviewed client version")
        if not 0 < timestamp(self.ends_at) - timestamp(self.starts_at) <= 366 * 86400:
            raise ValueError("campaign must have a bounded positive period (at most 366 days)")
        integer(self.boundary_utc_seconds, 0, 86399)
        if self.missed_day_policy not in ("preserve", "reset"):
            raise ValueError("explicit missed-day policy required")
        # Local UI/storage bound based on the original fourteen-cell default;
        # not a claim that every historical campaign contained fourteen days.
        if (not isinstance(self.rewards, tuple) or not 1 <= len(self.rewards) <= 14
                or any(not isinstance(row, StampReward) for row in self.rewards)):
            raise ValueError("one to fourteen immutable reward rows required")

    @property
    def fingerprint(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()

    def day(self, now: int) -> int:
        return (now - self.boundary_utc_seconds) // 86400


class AccountProgressDaily(PlayerServices):
    def __init__(self, service: Any, *, plan: LoginStampPlan | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        super().__init__(service)
        self.plan = plan
        self.clock = clock

    def register(self, registry: Any, *, apis: frozenset[str] = APIS) -> None:
        for api in APIS & apis:
            registry.register(api, self.service._guard(api, partial(self.call, api)))

    @staticmethod
    def failure(api: str, message: str) -> dict:
        # Do not include shared placeholder stampCount/loginSheet/empty dates:
        # failures are not stamp results and must not reach the reward consumer.
        return response_shapes.success(api, {"succeeded": False,
                                             "errorReason": message, "message": message})

    def active_plan(self, now: int) -> LoginStampPlan:
        if self.plan is None or not self.plan.starts_at <= now < self.plan.ends_at:
            raise ValueError("no stub response: no reviewed active login-stamp schedule")
        return self.plan

    def ledger(self, player: dict, plan: LoginStampPlan, now: int) -> tuple[dict, list]:
        bad = "no stub response: invalid or changed login-stamp ledger; migration required"
        account = player.get("accountProgress", {})
        if not isinstance(account, dict):
            raise ValueError(bad)
        stored = account.get("loginStampV1", {})
        if not isinstance(stored, dict):
            raise ValueError(bad)
        for campaign_id, row in stored.items():
            if not isinstance(campaign_id, str) or not isinstance(row, dict):
                raise ValueError(bad)
            if set(row) != {"fingerprint", "startsAt", "endsAt", "claims"}:
                raise ValueError(bad)
            start, end = timestamp(row["startsAt"]), timestamp(row["endsAt"])
            if (start >= end or not isinstance(row["fingerprint"], str)
                    or len(row["fingerprint"]) != 64 or not isinstance(row["claims"], list)
                    or not row["claims"]):
                raise ValueError(bad)
            if campaign_id != plan.campaign_id and start < plan.ends_at and plan.starts_at < end:
                raise ValueError("no stub response: overlapping saved campaign; migration required")
        current = stored.get(plan.campaign_id)
        if current is None:
            return stored, []
        if (current["fingerprint"] != plan.fingerprint or current["startsAt"] != plan.starts_at
                or current["endsAt"] != plan.ends_at):
            raise ValueError(bad)
        claims = current["claims"]
        previous_day, count = None, 0
        if len(claims) > 367:
            raise ValueError(bad)
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {"at", "day", "ordinal"}:
                raise ValueError(bad)
            at = timestamp(claim["at"])
            day = plan.day(at)
            if (not plan.starts_at <= at < plan.ends_at or at > now
                    or type(claim["day"]) is not int or claim["day"] != day
                    or previous_day is not None and day <= previous_day):
                raise ValueError(bad)
            if previous_day is not None and day > previous_day + 1 and plan.missed_day_policy == "reset":
                count = 0
            count += 1
            if integer(claim["ordinal"], 1, len(plan.rewards)) != count:
                raise ValueError(bad)
            previous_day = day
        return stored, claims

    def validate_rewards(self, plan: LoginStampPlan) -> None:
        for reward in plan.rewards:
            if reward.item_id in RESOURCE_ITEMS:
                continue  # Exact mapping from RewardProcessor.cs:25-70.
            if reward.item_id.startswith("item08_"):
                row = self.table("item08").get(reward.item_id)
                if isinstance(row, dict) and row.get("enable") is True and row.get("category") == "jewel":
                    continue
            raise ValueError("no stub response: unsupported login-stamp reward reference")

    @staticmethod
    def next_ordinal(plan: LoginStampPlan, claims: list, now: int) -> int:
        if not claims:
            return 1
        last = claims[-1]
        if last["ordinal"] == len(plan.rewards):
            return len(plan.rewards) + 1  # Completed sheets never restart after a gap.
        if plan.missed_day_policy == "reset" and plan.day(now) > last["day"] + 1:
            return 1
        return last["ordinal"] + 1

    def next_stamp_date(self, player: dict, *, now: int | None = None) -> str | None:
        """Read-only getPlayerParams adapter; None means no active campaign.

        Invalid ledger is an error, not permission to silently initialize it.
        The common timestamp must also drive stampLoginSheet; no host timezone.
        """
        now = timestamp(int(self.clock())) if now is None else timestamp(now)
        if self.plan is None or not self.plan.starts_at <= now < self.plan.ends_at:
            return None
        plan = self.plan
        _, claims = self.ledger(player, plan, now)
        self.validate_rewards(plan)
        day_start = plan.day(now) * 86400 + plan.boundary_utc_seconds
        if claims and claims[-1]["ordinal"] == len(plan.rewards):
            due = plan.ends_at
        elif claims and claims[-1]["day"] == plan.day(now):
            due = min(day_start + 86400, plan.ends_at)
        else:
            due = max(day_start, plan.starts_at)
        return wire_date(due)

    def payload(self, player: dict, plan: LoginStampPlan, claims: list, now: int) -> dict:
        return {"startDate": wire_date(plan.starts_at), "endDate": wire_date(plan.ends_at),
                "stampCount": float(claims[-1]["ordinal"] if claims else 0),
                "nextStampDate": self.next_stamp_date(player, now=now),
                "loginSheet": {f"day{index}": {"itemId": reward.item_id,
                    "amount": float(reward.amount), "anniversary": reward.anniversary}
                    for index, reward in enumerate(plan.rewards, 1)}}

    def claim(self, player: dict, plan: LoginStampPlan, now: int) -> dict:
        stored, claims = self.ledger(player, plan, now)
        day = plan.day(now)
        if claims and claims[-1]["day"] == day:
            # No date/nonce on the original request. Returning the first success
            # again would run UserStatus.addLoginBounus a second time.
            raise ValueError("no stub response: login stamp already claimed; refresh player parameters")
        ordinal = self.next_ordinal(plan, claims, now)
        if ordinal > len(plan.rewards):
            raise ValueError("no stub response: login stamp sheet completed")
        self.validate_rewards(plan)
        reward = plan.rewards[ordinal - 1]
        resource = RESOURCE_ITEMS.get(reward.item_id)
        if resource:
            balance = player.get("resources", {}).get(resource)
            if not isinstance(balance, dict):
                raise ValueError("no stub response: missing resource balance")
            total = integer(balance.get("amount")) + reward.amount
            if total > integer(balance.get("maxAmount")):
                raise ValueError("no stub response: stamp overflow/inbox delivery unsupported")
            balance["amount"] = total
        else:
            items = player.get("items")
            if not isinstance(items, dict):
                raise ValueError("no stub response: invalid item inventory")
            items[reward.item_id] = integer(integer(items.get(reward.item_id, 0)) + reward.amount)
        updated = copy.deepcopy(claims) + [{"at": now, "day": day, "ordinal": ordinal}]
        ledger = copy.deepcopy(stored)
        ledger[plan.campaign_id] = {"fingerprint": plan.fingerprint,
            "startsAt": plan.starts_at, "endsAt": plan.ends_at, "claims": updated}
        player.setdefault("accountProgress", {})["loginStampV1"] = ledger
        return self.payload(player, plan, updated, now)

    def call(self, api: str, params: dict, session: dict | None) -> dict:
        player_id = self.service._player_id(session)
        if not player_id:
            return self.failure(api, "authentication required")
        player, _dirty = self.service._load(player_id)
        staged = copy.deepcopy(player)
        try:
            if staged.get("entity", {}).get("created") is not True:
                raise ValueError("player must be created")
            # Only original token parameter is accepted: client cannot select
            # date, campaign, target account, counts, reward or a reset policy.
            if set(params) - {"token"}:
                raise ValueError("no stub response: unsupported login-stamp parameters")
            now = timestamp(int(self.clock()))
            plan = self.active_plan(now)
            if api == "common/stampLoginSheet":
                payload = self.claim(staged, plan, now)
            elif api == "common/getLoginStampSheet":
                _, claims = self.ledger(staged, plan, now)
                self.validate_rewards(plan)
                payload = self.payload(staged, plan, claims, now)
            else:
                raise ValueError("no stub response: unsupported daily API")
        except ValueError as exc:
            return self.failure(api, str(exc))
        # Reads never save, even when GameplayService supplied normalized data.
        # Rewards and receipt are one staged save under _guard + storage CAS.
        if staged != player:
            self.service._save(staged, player_id)
        return response_shapes.success(api, payload)
