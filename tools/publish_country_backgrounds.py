"""Publish a complete 47-country initial-city background release, create-only.

Requires all 47 files and explicit synthetic provenance. Preserves every existing
asset; a failed filesystem/HTTP check rolls back only files created by this run.
Does not access a database, patch a client, or restart a game/server.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

TEMPLATE_SHA256 = '3b2f6a9ed3af1f8c635bce0103a350489129bfc5cbb4372875089363b61b7e8e'


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def validate_plan(plan: dict) -> list[dict]:
    rows = plan['files']
    if (plan.get('original_template_sha256') != TEMPLATE_SHA256
            or plan.get('generated_art_is_not_original_recovery') is not True
            or len(rows) != 47
            or {r['country'] for r in rows} != {f'country{i:02d}' for i in range(1, 48)}):
        raise ValueError('a complete 47-country release and verified original template are required')
    archives, sources = set(), set()
    for row in rows:
        name = 'pbm' + row['country'][7:] + '_01'
        relative = 'bundles/pbm/' + hashlib.md5(name.encode('utf-16le')).hexdigest() + '.unity3d'
        original = row['country'] == 'country37'
        if (row['logical_name'] != name or row['relative'] != relative
                or row['url'] != '/client/pc/jp/assets/' + relative.removeprefix('bundles/')
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= 8 * 1024 * 1024
                or row['provenance'] != ('original_pc_preserved' if original else 'synthetic_imagegen_shared_original_model')):
            raise ValueError('invalid background identity, provenance or fingerprint')
        if original:
            if row['sha256'] != TEMPLATE_SHA256 or row['proof'].get('original_preserved') is not True:
                raise ValueError('original country37 must be preserved byte-for-byte')
        else:
            proof = row['proof']
            if (proof.get('non_texture_objects_preserved') is not True
                    or not re.fullmatch(r'CustomAssetBundle-[0-9a-f]{32}', proof.get('archive', ''))
                    or not re.fullmatch(r'[0-9a-f]{64}', proof.get('source_sha256', ''))):
                raise ValueError('synthetic background lacks model/source validation')
            archives.add(proof['archive'])
            sources.add(proof['source_sha256'])
    if len(archives) != 46 or len(sources) != 46:
        raise ValueError('each reconstructed country needs distinct art and archive identity')
    return rows


def safe_file(root: Path, relative: str) -> Path:
    if not re.fullmatch(r'bundles/pbm/[0-9a-f]{32}\.unity3d', relative):
        raise ValueError('unexpected background path')
    path = root / relative
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('symlink in publication path')
        if part == root:
            break
    path.resolve().relative_to(root)
    return path


def install(release: Path, assets: Path, backups: Path, *, verify_http=None) -> dict:
    release, assets = release.resolve(), assets.resolve()
    if not assets.is_dir():
        raise ValueError('existing PC asset directory required')
    plan = json.loads((release / 'manifest.json').read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    for row in rows:
        source, target = (safe_file(root, row['relative']) for root in (release, assets))
        if source.stat().st_size != row['bytes'] or sha(source) != row['sha256']:
            raise ValueError('release bytes changed: ' + row['country'])
        if target.exists():
            if target.stat().st_size != row['bytes'] or sha(target) != row['sha256']:
                raise ValueError('existing background differs; refusing replacement: ' + row['country'])
        elif row['country'] == 'country37':
            raise ValueError('existing original country37 is missing')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = backups.resolve() / ('background47-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    before = {p.relative_to(assets).as_posix(): sha(p) for p in assets.rglob('*') if p.is_file()}
    (backup / 'assets-before.json').write_text(json.dumps(before), encoding='utf-8')
    shutil.copyfile(release / 'manifest.json', backup / 'manifest.json')
    stage = Path(tempfile.mkdtemp(prefix='.background47-', dir=assets.parent)).resolve()
    created = []

    def verify_existing():
        for relative, digest in before.items():
            if sha(assets / relative) != digest:
                raise ValueError('pre-existing asset changed: ' + relative)

    try:
        for row in rows:
            target = safe_file(assets, row['relative'])
            if target.exists():
                continue
            staged = stage / row['country']
            shutil.copyfile(safe_file(release, row['relative']), staged)
            if sha(staged) != row['sha256']:
                raise ValueError('source changed during publication')
            os.chmod(staged, 0o644)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(staged, target)  # Atomic create-only; never overwrite.
            except FileExistsError:
                if target.is_symlink() or sha(target) != row['sha256']:
                    raise ValueError('concurrent background change')
            else:
                created.append((target, staged))
                (backup / 'created.json').write_text(json.dumps([
                    p.relative_to(assets).as_posix() for p, _ in created]), encoding='utf-8')
        verify_existing()
        for row in rows:
            if sha(safe_file(assets, row['relative'])) != row['sha256']:
                raise ValueError('published background fingerprint differs')
            if verify_http is not None:
                verify_http(row)
        verify_existing()
        result = dict(success=True, countries_verified=47, installed=len(created),
            originals_preserved=1, pre_existing_files_preserved=len(before),
            http_verified=47 if verify_http else 0, backup=str(backup), database_accessed=False)
        (backup / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    except BaseException:
        for target, staged in reversed(created):
            if target.is_file() and not target.is_symlink() and os.path.samestat(target.stat(), staged.stat()):
                target.unlink()
        verify_existing()
        (backup / 'rolled-back.json').write_text(json.dumps([
            p.relative_to(assets).as_posix() for p, _ in created]), encoding='utf-8')
        raise
    finally:
        # Verify the resolved deletion target is the owned temporary directory.
        if stage.parent != assets.parent or not stage.name.startswith('.background47-') or stage.is_symlink():
            raise ValueError('unsafe staging cleanup path')
        shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path, required=True)
    parser.add_argument('--http-origin', help='Optional HTTP origin for all 47 GET/hash checks')
    parser.add_argument('--environment', choices=['local-test', 'cloud'])
    parser.add_argument('--instance')
    args = parser.parse_args()
    verify = None
    if args.http_origin:
        url = urlsplit(args.http_origin)
        if url.scheme != 'http' or url.path not in ('', '/') or not args.environment or not args.instance:
            parser.error('HTTP checks require an origin and explicit environment/instance')

        def request(path):
            connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=15)
            try:
                connection.request('GET', path)
                response = connection.getresponse()
                if response.status != 200:
                    raise ValueError('HTTP check failed: ' + path)
                return response.read()
            finally:
                connection.close()

        health = json.loads(request('/client/status'))
        if (health.get('service') != 'onisoul-stub' or health.get('environment') != args.environment
                or health.get('instance_id') != args.instance):
            raise ValueError('server identity mismatch; no assets were published')

        def verify(row):
            body = request(row['url'])
            if len(body) != row['bytes'] or hashlib.sha256(body).hexdigest() != row['sha256']:
                raise ValueError('HTTP background fingerprint mismatch: ' + row['country'])

    print(json.dumps(install(args.release, args.assets, args.backup_root, verify_http=verify)))


if __name__ == '__main__':
    main()
