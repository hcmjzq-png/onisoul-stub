#!/usr/bin/env python3
"""Plan duplicate test-save cleanup; apply only the reviewed IDs and digests.

Retain one created save per exact nonempty name (newest update breaks ties).
Account credentials and account/player identity mappings are retained. Apply
requires a private backup file, a stopped service, and unchanged player rows.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

from app import db


def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def plan(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        value = json.loads(row['state_json'])
        name = value.get('entity', {}).get('username', '')
        if name:
            groups[name].append((row, value))
    result = []
    for name, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda pair: (pair[1].get('entity', {}).get('created') is True,
                                       pair[0]['updated_at'], pair[0]['player_id']), reverse=True)
        result.append({'name': name, 'keep': members[0][0]['player_id'],
                       'delete': [{'player_id': row['player_id'], 'sha256': digest(row['state_json'])}
                                  for row, _value in members[1:]]})
    return {'version': 1, 'groups': result}


def apply(expected: dict, backup: Path) -> int:
    with db.connection() as con:
        with con.cursor() as cur:
            cur.execute('SELECT player_id,state_json,updated_at FROM players ORDER BY player_id FOR UPDATE')
            rows = cur.fetchall()
            if plan(rows) != expected:
                raise ValueError('duplicate plan changed; review a fresh plan')
            ids = {entry['player_id'] for group in expected['groups'] for entry in group['delete']}
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open('x', encoding='utf-8') as stream:
                os.chmod(backup, 0o600)
                cur.execute('SELECT * FROM sessions WHERE player_id IN (' + ','.join(['%s'] * len(ids)) + ')', tuple(sorted(ids))) if ids else None
                sessions = cur.fetchall() if ids else []
                json.dump({'players': [row for row in rows if row['player_id'] in ids],
                           'sessions': sessions, 'plan': expected}, stream, ensure_ascii=False, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            for pid in sorted(ids):
                cur.execute('DELETE FROM sessions WHERE player_id=%s', (pid,))
                cur.execute('DELETE FROM players WHERE player_id=%s', (pid,))
                if cur.rowcount != 1:
                    raise ValueError('player disappeared during cleanup')
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.apply:
        if not args.backup:
            parser.error('--backup is required for apply')
        print(json.dumps({'deleted': apply(json.loads(args.plan.read_text(encoding='utf-8')), args.backup)}))
    else:
        with db.connection() as con:
            with con.cursor() as cur:
                cur.execute('SELECT player_id,state_json,updated_at FROM players ORDER BY player_id')
                result = plan(cur.fetchall())
        with args.plan.open('x', encoding='utf-8') as stream:
            os.chmod(args.plan, 0o600)
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'groups': len(result['groups']), 'deletions': sum(len(g['delete']) for g in result['groups'])}))


if __name__ == '__main__':
    main()
