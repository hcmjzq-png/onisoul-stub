"""Check this fixed baseline assignment against the normal registry; read-only."""
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

PLAN = Path(__file__).resolve().parent
ROOT = PLAN.parents[2]
sys.path.insert(0, str(ROOT))
from app.main import build_registry


def verify() -> dict:
    summary = json.loads((PLAN / 'summary.json').read_text(encoding='utf-8'))
    ownership = json.loads((PLAN / 'ownership.json').read_text(encoding='utf-8'))
    with (PLAN / 'assignments.tsv').open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle, delimiter='\t'))
    apis = [row['endpoint'] for row in rows]
    registry = build_registry()
    remaining = {api for api, handler in registry._handlers.items()
                 if handler.__module__ == 'app.business.placeholders'}
    assert len(apis) == len(set(apis)) == 331, 'duplicate or missing rows'
    assert set(apis) == remaining, {'missing': sorted(remaining - set(apis)),
                                   'stale': sorted(set(apis) - remaining)}
    assert Counter(row['group'] for row in rows) == summary['groups']
    assert len(registry.known()) == 402
    # Git may check TSV files out as CRLF on Windows; content identity uses LF.
    assignment_bytes = (PLAN / 'assignments.tsv').read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(assignment_bytes).hexdigest() == summary['assignment_sha256']
    by_api = {row['endpoint']: row['group'] for row in rows}
    for api, owner in ownership['transfers'].items():
        assert by_api[api] == owner
    files = {}
    for group, meta in ownership['groups'].items():
        task = (PLAN / meta['task_file']).read_text(encoding='utf-8')
        listed = re.findall(r'^\d+\. ((?:[A-Za-z][A-Za-z0-9_]*/)+[A-Za-z0-9_]+)$', task, re.MULTILINE)
        assigned = sorted(row['endpoint'] for row in rows if row['group'] == group)
        assert sorted(listed) == assigned, f'{group}: task list mismatch'
        assert f'任务 {group}：' in task and meta['worktree'] in task and meta['branch'] in task
        assert f'{meta["count"]} 个占位入口' in task
        for name in meta['files']:
            assert name not in files and name not in ownership['shared_integrator_only'], name
            files[name] = group
    assert all(by_api[api] == 'I' for api in apis if api.startswith(('debug/', 'admin/')))
    assert sum(api.startswith(('debug/', 'admin/')) for api in apis) == 32
    return {'registered': 402, 'placeholders': 331, 'gameplay': 299, 'debug_admin': 32,
            'counts': summary['groups'], 'duplicate_endpoints': 0,
            'missing_endpoints': 0, 'duplicate_edit_owners': 0}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
