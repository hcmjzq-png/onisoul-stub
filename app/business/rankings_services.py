"""Unmounted kokudaka snapshot queries; no fabricated scores or event periods.

Snapshot/ScoreRecord are SERVER INTERNAL interfaces, not original wire fields.
The integrator supplies a complete, transactionally consistent country snapshot
from verified A-group kokudaka records. Missing data is not an empty ranking.
Competition ties and player-id tie ordering are explicit compatibility policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import struct
from typing import Any, Callable

from app.business.player_services import PlayerServices, integer


@dataclass(frozen=True)
class ScoreRecord:
    player_id: str
    username: str
    country: str
    score: int

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in
               (self.player_id, self.username, self.country)):
            raise ValueError("invalid ranking identity")
        score = integer(self.score, minimum=0, maximum=2**53 - 1)
        # mypageRankingWindow:503 calls HashAccessFuncs.getInt, which parses
        # float32 then casts to Int32. The HTML list uses getDouble instead.
        # Reject unrepresentable scores rather than round/clamp authoritative
        # data and make the two views disagree. This is a support constraint,
        # not evidence of an original-game kokudaka cap.
        if score > 2**31 - 1 or struct.unpack("!f", struct.pack("!f", score))[0] != score:
            raise ValueError("no stub response: kokudaka score cannot be represented by client Int32/float32")


@dataclass(frozen=True)
class Snapshot:
    country: str
    records: tuple[ScoreRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.country, str) or not self.country:
            raise ValueError("snapshot country required")
        if type(self.records) is not tuple or any(type(r) is not ScoreRecord for r in self.records):
            raise ValueError("immutable score records required")
        if any(r.country != self.country for r in self.records):
            raise ValueError("mixed country snapshot")
        if len({r.player_id for r in self.records}) != len(self.records):
            raise ValueError("duplicate ranking player")

    def ranked(self) -> list[dict[str, Any]]:
        ordered = sorted(self.records, key=lambda r: (-r.score, r.player_id))
        rows, previous, rank = [], None, 0
        for index, record in enumerate(ordered):
            if record.score != previous:
                rank = index + 1
            previous = record.score
            rows.append(dict(playerId=record.player_id, username=record.username,
                             country=record.country, score=float(record.score), rank=float(rank)))
        return rows


@dataclass(frozen=True)
class SnapshotPair:
    """Provider must read both snapshots in ONE transaction/revision.

    None means unavailable (fail), Snapshot(country, ()) means proven empty.
    No automatic midnight reset or fabricated previous period is performed.
    One request retains one immutable pair even if the provider publishes a new
    pair concurrently. Separate HTTP requests may observe different pairs;
    the original wrappers do not send a snapshot revision to pin them together.
    """
    current: Snapshot | None
    last: Snapshot | None


class RankingsServices(PlayerServices):
    def __init__(self, service: Any,
                 snapshots: Callable[[str], SnapshotPair] | None = None) -> None:
        super().__init__(service)
        self.snapshots = snapshots

    def register(self, registry: Any) -> None:
        for api, action in {
            "ranking/getRankersInKokudaka": self.kokudaka_rankers,
            "ranking/getBriefOfKokudaka": self.kokudaka_brief,
        }.items():
            registry.register(api, self.service._guard(api, partial(self.call, api, action)))

    def pair(self, player: dict) -> SnapshotPair:
        if self.snapshots is None:
            raise ValueError("no stub response: verified kokudaka snapshot provider unavailable")
        country = player["entity"]["country"]
        pair = self.snapshots(country)
        if type(pair) is not SnapshotPair or any(
            s is not None and (type(s) is not Snapshot or s.country != country)
            for s in (pair.current, pair.last)
        ):
            raise ValueError("no stub response: invalid kokudaka snapshot scope")
        return pair

    @staticmethod
    def rows(snapshot: Snapshot | None) -> list[dict]:
        if snapshot is None:
            raise ValueError("no stub response: requested kokudaka period unavailable")
        return snapshot.ranked()

    @staticmethod
    def mine(rows: list[dict], player: dict) -> dict:
        player_id = str(player["entity"]["playerId"])
        return next(({"rank": r["rank"], "score": r["score"]}
                     for r in rows if r["playerId"] == player_id), {"rank": -1.0})

    def kokudaka_rankers(self, player: dict, params: dict) -> dict:
        term = params.get("term")
        if term not in ("current", "last"):
            raise ValueError("term must be current or last")
        start = integer(params.get("startIndex"), minimum=0)
        end = integer(params.get("endIndex"), minimum=start)
        if end - start >= 100:
            raise ValueError("at most 100 rankers per page")
        pair = self.pair(player)
        rows = self.rows(pair.current if term == "current" else pair.last)
        return {"entries": float(len(rows)), "myRecord": self.mine(rows, player),
                "rankers": {str(i): row for i, row in enumerate(rows[start:end + 1])}}

    def kokudaka_brief(self, player: dict, params: dict) -> dict:
        pair = self.pair(player)
        brief = self.mine(self.rows(pair.current), player)
        brief["lastRank"] = self.mine(self.rows(pair.last), player)["rank"]
        return {"brief": brief}
