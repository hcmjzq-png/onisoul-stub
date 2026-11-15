#!/usr/bin/env python3
"""Temporarily load converted bundles in the verified x86 PC WebPlayer.

Requires optional Frida 17 and an already running player. No game API calls or
save writes. URL manifests download through HTTP and native Unity WWW. This
probe creates muted diagnostic AudioSources for
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


class HttpPreflight:
    """Keep at most one small window ahead of native submissions, even if stalled."""

    def __init__(self, proofs: list[dict], workers: int, *, attempts: int, timeout: float):
        self.proofs = proofs
        self.window = workers
        self.attempts = attempts
        self.timeout = timeout
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.pending = {}
        self.next_index = 0

    def ready(self, index: int) -> bool:
        while self.next_index < min(index + self.window, len(self.proofs)):
            row = self.proofs[self.next_index]
            self.pending[self.next_index] = self.executor.submit(self.check, row)
            self.next_index += 1
        return self.pending[index].done()

    def check(self, row: dict) -> int | None:
        if not row.get('url'):
            return None
        return verify_url(row['url'], row['output_sha256'],
                          attempts=self.attempts, timeout=self.timeout)

    def take(self, index: int) -> int | None:
        return self.pending.pop(index).result()

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


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
        if row.get('url') and result.get('source_url') != row['url']:
            raise RuntimeError('native HTTP URL mismatch: ' + row['name'])
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
    parser.add_argument('--queue-size', type=int, default=4, help='Bound queued plus active bundles')
    parser.add_argument('--native-concurrency', type=int, default=2)
    parser.add_argument('--http-workers', type=int, default=2, help='Bound preflight downloads and lookahead')
    parser.add_argument('--transfer-timeout', type=float, default=60, help='Seconds per native download attempt / HTTP socket operation')
    parser.add_argument('--http-attempts', type=int, default=5)
    parser.add_argument('--native-attempts', type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    proofs = json.loads(args.manifest.read_text(encoding='utf-8'))['converted']
    if min(args.queue_size, args.native_concurrency, args.http_workers, args.timeout,
           args.transfer_timeout, args.http_attempts, args.native_attempts) <= 0:
        parser.error('queue, concurrency, timeouts and attempt counts must be positive')
    ids = [row.get('id', str(index)) for index, row in enumerate(proofs)]
    if len(set(ids)) != len(ids):
        parser.error('manifest IDs must be unique')
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
    if any(row.get('url') for row in proofs):
        prefetch = HttpPreflight(proofs, args.http_workers,
                                 attempts=args.http_attempts, timeout=args.transfer_timeout)
    native_source = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    settings = dict(concurrency=args.native_concurrency, timeoutMs=args.transfer_timeout * 1000,
                    attempts=args.native_attempts)
    def save() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + '.tmp')
        temporary.write_text(json.dumps(dict(pid=args.pid, engine_sha256=ENGINE_SHA256,
            manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            probe_sha256=hashlib.sha256(native_source.encode()).hexdigest(),
            settings=settings, status=status, events=events), indent=2), encoding='utf-8')
        temporary.replace(args.output)
    try:
        lookup = session.create_script(
            "rpc.exports.path=()=>Process.getModuleByName('webplayer_win.dll').path;")
        lookup.load()
        engine = Path(lookup.exports_sync.path())
        if hashlib.sha256(engine.read_bytes()).hexdigest() != ENGINE_SHA256:
            raise RuntimeError('unsupported engine binary')
        lookup.unload()
        script = session.create_script(native_source)
        def receive(message, data):
            event = message['payload'] if message['type'] == 'send' else message
            events.append(event)
        script.on('message', receive)
        script.load()
        script.exports_sync.configure(settings)
        try:
            start = time.monotonic()
            submitted = 0
            last_saved = 0
            while time.monotonic() - start < args.timeout:
                status = script.exports_sync.status()
                if (submitted < len(proofs) and
                        status['queued'] + len(status['current'] or []) < args.queue_size and
                        (not prefetch or prefetch.ready(submitted))):
                    row = proofs[submitted]
                    job = dict(id=row.get('id', str(submitted)), name=row['name'],
                        output_sha256=row['output_sha256'], expected_bytes=row['output_bytes'],
                        url=row.get('url'), play=row['name'] in args.play)
                    if prefetch:
                        retries = prefetch.take(submitted)
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
    except Exception as exc:
        events.append(dict(error=type(exc).__name__ + ': ' + str(exc), phase='driver'))
        raise
    finally:
        if prefetch:
            prefetch.close()
        session.detach()
        save()
    loaded = validate_results(proofs, events)
    print(json.dumps(dict(loaded=len(loaded), playback=sum(bool(r.get('playback_finished')) for r in loaded))))


if __name__ == '__main__':
    main()
