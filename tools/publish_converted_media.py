#!/usr/bin/env python3
"""Package verified media and publish additively without replacing PC assets.

Every variant is served under converted/pr69. Only unambiguous PS3 AudioClips
named vse... are also linked to the client's original UTF-16LE/MD5 voice URL.
Standalone textures must never masquerade as complete building/scene bundles.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.probe_legacy_media import ENGINE_SHA256, validate_results
from tools.media_http import verify_url

PREFIX = 'converted/pr69'
HEX = re.compile(r'[0-9a-f]{64}')
VOICE = re.compile(r'vse\d+_\d+_\d+_\d+_\d+')


def sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def canonical_voice(row: dict) -> str | None:
    if row['family'] == 'PS3' and row.get('source_platform') == 10 and row['kind'] == 'AudioClip' and VOICE.fullmatch(row['name']):
        return 'vse/' + hashlib.md5(row['name'].encode('utf-16le')).hexdigest() + '.unity3d'
    return None


def archive_relative(row: dict) -> str:
    if not HEX.fullmatch(row['id']) or row['family'] not in ('PS3', 'Android') or row['kind'] not in ('AudioClip', 'Texture2D'):
        raise ValueError('invalid media identity')
    return f"{PREFIX}/{row['family'].lower()}/{row['kind'].lower()}/{row['id']}.unity3d"


def build(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError('archive already exists')
    rows = json.loads(args.manifest.read_text(encoding='utf-8'))['converted']
    evidence = json.loads(args.native.read_text(encoding='utf-8'))
    if evidence['engine_sha256'] != ENGINE_SHA256:
        raise ValueError('native engine fingerprint mismatch')
    validate_results(rows, evidence['events'])
    files = []
    promoted = set()
    for row in rows:
        relative = archive_relative(row)
        source = Path(row['output'])
        if sha(source) != row['output_sha256'] or source.stat().st_size != row['output_bytes']:
            raise ValueError('converted file changed: ' + row['name'])
        canonical = canonical_voice(row)
        if canonical and canonical in promoted:
            raise ValueError('ambiguous canonical voice URL')
        if canonical:
            promoted.add(canonical)
        files.append(dict(id=row['id'], family=row['family'], kind=row['kind'], name=row['name'],
            source_platform=row['source_platform'],
            relative=relative, canonical=canonical, member=f"blobs/{row['id']}.unity3d",
            bytes=row['output_bytes'], sha256=row['output_sha256']))
    movie = json.loads(args.movie_proof.read_text(encoding='utf-8'))
    if not movie['decoded_frames_and_timestamps_identical'] or sha(Path(movie['output'])) != movie['output_sha256']:
        raise ValueError('movie verification failed')
    plan = dict(schema=1, prefix=PREFIX, engine_sha256=ENGINE_SHA256, files=files,
        native_evidence_sha256=sha(args.native), movie=dict(relative=f'{PREFIX}/movie/movie.mpg', member='movie.mpg',
            bytes=movie['output_bytes'], sha256=movie['output_sha256'], frames=movie['frames']))
    payload = json.dumps(plan, ensure_ascii=False, separators=(',', ':')).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'x') as archive:
        info = tarfile.TarInfo('manifest.json'); info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        for row, record in zip(rows, files):
            archive.add(row['output'], arcname=record['member'], recursive=False)
        archive.add(movie['output'], arcname='movie.mpg', recursive=False)
    args.plan.write_bytes(payload + b'\n')
    print(json.dumps(dict(media=len(files), canonical_voice_candidates=len(promoted), movie=1,
                          archive_bytes=args.output.stat().st_size, archive_sha256=sha(args.output))))


def snapshot(roots: list[Path]) -> list[dict]:
    return [dict(path=str(path), sha256=sha(path)) for root in roots for path in sorted(root.rglob('*')) if path.is_file()]


def verify_snapshot(records: list[dict]) -> None:
    for row in records:
        if sha(Path(row['path'])) != row['sha256']:
            raise ValueError('pre-existing PC asset changed: ' + row['path'])


def install(args: argparse.Namespace) -> None:
    from app.transport.static import StaticFiles
    root = args.bundle_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    resolver = StaticFiles(bundle_dir=root, cache_dir=args.cache_root)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup = args.backup_root / ('media69-' + stamp)
    backup.mkdir(mode=0o700, parents=True)
    before = snapshot([root, args.cache_root.resolve()])
    (backup / 'original-assets.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    created = []
    kept = []
    requests = []
    stage = Path(tempfile.mkdtemp(prefix='.oni69-', dir=root.parent))
    def link(source: Path, relative: str, expected: str) -> bool:
        parts = PurePosixPath(relative)
        if parts.is_absolute() or any(p in ('.', '..') for p in parts.parts) or '\\' in relative:
            raise ValueError('unsafe publication path')
        target = (root / Path(*parts.parts)).resolve()
        target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except FileExistsError:
            if sha(target) != expected:
                raise ValueError('existing archive file differs: ' + relative)
            return False
        created.append(dict(relative=relative, path=str(target), sha256=expected))
        return True
    try:
        with tarfile.open(args.archive, 'r:') as archive:
            manifest = archive.extractfile('manifest.json')
            if manifest is None:
                raise ValueError('missing manifest')
            payload = manifest.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError('manifest too large')
            plan = json.loads(payload)
            if plan['schema'] != 1 or plan['prefix'] != PREFIX or plan['engine_sha256'] != ENGINE_SHA256:
                raise ValueError('unexpected publication schema')
            records = list(plan['files']) + [plan['movie']]
            expected_members = {'manifest.json', *(r['member'] for r in records)}
            members = archive.getmembers()
            if len(members) != len(expected_members) or {m.name for m in members} != expected_members or any(not m.isfile() for m in members):
                raise ValueError('unexpected archive members')
            voices = set()
            for row in plan['files']:
                if row['relative'] != archive_relative(row) or row['member'] != f"blobs/{row['id']}.unity3d":
                    raise ValueError('media path does not match identity')
                if row['canonical'] != canonical_voice(row):
                    raise ValueError('unsafe canonical resource type')
                if row['canonical'] and row['canonical'] in voices:
                    raise ValueError('ambiguous canonical voice URL')
                if row['canonical']:
                    voices.add(row['canonical'])
            if plan['movie']['relative'] != f'{PREFIX}/movie/movie.mpg' or plan['movie']['member'] != 'movie.mpg':
                raise ValueError('unsafe movie path')
            for index, row in enumerate(records):
                member = archive.getmember(row['member'])
                if member.size != row['bytes'] or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
                    raise ValueError('invalid member length/digest')
                staged = stage / str(index)
                with staged.open('xb') as target, archive.extractfile(member) as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                if sha(staged) != row['sha256']:
                    raise ValueError('uploaded file digest mismatch')
                os.chmod(staged, 0o644)
                row['_staged'] = staged
            # Validate every staged byte before making any new URL visible.
            for row in records:
                link(row['_staged'], row['relative'], row['sha256'])
                requests.append(dict(relative=row['relative'], sha256=row['sha256']))
            canonical_added = 0
            for row in plan['files']:
                relative = row['canonical']
                if not relative:
                    continue
                existing = resolver.resolve('/client/pc/jp/assets/' + relative)
                if existing is not None:
                    kept.append(dict(relative=relative, path=str(existing.path), sha256=sha(existing.path)))
                    requests.append(dict(relative=relative, sha256=sha(existing.path)))
                    continue
                if link(root / row['relative'], relative, row['sha256']):
                    canonical_added += 1
                requests.append(dict(relative=relative, sha256=row['sha256']))
            for row in records:
                row.pop('_staged')
            index_file = stage / 'index.json'
            index_file.write_bytes(json.dumps(plan, ensure_ascii=False, separators=(',', ':')).encode())
            os.chmod(index_file, 0o644)
            index_relative = PREFIX + '/index.json'
            link(index_file, index_relative, sha(index_file))
            requests.append(dict(relative=index_relative, sha256=sha(index_file)))
        def check(row: dict) -> int:
            return verify_url(f'http://{args.http_host}:{args.http_port}/client/pc/jp/assets/' + row['relative'], row['sha256'])
        with ThreadPoolExecutor(max_workers=getattr(args, 'http_workers', 4)) as pool:
            retries = sum(pool.map(check, requests))
        verify_snapshot(before)
        result = dict(media=len(plan['files']), movie=1, new_files=len(created), canonical_voice_added=canonical_added,
            canonical_existing_preserved=len(kept), original_files_preserved=len(before), http_verified=len(requests),
            backup=str(backup), archive_sha256=sha(args.archive), http_transient_retries=retries, success=True)
        (backup / 'created.json').write_text(json.dumps(created, indent=2))
        (backup / 'kept.json').write_text(json.dumps(kept, indent=2))
        (backup / 'result.json').write_text(json.dumps(result, indent=2))
        args.result.write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    except BaseException:
        for row in reversed(created):
            path = Path(row['path'])
            if path.is_file() and sha(path) == row['sha256']:
                path.unlink()
        verify_snapshot(before)
        (backup / 'rolled-back.json').write_text(json.dumps(created, indent=2))
        raise
    finally:
        stage.resolve().relative_to(root.parent)
        if not stage.name.startswith('.oni69-'):
            raise ValueError('unexpected staging directory')
        shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    builder = sub.add_parser('build')
    for name in ('manifest', 'native', 'movie-proof', 'output', 'plan'):
        builder.add_argument('--' + name, type=Path, required=True)
    installer = sub.add_parser('install')
    for name in ('archive', 'bundle-root', 'cache-root', 'backup-root', 'result'):
        installer.add_argument('--' + name, type=Path, required=True)
    installer.add_argument('--http-host', default='127.0.0.1')
    installer.add_argument('--http-port', type=int, default=80)
    installer.add_argument('--http-workers', type=int, default=4)
    args = parser.parse_args()
    build(args) if args.action == 'build' else install(args)


if __name__ == '__main__':
    main()
