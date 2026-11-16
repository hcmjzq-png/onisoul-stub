"""Verify all staged country portraits while retaining their bundles together.

Uses the fingerprinted legacy engine and the existing Update-thread probe. Unlike
individual media validation, this detects internal serialized-file name collisions.
Run only against an isolated QA client before the map opens.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time


def retaining_probe():
    source = Path(__file__).with_name('probe_legacy_media.js').read_text(encoding='utf-8')
    replacements = {
        'let queue=[],current=null,active=[]': 'let held=[],releasing=false;let queue=[],current=null,active=[]',
        'if(c.bundle)call(unload,c.bundle,[yes]);': 'if(c.bundle){held.push({bundle:c.bundle,handles:c.handles});c.handles=[];}',
        'steps};': 'steps,held:held.length};',
        'cancel(){queue=[];cancelled=true;}': 'cancel(){queue=[];cancelled=true;},release(){releasing=true;}',
        'function advance(){': 'function advance(){if(releasing){for(const c of held){call(unload,c.bundle,[yes]);for(const h of c.handles)free(h);}held=[];releasing=false;}',
        '(!queue.length&&!active.length)': '(!queue.length&&!active.length&&!releasing)',
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise ValueError('legacy probe changed; review retained-bundle adapter')
        source = source.replace(old, new)
    return source


def main():
    import frida
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--inventory', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((args.release/'manifest.json').read_text(encoding='utf-8'))
    inventory = json.loads(args.inventory.read_text(encoding='utf-8'))['http']
    jobs = []
    for row in manifest['files']:
        data = (args.release/row['relative']).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('release fingerprint mismatch')
        original = next(x for x in inventory if x['country'] == row['country'])
        jobs.append((dict(id=row['country'], name=original['image']+'_1_01', output_sha256=row['sha256']), data))
    if len(jobs) != 20:
        raise ValueError('expected twenty available country bundles')
    results, errors = [], []
    session = frida.attach(args.pid)
    script = None
    engine_sha = '0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5'
    try:
        check = session.create_script("rpc.exports.path=()=>Process.getModuleByName('webplayer_win.dll').path;")
        check.load()
        if hashlib.sha256(Path(check.exports_sync.path()).read_bytes()).hexdigest() != engine_sha:
            raise ValueError('unverified native engine')
        check.unload()
        script = session.create_script(retaining_probe())
        def message(m, data):
            p = m.get('payload', {})
            if 'result' in p:
                results.append(p['result'])
            elif 'error' in p or 'cleanupError' in p or m['type'] == 'error':
                errors.append(m)
        script.on('message', message)
        script.load()
        script.exports_sync.configure(dict(concurrency=2, timeoutMs=30000, attempts=1))
        for job, data in jobs:
            script.exports_sync.enqueue(job, data)
        until = time.monotonic()+90
        while len(results)+len(errors) < len(jobs) and time.monotonic() < until:
            time.sleep(.2)
        status = script.exports_sync.status()
        proof = dict(engine_sha256=engine_sha, passed=len(results), held_simultaneously=status['held'], results=results, errors=errors)
        args.out.write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
        if len(results) != 20 or errors or status['held'] != 20:
            raise RuntimeError('native retained-bundle verification failed; see output')
        print(json.dumps(dict(passed=20, held_simultaneously=20)))
    finally:
        try:
            if script is not None:
                try:
                    script.exports_sync.cancel()
                    until = time.monotonic()+10
                    while script.exports_sync.status()['current'] and time.monotonic() < until:
                        time.sleep(.1)
                    script.exports_sync.release()
                    until = time.monotonic()+10
                    while script.exports_sync.status()['held'] and time.monotonic() < until:
                        time.sleep(.1)
                    if script.exports_sync.status()['held']:
                        raise RuntimeError('native probe cleanup incomplete; close QA client')
                finally:
                    script.unload()
        finally:
            session.detach()


if __name__ == '__main__':
    main()
