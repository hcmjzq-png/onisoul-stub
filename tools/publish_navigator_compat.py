"""Publish only the 71 missing navigator image bundles, without replacements.

The release carries all 80 expected image fingerprints but only 71 new files.
It never publishes voices or changes game code, SQL, configuration or services.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


ORIGINALS = {('navi8000201', 1, 'bust')} | {
    ('navi8000601', color, 'bust') for color in (1, 2, 4)
} | {('navi8000601', color, 'icon') for color in range(1, 6)}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_plan(plan: dict) -> list[dict]:
    rows = plan['files']
    expected = {(f'navi8000{family}01', color, role)
                for family in range(1, 9) for color in range(1, 6) for role in ('bust', 'icon')}
    if (plan.get('schema') != 1 or plan.get('kind') != 'navigator_compatibility_candidate'
            or len(rows) != 80 or len({r['relative'] for r in rows}) != 80
            or {(r['navigator'], r['color'], r['role']) for r in rows} != expected):
        raise ValueError('expected the 80 distinct PC navigator image identities')
    for row in rows:
        nid, color, role = row['navigator'], row['color'], row['role']
        family = nid[8]
        name = f'cch1_8000{family}_0{color}_3_01' if role == 'bust' else f'item12_8000{family}0{color}'
        category = 'cch' if role == 'bust' else 'item'
        relative = category + '/' + hashlib.md5(name.encode('utf-16le')).hexdigest() + '.unity3d'
        original = (nid, color, role) in ORIGINALS
        textures = ({name: (1024, 1024)} if role == 'bust' else
                    {name + '_01': (64, 64), name + '_02': (128, 128)})
        supplied = {t['name']: (t['width'], t['height']) for t in row['textures']}
        if (type(color) is not int or type(row['preserved_original']) is not bool
                or row['preserved_original'] != original or row['relative'] != relative
                or row['url'] != '/client/pc/jp/assets/' + relative
                or supplied != textures or len(row['textures']) != len(textures)
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= 16 * 1024 * 1024
                or row['provenance'] != ('original_pc_preserved' if original else 'ai_reference_compatibility')):
            raise ValueError('invalid navigator identity, provenance or fingerprint')
    return rows


def safe_file(root: Path, relative: str) -> Path:
    if not re.fullmatch(r'(?:cch|item)/[0-9a-f]{32}\.unity3d', relative):
        raise ValueError('unexpected navigator image path')
    path = root / relative
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('symlink in publication path')
        if part == root:
            break
    path.resolve().relative_to(root)
    return path


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def verify_snapshot(root: Path, before: dict[str, str]) -> None:
    for relative, digest in before.items():
        path = root / relative
        if not path.is_file() or sha(path) != digest:
            raise ValueError('pre-existing asset changed: ' + relative)


def install(release: Path, assets: Path, backups: Path, *, resolve=None, verify_http=None) -> dict:
    release, assets = release.resolve(), assets.resolve()
    bundle_root = assets / 'bundles'
    if not bundle_root.is_dir():
        raise ValueError('existing PC asset and bundle roots required')
    rows = validate_plan(json.loads((release / 'manifest.json').read_text(encoding='utf-8')))

    def resolved(row):
        if resolve is not None:
            return resolve(row['url'])
        target = safe_file(bundle_root, row['relative'])
        return target if target.is_file() else None

    # Validate the complete upload and every effective existing URL before any
    # file is published, including originals served from the cache fallback.
    for row in rows:
        target = safe_file(bundle_root, row['relative'])
        if not row['preserved_original']:
            source = safe_file(release / 'bundles', row['relative'])
            if source.stat().st_size != row['bytes'] or sha(source) != row['sha256']:
                raise ValueError('uploaded navigator bundle changed')
        existing = resolved(row)
        if existing is not None:
            if Path(existing).stat().st_size != row['bytes'] or sha(Path(existing)) != row['sha256']:
                raise ValueError('existing resource differs; refusing replacement: ' + row['relative'])
        elif row['preserved_original']:
            raise ValueError('existing original is missing: ' + row['relative'])
        if target.exists() and sha(target) != row['sha256']:
            raise ValueError('target differs; refusing replacement')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = backups / ('navigator-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    before = snapshot(assets)
    (backup / 'assets-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    shutil.copyfile(release / 'manifest.json', backup / 'manifest.json')
    stage = Path(tempfile.mkdtemp(prefix='.navigator-', dir=assets.parent))
    created = []
    try:
        for row in rows:
            if row['preserved_original']:
                continue
            staged = stage / Path(row['relative']).name
            shutil.copyfile(safe_file(release / 'bundles', row['relative']), staged)
            if sha(staged) != row['sha256']:
                raise ValueError('navigator source changed while staging')
            os.chmod(staged, 0o644)
        for row in rows:
            if row['preserved_original']:
                continue
            target = safe_file(bundle_root, row['relative'])
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = stage / Path(row['relative']).name
            try:
                os.link(staged, target)  # Atomic create-only; never replace.
            except FileExistsError:
                if target.is_symlink() or sha(target) != row['sha256']:
                    raise ValueError('concurrent navigator change; refusing replacement')
            else:
                created.append((target, staged))
                (backup / 'created.json').write_text(json.dumps([
                    dict(relative=p.relative_to(assets).as_posix(), sha256=sha(p))
                    for p, _ in created], indent=2), encoding='utf-8')
        for row in rows:
            existing = resolved(row)
            if existing is None or sha(Path(existing)) != row['sha256']:
                raise ValueError('published URL resolves to different bytes')
        http_count = verify_http(rows) if verify_http is not None else 0
        verify_snapshot(assets, before)
        result = dict(installed=len(created), image_bundles_verified=80, originals_preserved=9,
                      pre_existing_files_preserved=len(before), http_verified=http_count,
                      voices_uploaded=0, backup=str(backup), success=True)
        (backup / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    except BaseException:
        for target, staged in reversed(created):
            if target.is_file() and not target.is_symlink() and os.path.samestat(target.stat(), staged.stat()):
                target.unlink()
        verify_snapshot(assets, before)
        (backup / 'rolled-back.json').write_text(json.dumps([
            p.relative_to(assets).as_posix() for p, _ in created]), encoding='utf-8')
        raise
    finally:
        stage.resolve().relative_to(assets.parent)
        if not stage.name.startswith('.navigator-'):
            raise ValueError('unexpected staging directory')
        shutil.rmtree(stage)
