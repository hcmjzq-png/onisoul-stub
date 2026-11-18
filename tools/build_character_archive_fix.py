"""Give verified reconstructed character bundles distinct internal file names.

Offline only. Source fingerprints come from the texture/source proof. Preserve
the complete serialized file (all textures, names and container bindings) byte
for byte; only repack its outer UnityWeb directory with a distinct archive name.
Never overwrite inputs or publish files from this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import pack_pc, unpack_pc


def rebuild(data: bytes, logical: str) -> tuple[bytes, dict]:
    if not re.fullmatch(r'chara\d+_\d+_\d+', logical):
        raise ValueError('explicit character logical name required')
    header, old_archive, node = unpack_pc(data)
    archive = 'CustomAssetBundle-' + hashlib.md5(logical.encode('utf-16le') + node).hexdigest()
    result = pack_pc(header, archive, node)
    _, after_archive, after_node = unpack_pc(result)
    if after_archive != archive or after_node != node:
        raise ValueError('serialized character payload changed')
    return result, dict(old_archive=old_archive, archive=archive,
        serialized_sha256=hashlib.sha256(node).hexdigest(), serialized_unchanged=True,
        before_sha256=hashlib.sha256(data).hexdigest(), sha256=hashlib.sha256(result).hexdigest(),
        bytes=len(result))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True, help='Directory of chara__<hash>.unity3d files')
    ap.add_argument('--proof', type=Path, required=True, help='Verified original-TGA reconstruction proof')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise ValueError('output directory must not exist')
    rows = json.loads(args.proof.read_text(encoding='utf-8'))
    files, identities = [], set()
    staged = []
    for row in rows:
        logical = row['cid'] + '_01'
        canonical = hashlib.md5(logical.encode('utf-16le')).hexdigest()
        if row['canonical_hash'] != canonical or logical in identities:
            raise ValueError('character identity/hash mismatch or duplicate')
        identities.add(logical)
        source = args.source / ('chara__' + canonical + '.unity3d')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['bundle_sha256'] or len(data) != row['bytes']:
            raise ValueError('source reconstruction fingerprint mismatch')
        fixed, proof = rebuild(data, logical)
        relative = 'bundles/chara/' + canonical + '.unity3d'
        files.append(dict(logical=logical, relative=relative, textures=row['textures'], **proof))
        staged.append((relative, fixed))
    if not files or len({row['archive'] for row in files}) != len(files):
        raise ValueError('distinct character archives required')
    args.out.mkdir(parents=True)
    for relative, data in staged:
        target = args.out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (args.out / 'manifest.json').write_text(json.dumps({'files': files}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(bundles=len(files), distinct_archives=len(files), serialized_payloads_unchanged=True)))


if __name__ == '__main__':
    main()
