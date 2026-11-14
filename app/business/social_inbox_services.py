"""Unmounted inbox subset: already-materialized gold/wood/food/iron parcels.

Wire evidence: InboxReader, InboxResolveWorker, PluginRunner_DoReceiveMail and
RewardProcessor from the original client. socialInbox is our private versioned
storage contract, NOT an original mail format. No issuance or expiry is inferred.
Rewards and permanent consumed-ID tombstones share the existing player save.
"""
from __future__ import annotations

import copy
import math
from functools import partial
from typing import Any

from app.business.player_services import PlayerServices, integer


class SocialInboxServices(PlayerServices):
    # RewardProcessor.resorucerTables_g; deliberately excludes premium currencies.
    RESOURCES = {"item11_0000101": "gold", "item11_0000201": "wood",
                 "item11_0000301": "food", "item11_0000401": "iron"}
    # Support the bundled plugin's 0..499 request; not an original server limit.
    BATCH_LIMIT = 500

    def register(self, registry: Any) -> None:
        for api, action in (("inbox/getParcels", self.parcels),
                            ("inbox/resolveParcels", self.resolve)):
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    @staticmethod
    def ledger(player: dict) -> dict:
        if not (player.get("entity") or {}).get("created"):
            raise ValueError("created player required")
        ledger = player.get("socialInbox", {"version": 1, "pending": {}, "resolved": {}})
        if (not isinstance(ledger, dict) or set(ledger) != {"version", "pending", "resolved"}
                or type(ledger["version"]) is not int or ledger["version"] != 1
                or not isinstance(ledger["pending"], dict) or not isinstance(ledger["resolved"], dict)
                or any(not isinstance(k, str) or not k for k in (*ledger["pending"], *ledger["resolved"]))
                or any(v is not True for v in ledger["resolved"].values())
                or ledger["pending"].keys() & ledger["resolved"].keys()):
            raise ValueError("no stub response: inbox migration or reused parcel ID requires repair")
        return ledger

    def parcel(self, row: Any) -> dict:
        # Exact private schema prevents unknown expiry/conditions being ignored.
        if not isinstance(row, dict) or set(row) != {"createdTime", "rewards"}:
            raise ValueError("no stub response: unsupported stored parcel schema")
        stamp = row["createdTime"]
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not 0 <= stamp <= 253402271999):
            raise ValueError("no stub response: invalid parcel timestamp")
        rewards = row["rewards"]
        if not isinstance(rewards, dict) or not rewards:
            raise ValueError("no stub response: materialized parcel rewards required")
        if any(item not in self.RESOURCES for item in rewards):
            raise ValueError("no stub response: parcel reward category is not implemented")
        return {"createdTime": float(stamp),
                "rewards": {item: float(integer(amount, 1)) for item, amount in rewards.items()}}

    def parcels(self, player: dict, params: dict) -> dict:
        ledger = self.ledger(player)
        start = integer(params.get("start"))
        end = integer(params.get("end"), -1)
        if end != -1 and (end < start or end - start + 1 > self.BATCH_LIMIT):
            raise ValueError("unsupported inbox page range")
        # Inclusive end and deterministic timestamp/ID order are compatibility
        # choices; UI independently sorts by createdTime. No dummy parcels.
        pending = {key: self.parcel(row) for key, row in ledger["pending"].items()}
        ids = sorted(pending, key=lambda key: (-pending[key]["createdTime"], key))
        selected = ids[start:] if end == -1 else ids[start:end + 1]
        return {"parcels": {key: pending[key] for key in selected}, "totalCount": float(len(ids))}

    def resolve(self, player: dict, params: dict) -> dict:
        ledger = copy.deepcopy(self.ledger(player))
        requests = params.get("responses")
        if (not isinstance(requests, dict) or len(requests) > self.BATCH_LIMIT
                or any(not isinstance(key, str) or not key for key in requests)):
            raise ValueError("responses must be a parcel-ID map of at most 500 entries")
        successful, failed = {}, {}
        resources = copy.deepcopy(player["resources"])
        for parcel_id, decision in requests.items():
            try:
                if decision != "accept":
                    raise ValueError("no stub response: only accept is supported")
                if parcel_id in ledger["resolved"]:
                    # Replaying reward deltas would double the client's display.
                    # Lost-response callers must reconcile their resource snapshot.
                    successful[parcel_id] = {"rewards": {}}
                    continue
                if parcel_id not in ledger["pending"]:
                    raise ValueError("unknown parcel for this player")
                row = self.parcel(ledger["pending"][parcel_id])
                updated = copy.deepcopy(resources)
                for item, amount in row["rewards"].items():
                    key = self.RESOURCES[item]
                    current = updated[key]
                    total = integer(current["amount"]) + integer(amount, 1)
                    if total > integer(current["maxAmount"]):
                        raise ValueError("no stub response: parcel resource overflow is not supported")
                    current["amount"] = total
                resources = updated
                del ledger["pending"][parcel_id]
                ledger["resolved"][parcel_id] = True
                successful[parcel_id] = {"rewards": row["rewards"]}
            except ValueError as exc:
                # The original consumer uses failed.Count, not the value schema.
                # These diagnostic strings are a simulator compatibility choice.
                failed[parcel_id] = str(exc)
        if ledger != self.ledger(player):
            player["socialInbox"] = ledger
            player["resources"] = resources
        return {"successful": successful, "failed": failed}
