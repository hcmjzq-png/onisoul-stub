"""Verify unpublished character bundles together in the fingerprinted PC engine.

The staged release must have distinct, repaired internal names not yet served to
the game. Retain all tested bundles, re-read every named texture after the last
bundle loads, then release only the probe's own bundles. No game RPC/save writes.
Requires optional Frida 17 and a running x86 WebPlayer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import unpack_pc
from tools.probe_country_bundles import retaining_probe
from tools.probe_legacy_media import ENGINE_SHA256


def character_probe():
    source = retaining_probe()
    source = 'let recheck=false,rechecked=false;\n' + source
    changes = {
        'held.push({bundle:c.bundle,handles:c.handles})':
            'held.push({bundle:c.bundle,handles:c.handles,textures:c.textures,id:c.id})',
        'send({result:r});cleanup();': 'r.textures=checkTextures(c.bundle,c.textures);send({result:r});cleanup();',
        'function advance(){': '''function checkTextures(bundle,textures){return textures.map(t=>{
 const tex=call(load,bundle,[string(t.name)]);if(tex.isNull())throw new Error('missing '+t.name);
 const h=keep(tex,1);try{
  const kind=classname(getclass(tex)).readUtf8String();
  const width=unbox(call(getwidth,tex)).readS32(),height=unbox(call(getheight,tex)).readS32();
  const name=readString(call(method('Object','get_name',0),tex));
  if(kind!=='Texture2D'||name!==t.name||width!==t.width||height!==t.height)throw new Error('wrong texture '+t.name);
  return {name,kind,width,height};
 }finally{free(h);}
});}
function advance(){if(recheck){recheck=false;try{
 send({retained:held.map(c=>({id:c.id,textures:checkTextures(c.bundle,c.textures)}))});rechecked=true;
}catch(e){send({error:String(e)});}}''',
        '&&!releasing)': '&&!releasing&&!recheck)',
        'held:held.length};': 'held:held.length,rechecked};',
    }
    for old, new in changes.items():
        if source.count(old) != 1:
            raise ValueError('review changed retained probe adapter: ' + old)
        source = source.replace(old, new)
    return source + '\nrpc.exports.recheck=()=>{recheck=true;rechecked=false;};\n'


def main():
    import frida
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--release', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    rows = json.loads((args.release / 'manifest.json').read_text(encoding='utf-8'))['files']
    if not rows or len({r['archive'] for r in rows}) != len(rows):
        raise ValueError('distinct archives required')
    jobs = []
    for row in rows:
        path = (args.release / row['relative']).resolve()
        path.relative_to(args.release.resolve())
        data = path.read_bytes()
        _, archive, node = unpack_pc(data)
        if (archive != row['archive'] or archive == row['old_archive']
                or hashlib.sha256(data).hexdigest() != row['sha256']
                or hashlib.sha256(node).hexdigest() != row['serialized_sha256']):
            raise ValueError('repaired character fingerprint mismatch')
        jobs.append((dict(id=row['logical'], name=row['textures'][0]['name'], textures=row['textures'],
                          output_sha256=row['sha256']), data))
    events, script, status, cleanup, loaded = [], None, None, None, False
    session = frida.attach(args.pid)
    try:
        check = session.create_script("rpc.exports.path=()=>Process.getModuleByName('webplayer_win.dll').path;")
        check.load()
        if hashlib.sha256(Path(check.exports_sync.path()).read_bytes()).hexdigest() != ENGINE_SHA256:
            raise ValueError('unverified PC engine')
        check.unload()
        source = character_probe()
        script = session.create_script(source)
        script.on('message', lambda m, data: events.append(m.get('payload', m)))
        script.load()
        loaded = True
        script.exports_sync.configure(dict(concurrency=2, timeoutMs=30000, attempts=1))
        for job, data in jobs:
            script.exports_sync.enqueue(job, data)
        until = time.monotonic() + 60
        while time.monotonic() < until:
            status = script.exports_sync.status()
            if sum('result' in e or 'error' in e for e in events) == len(jobs):
                break
            time.sleep(.1)
        if status['held'] != len(jobs) or any('error' in e or e.get('type') == 'error' for e in events):
            raise RuntimeError('retained character load failed')
        script.exports_sync.recheck()
        until = time.monotonic() + 10
        while time.monotonic() < until:
            status = script.exports_sync.status()
            if status['rechecked']:
                break
            time.sleep(.1)
        if not status['rechecked']:
            raise RuntimeError('retained character texture recheck failed')
    finally:
        try:
            if loaded:
                script.exports_sync.cancel()
                script.exports_sync.release()
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    cleanup = script.exports_sync.status()
                    if not cleanup['held'] and not cleanup['current']:
                        break
                    time.sleep(.1)
                if cleanup['held'] or cleanup['current']:
                    raise RuntimeError('probe bundle cleanup incomplete')
                script.unload()
        finally:
            session.detach()
            args.output.write_text(json.dumps(dict(engine_sha256=ENGINE_SHA256, status=status,
                released=cleanup is not None and not cleanup['held'], events=events), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(bundles=len(jobs), retained_together=status['held'],
        textures=sum(len(row['textures']) for row in rows), rechecked=True, released=True)))


if __name__ == '__main__':
    main()
