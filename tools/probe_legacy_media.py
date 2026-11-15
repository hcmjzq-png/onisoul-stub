#!/usr/bin/env python3
"""Temporarily load converted bundles in the verified x86 PC WebPlayer.

Requires optional Frida 17 and an already running player. No game APIs, network
requests or save writes. This probe creates muted diagnostic AudioSources for
the selected samples, waits for playback to end and unloads all tested bundles.
The engine fingerprint and every converted file digest are checked first.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.media_http import verify_url

ENGINE_SHA256 = '0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5'


def validate_results(proofs: list[dict], events: list[dict]) -> list[dict]:
    """Match asynchronous native results by ID and verify decoded metadata."""
    loaded = [event['result'] for event in events if 'result' in event]
    errors = [event for event in events if 'error' in event or event.get('type') == 'error']
    if errors or len(loaded) != len(proofs):
        raise RuntimeError(f'native verification failed: {len(loaded)}/{len(proofs)}, {len(errors)} errors')
    by_id = {result['id']: result for result in loaded}
    if len(by_id) != len(proofs):
        raise RuntimeError('duplicate/missing native result IDs')
    for index, row in enumerate(proofs):
        result = by_id[row.get('id', str(index))]
        if row.get('output_sha256') and result.get('output_sha256') != row['output_sha256']:
            raise RuntimeError('native result is not bound to this output digest: ' + row['name'])
        if row.get('url') and result.get('http_preflight_sha256') != row['output_sha256']:
            raise RuntimeError('native HTTP preflight digest mismatch: ' + row['name'])
        if result['name'] != row['name'] or result['kind'] != row['kind'] or not result.get('loaded'):
            raise RuntimeError('native asset identity changed: ' + row['name'])
        if row['kind'] == 'Texture2D':
            if (result['width'], result['height']) != (row['width'], row['height']):
                raise RuntimeError('native texture dimensions changed: ' + row['name'])
        else:
            expected = row.get('ogg_granule_samples', row['source_samples'])
            if (result['frequency'], result['channels'], result['samples']) != (
                    row['sample_rate'], row['channels'], expected):
                raise RuntimeError('native audio metadata changed: ' + row['name'])
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--play', action='append', default=[], help='Exact clip name; muted playback')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=150)
    parser.add_argument('--queue-size', type=int, default=4, help='Bound simultaneous queued bundle bytes')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    proofs = json.loads(args.manifest.read_text(encoding='utf-8'))['converted']
    if args.queue_size < 1:
        parser.error('--queue-size must be positive')
    for row in proofs:
        blob = (args.root / row['output']).read_bytes()
        if hashlib.sha256(blob).hexdigest() != row['output_sha256']:
            raise ValueError('converted file changed: ' + row['name'])
    if not set(args.play) <= {row['name'] for row in proofs}:
        parser.error('--play name is not in the conversion manifest')
    import frida
    session = frida.attach(args.pid)
    events = []
    status = None
    prefetch = None
    checks = None
    if any(row.get('url') for row in proofs):
        def check_http(row: dict) -> int | None:
            if not row.get('url'):
                return None
            return verify_url(row['url'], row['output_sha256'])
        prefetch = ThreadPoolExecutor(max_workers=8)
        checks = [prefetch.submit(check_http, row) for row in proofs]
    def save() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(pid=args.pid, engine_sha256=ENGINE_SHA256,
            status=status, events=events), indent=2), encoding='utf-8')
    try:
        lookup = session.create_script(
            "rpc.exports.path=()=>Process.getModuleByName('webplayer_win.dll').path;")
        lookup.load()
        engine = Path(lookup.exports_sync.path())
        if hashlib.sha256(engine.read_bytes()).hexdigest() != ENGINE_SHA256:
            raise RuntimeError('unsupported engine binary')
        lookup.unload()
        script = session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))
        def receive(message, data):
            event = message['payload'] if message['type'] == 'send' else message
            events.append(event)
        script.on('message', receive)
        script.load()
        try:
            start = time.monotonic()
            submitted = 0
            last_saved = 0
            while time.monotonic() - start < args.timeout:
                status = script.exports_sync.status()
                if submitted < len(proofs) and status['queued'] < args.queue_size:
                    row = proofs[submitted]
                    job = dict(id=row.get('id', str(submitted)), name=row['name'],
                        output_sha256=row['output_sha256'], expected_bytes=row['output_bytes'],
                        url=row.get('url'), play=row['name'] in args.play)
                    if checks:
                        retries = checks[submitted].result()
                        if job['url']:
                            job.update(http_preflight_sha256=row['output_sha256'], http_preflight_retries=retries)
                    script.exports_sync.enqueue(job, b'' if job['url'] else (args.root / row['output']).read_bytes())
                    submitted += 1
                    continue
                finished = sum('result' in event or 'error' in event for event in events)
                if finished >= last_saved + 100:
                    save()
                    last_saved = finished
                    print(f'NATIVE {finished}/{len(proofs)}', flush=True)
                if submitted == len(proofs) and not status['queued'] and not status['current']:
                    break
                time.sleep(.02)
            else:
                raise TimeoutError('native resource probe timed out')
        finally:
            script.exports_sync.cancel()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and script.exports_sync.status()['current']:
                time.sleep(.1)
    finally:
        if prefetch:
            prefetch.shutdown(wait=False, cancel_futures=True)
        session.detach()
        save()
    loaded = validate_results(proofs, events)
    print(json.dumps(dict(loaded=len(loaded), playback=sum(bool(r.get('playback_finished')) for r in loaded))))


if __name__ == '__main__':
    main()
