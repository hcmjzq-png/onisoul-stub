"""Research I policy inventory. All 32 routes stay closed; no grant/login handler.

The original wrapper is protocol evidence, not administrator authentication.
In particular forcePresents sends client-selected rewards without a token.
See docs/analysis/research-331/results/i-infrastructure/endpoints.tsv.
"""
from __future__ import annotations

from typing import Any

from app.protocol import envelope

CONTROLLED_ADMIN = frozenset({"admin/inbox/present"})
TEST_HELPERS = frozenset({
    "debug/addCollections", "debug/addItems", "debug/debugAccelerateProduceTask",
    "debug/debugAddBuildingExp", "debug/debugCreateCharacter", "debug/debugCreateEquip",
    "debug/debugCreateQuestEncount", "debug/debugCreateRaidBossWork",
    "debug/debugGetQuestCompleteFlags", "debug/debugGradeUpBuildings",
    "debug/debugIncreasePlayerLevel", "debug/debugOpenQuest",
    "debug/debugRankingNationalPowerAddScoreWithSwitch",
    "debug/debugRentalNavigatorBarelyExpiration", "debug/dedicate",
    "debug/forceCompleteQuest", "debug/forceFeedbackFriendOffer",
    "debug/forceProgressGiganticChain", "debug/forceProgressGiganticPhase",
    "debug/forceProgressQuest", "debug/setQuestStep",
})
RETAIN_CLOSED = frozenset({
    "debug/clearBuildings", "debug/clearLastMigrateTime", "debug/debugDeleteAllCharacter",
    "debug/debugDeleteAllEquip", "debug/debugLoginCog", "debug/debugResetCreditStepCount",
    "debug/resetDedication", "debug/resetPlayer", "debug/resetQuest", "debug/withdrawTurfWar",
})
DISABLED_ENDPOINTS = CONTROLLED_ADMIN | TEST_HELPERS | RETAIN_CLOSED


def denial(api: str) -> dict[str, Any] | None:
    """Unconditional policy, including observe mode and purported admin sessions.

    No request fields, loopback address, player role or default account can opt in.
    A future issuer needs an independent trusted principal and issuance ledger.
    """
    if api not in DISABLED_ENDPOINTS:
        return None
    message = f"no stub response: {api}; administrative/debug endpoint disabled"
    # GameRestarter.cs:79-99 checks errorReason before invoking success callbacks.
    return envelope.error(envelope.ERR_UNAUTHORIZED, message, {"errorReason": message})
