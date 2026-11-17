"""Add the 27 rebuilt country bundles, refusing to replace any existing asset.

The release directory contains manifest.json (all 47 fingerprints) and only the
27 rebuilt files. Existing PC originals and every unrelated file are hashed
before and after publication. Run on the asset filesystem; no service restart.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    if not re.fullmatch(r'bundles/chara/[0-9a-f]{32}\.unity3d', relative):
        raise ValueError('unexpected country path')
    path = root / relative
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise ValueError('symlink in country path')
    path.resolve().relative_to(root)
    return path


def validate_plan(plan: dict) -> list[dict]:
    rows = plan['files']
    if (len(rows) != 47 or {r['country'] for r in rows} != {f'country{i:02d}' for i in range(1, 48)}
            or len({r['relative'] for r in rows}) != 47
            or len({r['archive'] for r in rows}) != 47
            or any(type(r['reconstructed']) is not bool for r in rows)
            or sum(r['reconstructed'] for r in rows) != 27):
        raise ValueError('expected 20 original and 27 rebuilt distinct countries')
    for row in rows:
        expected = hashlib.md5(row['image'].encode('utf-16le')).hexdigest()
        if (row['relative'] != f'bundles/chara/{expected}.unity3d'
                or not re.fullmatch(r'chara\d+_\d+_\d+', row['image'])
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or not re.fullmatch(r'CustomAssetBundle-[0-9a-f]{32}', row['archive'])
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= 16 * 1024 * 1024):
            raise ValueError('invalid country identity/fingerprint')
    return rows


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def verify_snapshot(root: Path, before: dict[str, str]) -> None:
    for relative, digest in before.items():
        if sha(root / relative) != digest:
            raise ValueError('pre-existing asset changed: ' + relative)


def install(release: Path, assets: Path, backup_root: Path) -> dict:
    release, assets = release.resolve(), assets.resolve()
    if not assets.is_dir():
        raise ValueError('asset root must already exist')
    plan = json.loads((release / 'manifest.json').read_text(encoding='utf-8'))
    rows = validate_plan(plan)
    # Validate all input bytes and all existing countries before publishing any.
    for row in rows:
        target = safe_path(assets, row['relative'])
        if row['reconstructed']:
            source = safe_path(release, row['relative'])
            if source.stat().st_size != row['bytes'] or sha(source) != row['sha256']:
                raise ValueError('release fingerprint changed: ' + row['country'])
        if target.exists():
            if target.stat().st_size != row['bytes'] or sha(target) != row['sha256']:
                raise ValueError('existing country fingerprint differs; refusing replacement: ' + row['country'])
        elif not row['reconstructed']:
            raise ValueError('missing original PC country: ' + row['country'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_root / ('country81-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    before = snapshot(assets)
    (backup / 'assets-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    (backup / 'manifest.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    created: list[tuple[Path, Path]] = []
    stage = Path(tempfile.mkdtemp(prefix='.country81-', dir=assets.parent))
    try:
        for row in rows:
            if not row['reconstructed']:
                continue
            staged = stage / row['country']
            shutil.copyfile(safe_path(release, row['relative']), staged)
            if sha(staged) != row['sha256']:
                raise ValueError('source changed while staging')
            os.chmod(staged, 0o644)
        for row in rows:
            if not row['reconstructed']:
                continue
            target = safe_path(assets, row['relative'])
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = stage / row['country']
            try:
                os.link(staged, target)  # atomic create-only, never os.replace
            except FileExistsError:
                if target.is_symlink() or sha(target) != row['sha256']:
                    raise ValueError('concurrent country change; refusing replacement')
            else:
                created.append((target, staged))
                (backup / 'created.json').write_text(json.dumps([
                    p.relative_to(assets).as_posix() for p, _ in created]), encoding='utf-8')
        verify_snapshot(assets, before)
        for row in rows:
            if sha(safe_path(assets, row['relative'])) != row['sha256']:
                raise ValueError('published country fingerprint mismatch')
        result = dict(installed=len(created), countries_verified=47, originals_preserved=20,
                      pre_existing_files_preserved=len(before), backup=str(backup), success=True)
        (backup / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    except BaseException:
        for target, staged in reversed(created):
            if target.exists() and not target.is_symlink() and os.path.samestat(target.stat(), staged.stat()):
                target.unlink()
        verify_snapshot(assets, before)
        (backup / 'rolled-back.json').write_text(json.dumps([p.relative_to(assets).as_posix() for p, _ in created]), encoding='utf-8')
        raise
    finally:
        shutil.rmtree(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.release, args.assets, args.backup_root)))
