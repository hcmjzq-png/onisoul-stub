"""Copy a read-only PC asset snapshot over SSH and verify every file digest.

Copies bundles/tables/web only. Never exports accounts, sessions, saves, database
credentials, or service environment files. Requires a new destination directory.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-target', required=True)
    parser.add_argument('--remote-root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse-manifest', action='store_true')
    parser.add_argument('--local-cache', type=Path, action='append', default=[])
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be a new directory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output.parent / 'pc-source-manifest.json'
    archive_path = args.output.parent / 'pc-delta.tar.gz'
    if archive_path.exists() or (manifest_path.exists() and not args.reuse_manifest):
        parser.error('snapshot evidence already exists; reuse requires explicit --reuse-manifest')
    source = """import hashlib,json,pathlib
root=pathlib.Path(REMOTE_ROOT)
rows=[]
for category in ['bundles','tables','web']:
 for path in sorted((root/category).rglob('*')):
  if path.is_file():
   h=hashlib.sha256()
   with path.open('rb') as f:
    for block in iter(lambda:f.read(1048576),b''):h.update(block)
   rows.append(dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=h.hexdigest()))
print(json.dumps(rows))
""".replace('REMOTE_ROOT', repr(args.remote_root))
    if not args.reuse_manifest:
        with manifest_path.open('wb') as output:
            subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh_target, 'python3 -'],
                input=source.encode(), stdout=output, check=True)
    rows = json.loads(manifest_path.read_text(encoding='utf-8'))
    print('Source snapshot:', len(rows), 'files;', sum(row['bytes'] for row in rows), 'bytes', flush=True)
    args.output.mkdir()
    root = args.output.resolve()
    wanted = {row['sha256']: row for row in rows}
    def asset_key(name, size):
        match = re.search(r'([0-9a-f]{32}\.unity3d)$', name.lower())
        return (match.group(1) if match else name.lower(), size)
    keys = {asset_key(Path(row['path']).name, row['bytes']) for row in rows}
    available = {}
    skipped = {'.git', '.venv', 'node_modules', 'py313', 'pylibs', '__pycache__', 'jdk', 'dotnet'}
    def digest(path):
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1048576), b''):
                h.update(block)
        return h.hexdigest()
    checked = set()
    for cache in args.local_cache:
        if not cache.is_dir():
            continue
        for folder, directories, files in os.walk(cache):
            directories[:] = [d for d in directories if d not in skipped]
            for name in files:
                path = Path(folder) / name
                try:
                    if path.is_symlink() or asset_key(name, path.stat().st_size) not in keys:
                        continue
                    normalized = str(path.resolve()).casefold()
                    if normalized in checked:
                        continue
                    checked.add(normalized)
                    sha = digest(path)
                    if sha in wanted:
                        available.setdefault(sha, path)
                except OSError:
                    continue
        print('Local cache matches:', len(available), '/', len(wanted), flush=True)
    cached_count = len(available)
    missing = [row for sha, row in wanted.items() if sha not in available]
    print('Remote delta:', len(missing), 'files;', sum(row['bytes'] for row in missing), 'bytes', flush=True)
    if missing:
        command = 'tar --hard-dereference -C ' + shlex.quote(args.remote_root) + ' -czf - --null -T -'
        with archive_path.open('wb') as output:
            subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh_target, command],
                input=b''.join(row['path'].encode() + b'\0' for row in missing), stdout=output, check=True)
        expected = {row['path'] for row in missing}
        with tarfile.open(archive_path, 'r:gz') as archive:
            for member in archive.getmembers():
                candidate = (root / member.name).resolve()
                if not candidate.is_relative_to(root) or not member.isfile() or member.name not in expected:
                    raise ValueError('asset archive contains an unsafe or unexpected entry')
            archive.extractall(root, filter='data')
        for row in missing:
            path = root / row['path']
            if digest(path) != row['sha256']:
                raise ValueError('remote delta digest mismatch: ' + row['path'])
            available[row['sha256']] = path
    for row in rows:
        target = root / row['path']
        if not target.resolve().is_relative_to(root):
            raise ValueError('unsafe manifest path')
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(available[row['sha256']], target)
    def verify(row):
        path = root / row['path']
        if not path.resolve().is_relative_to(root) or path.stat().st_size != row['bytes']:
            raise ValueError('asset path/size mismatch: ' + row['path'])
        h = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1048576), b''):
                h.update(block)
        if h.hexdigest() != row['sha256']:
            raise ValueError('asset digest mismatch: ' + row['path'])
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(verify, rows))
    (args.output.parent / 'pc-source-verification.json').write_text(json.dumps(dict(
        files=len(rows), verified=True, bytes=sum(row['bytes'] for row in rows),
        scope=['bundles', 'tables', 'web'], database_exported=False,
        local_cache_hashes=cached_count, remote_files=len(missing)), indent=2) + '\n', encoding='utf-8')
    print('Verified every asset SHA-256; no player database copied.', flush=True)


if __name__ == '__main__':
    main()
