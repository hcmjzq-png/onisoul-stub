#!/usr/bin/env python3
"""Check mounted first-tier trophies against installed tables using memory only.

Level 4 is injected into the isolated test save; this is not Unity acceptance
and does not prove that all progression paths leading to level 4 are complete.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.business.gameplay import GameplayService  # noqa: E402
from app.main import build_registry  # noqa: E402
from app.tables import TableCatalog  # noqa: E402
from tools.gameplay_smoke import MemorySessions, MemoryState  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(table_dir: Path) -> dict:
    catalog, states, sessions = TableCatalog(table_dir), MemoryState(), MemorySessions()
    def connect():
        service = GameplayService(catalog=catalog, load_state=states.load,
                                  save_state=states.save, session_store=sessions)
        with patch('app.main.GameplayService', return_value=service):
            registry = build_registry()
        session, _ = service._issue_login('isolated-trophy-smoke')
        return service, registry, session
    service, registry, session = connect()
    def call(name, **params):
        code, body = registry.dispatch('trophy/' + name, {'access': 'mypage', **params}, session)
        check(code == 200 and isinstance(body, dict), 'invalid dispatch response')
        return body
    created = service.create_player(dict(username='trophy-smoke', countryId='country01',
                                        navigatorId='navi8000101', colorIndex='color1'), session)
    check(created['succeeded'], 'createPlayer failed')
    check(call('getTrophyProgress') == {'playerLevel': {'level': 1.0, 'status': 'accept', 'window': 0.0}},
          'unexpected fresh-player trophy progress')
    check('errorReason' in call('completeTrophy', category='playerLevel'), 'ineligible claim accepted')
    player = states.load(session['playerId'])
    player['entity']['level'] = 4
    service._apply_limits(player)
    states.save(player, session['playerId'])
    before = states.load(session['playerId'])
    check(call('getTrophyProgress')['playerLevel']['window'] == 1.0, 'notification unavailable')
    check(call('messageWindowTrophy', category='playerLevel')['succeeded'], 'notification ack failed')
    check(states.load(session['playerId'])['resources'] == before['resources'], 'ack granted resources')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call('completeTrophy', category='playerLevel'), range(16)))
    wins = [result for result in results if 'errorReason' not in result]
    check(len(wins) == 1, 'first claim did not have exactly one winner')
    check(wins[0]['rewards'] == {'item11_0000101': 100000.0, 'item08_0102701': 6.0},
          'original reward mismatch')
    service, registry, session = connect()
    after = states.load(session['playerId'])
    check(after['resources']['gold']['amount'] == before['resources']['gold']['amount'] + 100000,
          'gold not persisted once')
    check(after['items']['item08_0102701'] == 6, 'jewels not persisted once')
    check(call('getTrophyProgress') == {'playerLevel': {'level': 1.0, 'status': 'lock', 'window': 0.0}},
          'claim status not persisted or unsupported next tier advertised')
    check('errorReason' in call('completeTrophy', category='playerLevel'), 'relogin replay granted reward')
    check(states.load(session['playerId']) == after, 'read/replay changed persistent state')
    return {'ok': True, 'storage': 'isolated memory', 'unity_accepted': False,
            'concurrent_requests': len(results), 'successful_claims': len(wins),
            'reward': wins[0]['rewards'], 'placeholders': sum(
                handler.__module__ == 'app.business.placeholders' for handler in registry._handlers.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--table-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.table_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
