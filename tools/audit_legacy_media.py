#!/usr/bin/env python3
"""Inventory all PS3 bundles/APK serialized files, then port each distinct medium.

Offline only. A converted Texture2D is not a converted scene/prefab. Deduplication
uses platform, class and exact serialized object bytes, not a guessed filename.
JSON records every source occurrence, failure, output digest and prior reuse.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import convert, digest
from tools.probe_legacy_media import ENGINE_SHA256, validate_results

MEDIA = {'AudioClip', 'Texture2D'}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def object_identity(platform: int, kind: str, raw: bytes) -> str:
    return digest(f'{platform}:{kind}:'.encode() + raw)


def inspect_source(job: dict) -> dict:
    import UnityPy
    blob = Path(job['source']).read_bytes()
    if job.get('member'):
        with zipfile.ZipFile(job['source']) as archive:
            blob = archive.read(job['member'])
    package = dict(job, member_sha256=digest(blob), classes={}, media=[])
    try:
        env = UnityPy.load(blob)
        counts = Counter()
        for obj in env.objects:
            kind = obj.type.name
            counts[kind] += 1
            if kind not in MEDIA:
                continue
            item = dict(source=job['source'], member=job.get('member'),
                        path_id=obj.path_id, kind=kind, platform=int(obj.platform),
                        version=str(obj.assets_file.unity_version))
            try:
                data = obj.read()
                raw = obj.get_raw_data()
                item.update(id=object_identity(item['platform'], kind, raw),
                            object_sha256=digest(raw), name=data.m_Name)
                if kind == 'Texture2D':
                    item.update(width=data.m_Width, height=data.m_Height,
                                texture_format=int(data.m_TextureFormat))
                else:
                    item.update(audio_bytes=len(data.m_AudioData), audio_type=int(data.m_Type))
            except Exception as exc:
                item.update(id=digest(repr(item).encode()), error=f'{type(exc).__name__}: {exc}')
            package['media'].append(item)
        package['classes'] = dict(counts)
        if not counts:
            package['error'] = 'no serialized Unity objects (non-Unity/support file)'
    except Exception as exc:
        package['error'] = f'{type(exc).__name__}: {exc}'
    return package


def scan(args: argparse.Namespace) -> None:
    jobs = []
    extras = []
    for path in sorted(args.ps3_root.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix.lower() == '.unity3d':
            jobs.append(dict(source=str(path.resolve()), family='PS3', member=None))
        else:
            extras.append(dict(source=str(path.resolve()), bytes=path.stat().st_size,
                               sha256=digest(path.read_bytes())))
    apk_sources = []
    seen = {}
    duplicate_members = []
    for path in sorted(args.apk):
        apk_sources.append(dict(source=str(path.resolve()), sha256=digest(path.read_bytes())))
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if (info.is_dir() or not info.filename.startswith('assets/bin/Data/')
                        or '/Managed/' in info.filename):
                    continue
                sha = digest(archive.read(info))
                occurrence = dict(source=str(path.resolve()), member=info.filename, family='Android')
                if sha in seen:
                    duplicate_members.append(dict(**occurrence, same_as=seen[sha]))
                else:
                    seen[sha] = occurrence
                    jobs.append(occurrence)
    packages = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(inspect_source, job) for job in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            packages.append(future.result())
            if index % 1000 == 0:
                print(f'SCAN {index}/{len(jobs)}', flush=True)
    packages.sort(key=lambda row: (row['source'], row['member'] or ''))
    unique = {}
    for package in packages:
        for item in package['media']:
            occurrence = dict(source=item['source'], member=item['member'], path_id=item['path_id'])
            if item['id'] not in unique:
                unique[item['id']] = dict(item, family=package['family'], occurrences=[])
            unique[item['id']]['occurrences'].append(occurrence)
    media = sorted(unique.values(), key=lambda row: (row['family'], row['kind'], row.get('name', ''), row['id']))
    summary = dict(packages=len(packages), distinct_media=len(media),
                   media_by_family_kind=dict(Counter(f"{r['family']}/{r['kind']}" for r in media)),
                   media_occurrences=sum(len(p['media']) for p in packages),
                   classes_by_family={family: dict(sum((Counter(p['classes']) for p in packages
                       if p['family'] == family), Counter())) for family in ('PS3', 'Android')},
                   package_errors=sum('error' in p for p in packages))
    result = dict(schema=1, deduplication='platform + class + exact serialized object bytes',
                  summary=summary, apk_sources=apk_sources, duplicate_apk_members=duplicate_members,
                  extra_ps3_files=extras, packages=packages, media=media)
    write_json(args.output, result)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def port_one(item: dict, options: dict) -> dict:
    try:
        if 'error' in item:
            raise ValueError(item['error'])
        template = Path(options['audio_template'] if item['kind'] == 'AudioClip' else options['texture_template'])
        blob, proof = convert(Path(item['source']), template, item['name'],
                              member=item['member'], path_id=item['path_id'], command=Path(options['ffmpeg']),
                              allow_silent=bool(options.get('allow_silent')),
                              expected_object_sha256=item['object_sha256'])
        if proof['kind'] != item['kind'] or proof['source_platform'] != item['platform']:
            raise ValueError('source class/platform changed since inventory')
        output = Path(options['output_root']) / item['family'].lower() / item['kind'] / (item['id'] + '.unity3d')
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open('xb') as stream:
                stream.write(blob)
        except FileExistsError:
            # A worker may finish writing just before its manifest checkpoint.
            # Reuse only the exact rebuilt bytes, never replace another file.
            if digest(output.read_bytes()) != proof['output_sha256']:
                raise ValueError('existing output differs; choose a fresh output root')
        return dict(id=item['id'], family=item['family'], status='converted', output=str(output.resolve()), **proof)
    except Exception as exc:
        return dict(id=item['id'], family=item['family'], name=item.get('name'), kind=item['kind'],
                    status='failed', error=f'{type(exc).__name__}: {exc}', source=item['source'],
                    member=item['member'], source_path_id=item['path_id'])


def port_all(args: argparse.Namespace) -> None:
    inventory = json.loads(args.inventory.read_text(encoding='utf-8'))
    prior = {}
    if args.prior_manifest:
        for row in json.loads(args.prior_manifest.read_text(encoding='utf-8'))['converted']:
            prior[(row['source'], row.get('member'), row['name'])] = row
    results = []
    if args.output.exists():
        saved = json.loads(args.output.read_text(encoding='utf-8'))
        if saved['inventory_sha256'] != digest(args.inventory.read_bytes()):
            raise ValueError('resume inventory changed; use a different manifest/output root')
        results = saved['results']
        # Resume only verified completed files; failures are retried.
        results = [r for r in results if verified_output(r)]
    done = {row['id'] for row in results}
    pending = []
    for item in inventory['media']:
        if item['id'] in done:
            continue
        old = prior.get((item['source'], item['member'], item.get('name')))
        if old:
            source = Path(item['source'])
            output = args.prior_root / old['output']
            if (digest(source.read_bytes()) == old['source_sha256'] and output.is_file()
                    and digest(output.read_bytes()) == old['output_sha256']
                    and len([r for r in inventory['media'] if r['source'] == item['source']
                             and r['member'] == item['member'] and r.get('name') == item.get('name')]) == 1):
                results.append(dict(old, id=item['id'], family=item['family'], status='reused',
                                    output=str(output.resolve()), source_path_id=item['path_id']))
                continue
        pending.append(item)
    options = {key: str(getattr(args, key).resolve()) for key in
               ('audio_template', 'texture_template', 'ffmpeg', 'output_root')}
    options['allow_silent'] = args.allow_silent
    def save() -> None:
        ordered = sorted(results, key=lambda r: r['id'])
        write_json(args.output, dict(schema=1, inventory_sha256=digest(args.inventory.read_bytes()),
                   summary=dict(Counter(f"{r['family']}/{r['kind']}/{r['status']}" for r in ordered)),
                   results=ordered, converted=[r for r in ordered if r['status'] != 'failed'],
                   failed=[r for r in ordered if r['status'] == 'failed']))
    save()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(port_one, item, options) for item in pending]
        for index, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if index % 100 == 0:
                save()
                print(f'PORT {index}/{len(pending)} failures={sum(r["status"] == "failed" for r in results)}', flush=True)
    save()
    print(json.dumps(Counter(f"{r['family']}/{r['kind']}/{r['status']}" for r in results)), flush=True)


def port_raw(args: argparse.Namespace) -> None:
    """Rebuild standard PNGs too, including Android nine-patch pixel payloads."""
    rows = {}
    sources = [(path, None, 'PS3') for path in sorted(args.ps3_root.rglob('*.png'))]
    for apk in sorted(args.apk):
        with zipfile.ZipFile(apk) as archive:
            sources.extend((apk, info.filename, 'Android') for info in archive.infolist()
                           if info.filename.lower().endswith('.png'))
    for source, member, family in sources:
        if member:
            with zipfile.ZipFile(source) as archive:
                data = archive.read(member)
        else:
            data = source.read_bytes()
        sha = digest(data)
        occurrence = dict(source=str(source), member=member)
        if sha in rows:
            rows[sha]['occurrences'].append(occurrence)
            continue
        blob, proof = convert(source, args.texture_template, Path(member or source.name).stem, member=member)
        output = args.output_root / (sha + '.unity3d')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            stream.write(blob)
        rows[sha] = dict(proof, id=sha, family=family, output=str(output.resolve()), occurrences=[occurrence])
    write_json(args.output, dict(converted=list(rows.values()), failed=[]))
    print(json.dumps(dict(converted=len(rows), by_family=dict(Counter(r['family'] for r in rows.values())))))


def verified_output(row: dict) -> bool:
    if row['status'] not in ('converted', 'reused'):
        return False
    try:
        return digest(Path(row['output']).read_bytes()) == row['output_sha256']
    except OSError:
        return False


def report(args: argparse.Namespace) -> None:
    """Export reviewable evidence after final file hashes/native metadata agree."""
    inventory = json.loads(args.inventory.read_text(encoding='utf-8'))
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if manifest['inventory_sha256'] != digest(args.inventory.read_bytes()):
        raise ValueError('manifest is not bound to this inventory')
    if any(p.get('error') and not p['error'].startswith('no serialized Unity objects')
           for p in inventory['packages']):
        raise ValueError('inventory has unreadable source packages')
    proofs = manifest['converted']
    if manifest['failed'] or {r['id'] for r in proofs} != {r['id'] for r in inventory['media']}:
        raise ValueError('report requires exactly one successful output per inventoried medium')
    native = {}
    history = []
    for path in args.native:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['engine_sha256'] != ENGINE_SHA256:
            raise ValueError('native engine fingerprint mismatch')
        for event in data['events']:
            if 'result' in event:
                native[event['result']['id']] = event['result']
            elif 'error' in event:
                history.append(event)
                native.pop(event['id'], None)
    validate_results(proofs, [dict(result=result) for result in native.values()])
    indexed = {row['id']: row for row in inventory['media']}
    previous_keys = {(o['source'], o['member'], row['name']): row['id']
                     for row in inventory['media'] for o in row['occurrences']}
    previous = set()
    for row in json.loads(args.prior_manifest.read_text(encoding='utf-8'))['converted']:
        if row['source_platform'] in (10, 13):
            previous.add(previous_keys[(row['source'], row.get('member'), row['name'])])
    def label(source: str, member: str | None = None) -> str:
        return (Path(source).name + '!' + member if member else
                Path(source).relative_to(args.ps3_root).as_posix())
    def tsv(name: str, rows: list[dict]) -> None:
        if not rows:
            return
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with (args.output_dir / name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter='\t', lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    names = Counter((r['family'], r['kind'], r['name']) for r in proofs)
    media_rows = []
    for row in sorted(proofs, key=lambda r: (r['family'], r['kind'], r['name'], r['id'])):
        if (digest(Path(row['output']).read_bytes()) != row['output_sha256']
                or Path(row['output']).stat().st_size != row['output_bytes']):
            raise ValueError('final output changed: ' + row['name'])
        original = indexed[row['id']]
        media_rows.append(dict(id=row['id'], family=row['family'], kind=row['kind'], name=row['name'],
            source_platform=original['platform'], source_object_sha256=original['object_sha256'],
            source=label(original['source'], original['member']), path_id=original['path_id'],
            occurrences=len(original['occurrences']), name_variants=names[(row['family'], row['kind'], row['name'])],
            previously_converted=row['id'] in previous, status=row['status'],
            output_sha256=row['output_sha256'], output_bytes=row['output_bytes'],
            pc_archive=row['pc_archive'], pc_platform=row['pc_platform'], pc_version=row['pc_version'],
            texture_format=row.get('pc_texture_format', ''), width=row.get('width', ''), height=row.get('height', ''),
            pixel_mae=row.get('pixel_mae', ''), sample_rate=row.get('sample_rate', ''), channels=row.get('channels', ''),
            source_samples=row.get('source_samples', ''), ogg_samples=native[row['id']].get('samples', ''),
            snr_db=row.get('decoded_snr_db', ''), source_silent=row.get('source_silent', False),
            ffmpeg_padding_samples=row.get('ffmpeg_padding_samples', 0),
            native_loaded=native[row['id']]['loaded'], native_playback_finished=native[row['id']].get('playback_finished', False)))
    tsv('media.tsv', media_rows)
    tsv('occurrences.tsv', [dict(id=row['id'], source=label(o['source'], o['member']), path_id=o['path_id'])
                          for row in inventory['media'] for o in row['occurrences']])
    tsv('packages.tsv', [dict(family=p['family'], source=label(p['source'], p['member']),
        sha256=p['member_sha256'], objects=sum(p['classes'].values()), media=len(p['media']),
        classes=json.dumps(p['classes'], sort_keys=True, separators=(',', ':')),
        excluded_or_error=p.get('error', '-')) for p in inventory['packages']])
    blocked = [p for p in inventory['packages'] if p['family'] == 'PS3'
               and Path(p['source']).parent.name in ('building', 'scene')]
    tsv('unported-containers.tsv', [dict(source=label(p['source']),
        category=Path(p['source']).parent.name, reason='object graph/mesh/material/shader/script rebuild not implemented',
        extracted_media=len(p['media'])) for p in blocked])
    tsv('native-initial-failures.tsv', [dict(id=e['id'], name=e['name'], error=e['error'],
        final_loaded=native[e['id']]['loaded']) for e in history])
    raw = []
    if args.raw_manifest and args.raw_native:
        raw_manifest = json.loads(args.raw_manifest.read_text(encoding='utf-8'))
        raw = raw_manifest['converted']
        raw_native = json.loads(args.raw_native.read_text(encoding='utf-8'))
        if raw_manifest.get('failed') or raw_native['engine_sha256'] != ENGINE_SHA256:
            raise ValueError('raw image conversion/native fingerprint failed')
        raw_events = raw_native['events']
        validate_results(raw, raw_events)
        for row in raw:
            if digest(Path(row['output']).read_bytes()) != row['output_sha256']:
                raise ValueError('raw image output changed')
        tsv('raw-images.tsv', [dict(id=r['id'], family=r['family'], name=r['name'], source=r['source'],
            member=r['member'], width=r['width'], height=r['height'], source_sha256=r['member_sha256'],
            output_sha256=r['output_sha256'], output_bytes=r['output_bytes'], pc_texture_format=r['pc_texture_format'],
            pixel_mae=r['pixel_mae'], native_loaded=True, occurrences=len(r['occurrences'])) for r in raw])
    snr = [r['decoded_snr_db'] for r in proofs if r.get('decoded_snr_db') is not None]
    summary = dict(schema=1, unit='distinct serialized AudioClip/Texture2D per platform',
        deduplication=inventory['deduplication'], inventory_sha256=digest(args.inventory.read_bytes()),
        manifest_sha256=digest(args.manifest.read_bytes()),
        inputs=dict(ps3_root=str(args.ps3_root.resolve()), ps3_bundles=sum(p['family'] == 'PS3' for p in inventory['packages']),
                    apk_sources=inventory['apk_sources'], unique_apk_members=len([p for p in inventory['packages']
                    if p['family'] == 'Android']), duplicate_apk_members=len(inventory['duplicate_apk_members'])),
        media_counts=inventory['summary']['media_by_family_kind'], total=len(proofs), previous=len(previous),
        newly_available=len(proofs) - len(previous), new_final_files=sum(r['status'] == 'converted' for r in proofs),
        reused_files=sum(r['status'] == 'reused' for r in proofs), conversion_failures=len(manifest['failed']),
        output_bytes=sum(r['output_bytes'] for r in proofs), native_loaded=len(native),
        native_engine_sha256=ENGINE_SHA256, native_playback_finished=sum(r.get('playback_finished', False) for r in native.values()),
        initial_native_failures=len(history), silent_source_placeholders=sum(r.get('source_silent', False) for r in proofs),
        rgba_fallbacks=sum('bc3_fallback_mae' in r for r in proofs), min_audio_snr_db=min(snr),
        full_ps3_containers_unported=dict(Counter(Path(p['source']).parent.name for p in blocked)),
        classes_by_family=inventory['summary']['classes_by_family'], ps3_extra_files=inventory['extra_ps3_files'],
        native_evidence=[dict(path=path.name, sha256=digest(path.read_bytes())) for path in args.native])
    summary.update(raw_png_bundles=len(raw), raw_png_by_family=dict(Counter(r['family'] for r in raw)),
                   all_pc_bundles=len(proofs) + len(raw), all_native_loaded=len(native) + len(raw),
                   all_newly_available=len(proofs) + len(raw) - len(previous))
    if args.targets:
        targets = json.loads(args.targets.read_text(encoding='utf-8'))
        wanted = {r['image'] + suffix for r in targets['rows']
                  for suffix in ('_1_01', '_1_02', '_1_03', '_3_01')}
        wanted |= {a['texture'] for n in targets['navigators'] for c in n['colors'] for a in c['assets'].values()}
        available = {r['name'] for r in proofs if r['kind'] == 'Texture2D'}
        tsv('target-images.tsv', [dict(name=name, source_exact_name_match=name in available) for name in sorted(wanted)])
        summary.update(target_image_names=len(wanted), target_image_source_matches=len(wanted & available),
                       target_table_snapshot_sha256=digest(args.targets.read_bytes()))
    write_json(args.output_dir / 'summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('total', 'previous', 'newly_available', 'conversion_failures', 'native_loaded')}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    scanner = commands.add_parser('scan')
    scanner.add_argument('--ps3-root', type=Path, required=True)
    scanner.add_argument('--apk', type=Path, action='append', required=True)
    scanner.add_argument('--output', type=Path, required=True)
    scanner.add_argument('--workers', type=int, default=4)
    porter = commands.add_parser('port')
    for key in ('inventory', 'audio-template', 'texture-template', 'ffmpeg', 'output-root', 'output'):
        porter.add_argument('--' + key, type=Path, required=True)
    porter.add_argument('--prior-manifest', type=Path)
    porter.add_argument('--prior-root', type=Path, default=Path.cwd())
    porter.add_argument('--workers', type=int, default=4)
    porter.add_argument('--allow-silent', action='store_true', help='Preserve source silence, explicitly marked in proof')
    reporter = commands.add_parser('report')
    for key in ('inventory', 'manifest', 'prior-manifest', 'ps3-root', 'output-dir'):
        reporter.add_argument('--' + key, type=Path, required=True)
    reporter.add_argument('--native', type=Path, action='append', required=True)
    reporter.add_argument('--raw-manifest', type=Path)
    reporter.add_argument('--raw-native', type=Path)
    reporter.add_argument('--targets', type=Path, help='Prior country/navigator coverage snapshot; no HTTP writes')
    raw = commands.add_parser('raw')
    for key in ('ps3-root', 'texture-template', 'output-root', 'output'):
        raw.add_argument('--' + key, type=Path, required=True)
    raw.add_argument('--apk', type=Path, action='append', required=True)
    args = parser.parse_args()
    if args.action == 'scan':
        scan(args)
    elif args.action == 'port':
        port_all(args)
    elif args.action == 'report':
        if bool(args.raw_manifest) != bool(args.raw_native):
            parser.error('--raw-manifest and --raw-native must be supplied together')
        report(args)
    else:
        port_raw(args)


if __name__ == '__main__':
    main()
