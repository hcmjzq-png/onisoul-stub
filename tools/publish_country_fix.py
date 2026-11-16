"""Replace only fingerprinted country bundles and the PC app; back up first."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(release, assets, backup_root):
    release, assets = release.resolve(), assets.resolve()
    plan = json.loads((release / 'manifest.json').read_text(encoding='utf-8'))
    rows = plan['files']
    if len(rows) != 20 or len({r['relative'] for r in rows}) != 20:
        raise ValueError('expected twenty distinct country bundles')
    for row in rows:
        if not re.fullmatch(r'bundles/chara/[0-9a-f]{32}\.unity3d', row['relative']):
            raise ValueError('unexpected country path')
    if plan['app_relative'] != 'web/client/app.unity3d':
        raise ValueError('unexpected app path')
    app = dict(relative=plan['app_relative'], before_sha256=plan['original_app_sha256'], sha256=plan['app_sha256'])
    # Validate the complete set before touching any live file. App is published last.
    all_rows = rows + [app]
    for row in all_rows:
        source, target = release / row['relative'], assets / row['relative']
        if source.is_symlink() or target.is_symlink() or not target.resolve().is_relative_to(assets):
            raise ValueError('symlink or path outside assets')
        if sha(source) != row['sha256'] or sha(target) != row['before_sha256']:
            raise ValueError('source/live fingerprint changed: ' + row['relative'])
    changed = [r for r in all_rows if r['before_sha256'] != r['sha256']]
    backup = backup_root / ('country76-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, mode=0o700)
    for row in changed:
        saved = backup / row['relative']
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(assets / row['relative'], saved)
        if sha(saved) != row['before_sha256']:
            raise ValueError('backup fingerprint mismatch')
    (backup / 'manifest.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    installed = []
    try:
        for row in changed:
            target = assets / row['relative']
            fd, name = tempfile.mkstemp(prefix='.country76-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write((release / row['relative']).read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                shutil.copystat(target, name)
                if sha(target) != row['before_sha256']:
                    raise ValueError('live file changed during staging: ' + row['relative'])
                os.replace(name, target)
                installed.append(row)
            finally:
                if Path(name).exists():
                    Path(name).unlink()
        for row in all_rows:
            if sha(assets / row['relative']) != row['sha256']:
                raise ValueError('installed fingerprint mismatch')
    except BaseException:
        for row in reversed(installed):
            target = assets / row['relative']
            if sha(target) != row['sha256']:
                raise RuntimeError('concurrent change; refusing to overwrite: ' + str(target))
            fd, name = tempfile.mkstemp(prefix='.country76-rollback-', dir=target.parent)
            os.close(fd)
            shutil.copy2(backup / row['relative'], name)
            os.replace(name, target)
        raise
    result = dict(backup=str(backup), installed=len(changed), untouched=len(all_rows)-len(changed),
                  app_sha256=plan['app_sha256'], assets_verified=len(rows))
    (backup / 'installed.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--assets', type=Path, required=True)
    ap.add_argument('--backup-root', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(install(args.release, args.assets, args.backup_root)))
