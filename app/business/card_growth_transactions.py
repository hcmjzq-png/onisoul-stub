"""C-only transaction adapter. These identities are NOT original wire fields.

An authenticated transport must bind one identity before its retry loop and
retain it for retries. No default resolver, random-per-request ID or body-based
deduplication is supplied. See research-331/results/c-card-growth/.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Callable


def request_digest(api: str, params: dict) -> str:
    """Bind an identity to its body; the digest is never the identity itself."""
    try:
        encoded = json.dumps({"api": api, "params": {
            key: value for key, value in params.items() if key != "token"
        }}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid operation body") from exc
    return hashlib.sha256(encoded).hexdigest()


def operation_key(operation_id: str) -> str:
    if (not isinstance(operation_id, str) or not operation_id.isascii()
            or not 1 <= len(operation_id) <= 128
            or any(not (c.isalnum() or c in "-_.:") for c in operation_id)):
        raise ValueError("no stub response: trusted operation identity required")
    return hashlib.sha256(operation_id.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class OperationContext:
    """Out-of-band authenticated dispatcher metadata; never read from params."""

    player_id: str
    api: str
    operation_id: str
    body_digest: str

    def validate(self, player_id: str, api: str, params: dict) -> None:
        operation_key(self.operation_id)
        if (self.player_id != player_id or self.api != api
                or self.body_digest != request_digest(api, params)):
            raise ValueError("operation context does not match authenticated request")


def settle_once(player: dict, context: OperationContext, action: Callable[[dict], dict]) -> dict:
    """Copy, validate, mutate and add receipt inside the existing single-save CAS.

    A committed retry is an error, even when the first response was lost. This
    avoids replaying an increment or rolling the client back to an old snapshot.
    The transport must refresh authoritative inventories after such an error.
    """
    receipts = player.get("cardGrowthOperations", {})
    if not isinstance(receipts, dict):
        raise ValueError("no stub response: invalid card growth operation ledger")
    key = operation_key(context.operation_id)
    if key in receipts:
        record = receipts[key]
        if not isinstance(record, dict) or record.get("status") != "committed":
            raise ValueError("no stub response: invalid card growth operation receipt")
        if record.get("api") != context.api or record.get("bodyDigest") != context.body_digest:
            raise ValueError("operation identity was already used for another request")
        raise ValueError("operation already committed; refresh character, potions and resources")
    if len(receipts) >= 1024:
        raise ValueError("no stub response: card growth receipt archive required")
    candidate = copy.deepcopy(player)
    payload = action(candidate)
    candidate.setdefault("cardGrowthOperations", {})[key] = {
        "api": context.api, "bodyDigest": context.body_digest, "status": "committed",
        # Hash, not a replayable response; unchanged historical receipts remain valid.
        "resultDigest": request_digest(context.api, payload),
    }
    player.clear()
    player.update(candidate)
    return payload
