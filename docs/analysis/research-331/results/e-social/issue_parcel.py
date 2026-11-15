"""Host-admin issuance CLI, not an HTTP endpoint. Preview by default.

Requires I's atomic_players after integration. A host administrator supplies a
stable operation ID and an audit reference; normal game sessions cannot invoke
this process. Database connection settings come only from ONI_DB_* environment.
Never expose this command or stage_parcel through a client-selected RPC.
"""
import argparse
import json
from pathlib import Path
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--issuance-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--resource", choices=("gold", "wood", "food", "iron"), required=True)
    parser.add_argument("--amount", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from app import state
    from app.business.gameplay import GameplayService
    from app.business.social_inbox_services import SocialInboxServices
    service = SocialInboxServices(GameplayService())
    item = next(k for k, v in service.RESOURCES.items() if v == args.resource)
    rewards = {item: args.amount}
    service.parcel({"createdTime": time.time(), "rewards": rewards})
    intent = {"playerId": args.player_id, "issuanceId": args.issuance_id,
              "source": {"kind": "administrator", "authority": args.operator, "reference": args.reference},
              "rewards": rewards}
    if not args.apply:
        print(json.dumps({"preview": intent, "recipientChecked": False, "written": False}, ensure_ascii=False))
        return 0
    if not hasattr(state, "atomic_players"):
        raise RuntimeError("I infrastructure must be integrated before issuance")
    with state.atomic_players((args.player_id,)) as rows:
        parcel_id = service.stage_parcel(rows[args.player_id], issuance_id=args.issuance_id,
            source=intent["source"], rewards=rewards, created_time=time.time())
    print(json.dumps({"parcelId": parcel_id, "committed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
