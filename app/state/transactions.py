"""InnoDB unit of work for existing players and server-owned shared records.

Declare every key before entering. Lock all players in ASCII order, then shared
keys in (namespace, key) order. No network/DDL/standalone save inside the block.
Only changed records advance revision. Pre-commit failures roll everything back,
including new shared keys. Lost COMMIT acknowledgement has unknown outcome: read
the durable receipt before retrying. These keys/revisions are private, not wire
fields. No gameplay, administrator identity or reward authority is inferred here.
"""
from __future__ import annotations

import copy
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from app import db
from app.state.player import (RetryableTransactionError, StateConflictError,
                              decode_state, revision)

SharedKey = tuple[str, str]
_ID = re.compile(r"[a-z0-9_:-]{1,64}\Z")
_KEY = re.compile(r"[A-Za-z0-9_.:/-]+\Z")
MAX_RECORDS = 256  # local bound on lock footprint, not an original game rule


@dataclass
class UnitOfWork:
    players: dict[str, dict[str, Any]]
    records: dict[SharedKey, dict[str, Any] | None]


def _keys(player_ids: tuple[str, ...], shared_keys: tuple[SharedKey, ...]
          ) -> tuple[tuple[str, ...], tuple[SharedKey, ...]]:
    if not 0 < len(player_ids) + len(shared_keys) <= MAX_RECORDS:
        raise ValueError("declare between 1 and 256 transaction records")
    if any(not isinstance(pid, str) or not _ID.fullmatch(pid) for pid in player_ids):
        raise ValueError("player IDs must be canonical lower-case ASCII identifiers")
    for key in shared_keys:
        if (not isinstance(key, tuple) or len(key) != 2
                or any(not isinstance(v, str) or not _KEY.fullmatch(v) for v in key)
                or len(key[0]) > 64 or len(key[1]) > 128):
            raise ValueError("invalid shared record key")
    if len(set(player_ids)) != len(player_ids) or len(set(shared_keys)) != len(shared_keys):
        raise ValueError("duplicate transaction key")
    return tuple(sorted(player_ids)), tuple(sorted(shared_keys))


def _encode(value: dict[str, Any], next_revision: int) -> str:
    if not isinstance(value, dict):
        raise ValueError("transaction records must be objects")
    payload = json.dumps({**value, "_revision": next_revision},
                         ensure_ascii=False, allow_nan=False, sort_keys=True)
    # Do not silently stringify integer mapping keys/convert tuples in a save.
    if json.loads(payload) != {**value, "_revision": next_revision}:
        raise ValueError("transaction record is not a JSON object tree")
    return payload


@contextmanager
def atomic(*, player_ids: tuple[str, ...] = (), shared_keys: tuple[SharedKey, ...] = (),
           expected_players: Mapping[str, int] | None = None,
           expected_records: Mapping[SharedKey, int] | None = None) -> Iterator[UnitOfWork]:
    """Commit declared records together. Missing players fail; shared None means absent.

    Use a shared key as an idempotency receipt/quota/snapshot identity. Set its
    value in the same block as the player mutation; check existing contents before
    applying again. Reusing a key with different intent must be rejected by the
    caller. Setting an existing record to None/deleting keys is forbidden; retain
    tombstones/receipts so IDs cannot be recycled. No automatic retries or grants.
    """
    pids, keys = _keys(player_ids, shared_keys)
    ep, er = dict(expected_players or {}), dict(expected_records or {})
    if not ep.keys() <= set(pids) or not er.keys() <= set(keys):
        raise ValueError("expected revision for an undeclared key")
    if any(type(v) is not int or v < 0 for v in (*ep.values(), *er.values())):
        raise ValueError("invalid expected revision")
    unit = UnitOfWork({}, {})
    revisions: dict[SharedKey, int] = {}
    changed: list[tuple[dict, int]] = []
    try:
        with db.connection() as con:
            with con.cursor() as cur:
                for pid in pids:
                    cur.execute("SELECT player_id, state_json FROM players "
                                "WHERE player_id = %s FOR UPDATE", (pid,))
                    row = cur.fetchone()
                    if row is None:
                        raise ValueError(f"no stub response: missing player {pid}")
                    if row["player_id"] != pid:
                        raise ValueError("noncanonical player ID alias")
                    unit.players[pid] = decode_state(row["state_json"], pid)
                    if pid in ep and revision(unit.players[pid]) != ep[pid]:
                        raise StateConflictError(f"player {pid} revision changed")
                for key in keys:
                    # Lock an absent key via its unique PK as well as existing rows.
                    # A NULL row reserves the key, but is not a published record.
                    cur.execute("INSERT INTO shared_records "
                                "(namespace, record_key, state_json, revision, updated_at) "
                                "VALUES (%s, %s, NULL, 0, %s) "
                                "ON DUPLICATE KEY UPDATE revision = revision", (*key, time.time()))
                    cur.execute("SELECT state_json, revision FROM shared_records "
                                "WHERE namespace = %s AND record_key = %s FOR UPDATE", key)
                    row = cur.fetchone()
                    revisions[key] = row["revision"]
                    raw = row["state_json"]
                    value = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                    if value is not None and (not isinstance(value, dict)
                                              or revision(value) != revisions[key]):
                        raise ValueError("invalid shared record revision/schema")
                    if value is None and revisions[key] != 0:
                        raise ValueError("invalid empty shared record revision")
                    unit.records[key] = value
                    if key in er and er[key] != revisions[key]:
                        raise StateConflictError(f"shared record {key} revision changed")
                before = copy.deepcopy(unit)
                yield unit
                if set(unit.players) != set(pids) or set(unit.records) != set(keys):
                    raise ValueError("transaction key set cannot change")
                # Prepare/validate every payload before the first UPDATE.
                writes = []
                for pid in pids:
                    value, original = unit.players[pid], before.players[pid]
                    if not isinstance(value, dict) or revision(value) != revision(original):
                        raise StateConflictError("player revision is managed by storage")
                    if (value.get("entity") or {}).get("playerId") != pid:
                        raise ValueError("player identity cannot change")
                    rev = revision(original) + 1
                    payload = _encode(value, rev)
                    if payload != _encode(original, rev):
                        writes.append(("UPDATE players SET state_json = %s, updated_at = %s "
                                       "WHERE player_id = %s", (payload, time.time(), pid)))
                        changed.append((value, rev))
                for key in keys:
                    value, original = unit.records[key], before.records[key]
                    if value is None:
                        if original is not None:
                            raise ValueError("retain shared record tombstones; deletion is forbidden")
                        continue
                    if not isinstance(value, dict) or revision(value) != revisions[key]:
                        raise StateConflictError("shared revision is managed by storage")
                    rev = revisions[key] + 1
                    payload = _encode(value, rev)
                    if original is None or payload != _encode(original, rev):
                        writes.append(("UPDATE shared_records SET state_json = %s, revision = %s, "
                                       "updated_at = %s WHERE namespace = %s AND record_key = %s",
                                       (payload, rev, time.time(), *key)))
                        changed.append((value, rev))
                for sql, params in writes:
                    cur.execute(sql, params)
    except Exception as exc:
        if db.retryable_transaction_error(exc):
            raise RetryableTransactionError("transaction rolled back; reload and retry") from exc
        raise
    # Never advertise a new revision until COMMIT has actually succeeded.
    for value, rev in changed:
        value["_revision"] = rev


@contextmanager
def atomic_players(player_ids: tuple[str, ...]) -> Iterator[dict[str, dict[str, Any]]]:
    """Adapter for SocialServices.AtomicPlayers; same players table/CAS as save()."""
    with atomic(player_ids=player_ids) as unit:
        yield unit.players
