#!/usr/bin/env python3
"""Temporarily load converted bundles in the verified x86 PC WebPlayer.

Requires optional Frida 17 and an already running player. No game APIs, network
requests or save writes. This probe creates muted diagnostic AudioSources for
the selected samples, waits for playback to end and unloads all tested bundles.
The engine fingerprint and every converted file digest are checked first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

ENGINE_SHA256 = '0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--play', action='append', default=[], help='Exact clip name; muted playback')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=150)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    proofs = json.loads(args.manifest.read_text(encoding='utf-8'))['converted']
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
            events.append(message['payload'] if message['type'] == 'send' else message)
        script.on('message', receive)
        script.load()
        try:
            for row in proofs:
                script.exports_sync.enqueue(dict(name=row['name'],
                    bytes=list((args.root / row['output']).read_bytes()), play=row['name'] in args.play))
            start = time.monotonic()
            while time.monotonic() - start < args.timeout:
                status = script.exports_sync.status()
                if not status['queued'] and not status['current']:
                    break
                time.sleep(.3)
            else:
                raise TimeoutError('native resource probe timed out')
        finally:
            script.exports_sync.cancel()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and script.exports_sync.status()['current']:
                time.sleep(.1)
    finally:
        session.detach()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(pid=args.pid, engine_sha256=ENGINE_SHA256,
            status=status, events=events), indent=2), encoding='utf-8')
    loaded = [event['result'] for event in events if 'result' in event]
    errors = [event for event in events if 'error' in event or event.get('type') == 'error']
    if errors or len(loaded) != len(proofs):
        raise RuntimeError(f'native verification failed: {len(loaded)}/{len(proofs)}, {len(errors)} errors')
    print(json.dumps(dict(loaded=len(loaded), playback=sum(bool(r.get('playback_finished')) for r in loaded))))


if __name__ == '__main__':
    main()
