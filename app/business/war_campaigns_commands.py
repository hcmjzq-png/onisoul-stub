"""TurfWar enrollment transitions over an isolated event/player transaction.

Wire: WebApiClient.cs:2784-2806; TurfWarBriefCache.cs:379-393;
TurfWarWorldMap.cs:291-328. No client-provided team, country, event ID or clock.
"""
from __future__ import annotations

from typing import Any, ContextManager, Protocol

from app.business.war_campaigns_events import (
    append_turf_event, replay_turf_war, turf_war_phase,
)


class AtomicWarEnrollment(Protocol):
    def __call__(self, event_id: str, player_id: str) -> ContextManager[dict[str, Any]]:
        """Yield {'event': existing event, 'player': existing player} drafts.

        Lock event first, then player; authenticate/select the current player in
        the caller. Read the country inside this transaction, never from a stale
        earlier load. Commit journal and revisions once on normal exit, otherwise
        roll back. No default event, auto-create player or partial commits. The
        adapter belongs to I and MUST use the same store as GameplayService.
        """
        ...


def enroll_turf_war(event: dict, player: dict, player_id: str, *, now: float,
                    battlefield: str | None = None) -> dict:
    """Real source of entry/selection records, not an imported alive snapshot.

    Idempotent same-event retries return only absolute team/empty acknowledgment;
    no resource deltas. First choice is permanent in this supported subset.
    Other choices must use moveBattlefield, whose cooldown/cost rules are unknown.
    """
    if turf_war_phase(event, now) != "open":
        raise ValueError("no stub response: turfWar enrollment is not open")
    entity = player.get("entity") if isinstance(player, dict) else None
    if (not isinstance(entity, dict) or entity.get("created") is not True
            or entity.get("playerId") != player_id):
        raise ValueError("no stub response: created authenticated player required")
    country = entity.get("country")
    if not isinstance(country, str) or country not in event["plan"]["countryTeams"]:
        raise ValueError("no stub response: player country has no declared allocation")
    member = replay_turf_war(event)[0].get(player_id)
    if member is not None and member["country"] != country:
        raise ValueError("no stub response: enrolled country changed; migration unsupported")
    if battlefield is None:
        if member is None:
            append_turf_event(event, "entered", now, playerId=player_id, country=country)
        return {"team": event["plan"]["countryTeams"][country]}
    if member is None:
        raise ValueError("no stub response: enter turfWar before selecting a battlefield")
    # HTTP uses catalogue IDs, not active-table slot names battlefield01..03.
    # TurfWarInformation.cs:45-49 resolves the same key through the catalogue.
    if not isinstance(battlefield, str) or battlefield not in event["plan"]["battlefields"].values():
        raise ValueError("no stub response: battlefield is not in the declared event")
    if member["battlefield"] not in ("none", battlefield):
        raise ValueError("no stub response: battlefield movement is unsupported")
    if member["battlefield"] == "none":
        append_turf_event(event, "selected", now, playerId=player_id, battlefield=battlefield)
    return {}
