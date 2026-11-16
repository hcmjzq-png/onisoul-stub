"""Build reversible PC country assets and app bundle; require known source hashes."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import http.client
import json
import lzma
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.port_legacy_media import unpack_pc, pack_pc
from tools.repair_unityweb_lzma import layout, repair
from tools.oni_il import parse_unity_web_data

APP_SHA = 'a374083f4662a5e3d2480058cbd2712d43c29035699b8d453dd749d19a45e9ce'
DLL_SHA = 'b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e'
sha = lambda b: hashlib.sha256(b).hexdigest()

def replace_entry(payload, name, replacement):
    parsed = parse_unity_web_data(payload)
    assert sum(e.name == name for e in parsed.entries) == 1
    contents = [(e.name, replacement if e.name == name else payload[e.offset:e.end]) for e in parsed.entries]
    size = 4 + sum(len(n.encode()) + 9 for n, _ in contents)
    directory = bytearray(struct.pack('>I', len(contents)))
    bodies = bytearray()
    start = (size + 3) & ~3
    for n, body in contents:
        bodies += b'\0' * (-len(bodies) % 4)
        directory += n.encode() + b'\0' + struct.pack('>II', start + len(bodies), len(body))
        bodies += body
    result = bytes(directory).ljust(start, b'\0') + bodies
    after = parse_unity_web_data(result)
    assert [e.name for e in after.entries] == [e.name for e in parsed.entries]
    for e in after.entries:
        expected = replacement if e.name == name else next(payload[o.offset:o.end] for o in parsed.entries if o.name == e.name)
        assert result[e.offset:e.end] == expected
    return result, start

def pack_app(blob, payload, first_offset):
    # The original app has six cumulative streaming levels in one LZMA stream.
    # Rebuild as a complete single level; preserve all named entries verbatim.
    pos = 13
    for _ in range(2):pos = blob.index(b'\0', pos)+1
    header = (pos + 32 + 3) & ~3
    comp = lzma.compress(payload, format=lzma.FORMAT_ALONE,
        filters=[dict(id=lzma.FILTER_LZMA1, dict_size=1 << 23, lc=3, lp=0, pb=2)])
    comp = comp[:5] + struct.pack('<Q', len(payload)) + comp[13:]
    head = blob[:pos]+struct.pack('>IIIIIIII', header+len(comp), header, 1, 1,
                                  len(comp), len(payload), header+len(comp), first_offset)
    head = head.ljust(header,b'\0')
    result = bytes(head)+comp
    assert not repair(result)[1]['changed']
    assert lzma.decompress(result[header:], format=lzma.FORMAT_ALONE) == payload
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app', type=Path, required=True)
    ap.add_argument('--assembly', type=Path, required=True)
    ap.add_argument('--inventory', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--host', help='Explicit source host; unnecessary with --source-dir')
    ap.add_argument('--source-dir', type=Path, help='Original chara files, for a reproducible offline rebuild after publishing')
    args=ap.parse_args()
    if not args.source_dir and not args.host:
        ap.error('Supply --source-dir for offline work or an explicit --host')
    if args.out.exists():raise ValueError('output directory already exists')
    args.out.mkdir(parents=True)
    source=args.app.read_bytes();assert sha(source)==APP_SHA
    pos=13
    for _ in range(2):pos=source.index(b'\0',pos)+1
    _,header,_,levels=struct.unpack_from('>IIII',source,pos)
    assert levels==6 and header==100
    payload=lzma.decompress(source[header:],format=lzma.FORMAT_ALONE)
    entry=next(e for e in parse_unity_web_data(payload).entries if e.name=='Assembly-CSharp.dll')
    assert sha(payload[entry.offset:entry.end])==DLL_SHA
    changed, first=replace_entry(payload,'Assembly-CSharp.dll',args.assembly.read_bytes())
    app=pack_app(source,changed,first)
    app_path=args.out/'web/client/app.unity3d';app_path.parent.mkdir(parents=True);app_path.write_bytes(app)
    rows=json.loads(args.inventory.read_text(encoding='utf-8'))['http']
    def get(row):
        path='/client/pc/jp/assets/chara/'+Path(row['path'].split('?')[0]).name
        if args.source_dir:
            data=(args.source_dir/Path(path).name).read_bytes()if row['status']==200 else None
            if data is not None and sha(data)!=row['sha256']:raise ValueError('original file fingerprint mismatch for '+row['country'])
            return row,path,data
        for attempt in range(5):
            c=http.client.HTTPConnection(args.host,80,timeout=20)
            try:
                c.request('GET',path+'?country_source=20261116');r=c.getresponse();data=r.read()
                if r.status!=row['status']:raise ValueError('status changed for '+row['country'])
                if r.status==200 and sha(data)!=row['sha256']:raise ValueError('source asset changed for '+row['country'])
                return row, path, data if r.status==200 else None
            except (OSError,http.client.HTTPException):
                if attempt==4:raise
                time.sleep(.3*(attempt+1))
            finally:c.close()
    with ThreadPoolExecutor(max_workers=4) as pool:fetched=list(pool.map(get,rows))
    groups=defaultdict(list)
    unpacked={}
    for row,path,data in fetched:
        if data is not None:
            hdr,archive,node=unpack_pc(data);groups[archive].append(sha(node));unpacked[row['country']]=(hdr,archive,node)
    conflicting={archive for archive,hashes in groups.items()if len(set(hashes))>1}
    proof=[]
    for row,path,data in fetched:
        if data is None:continue
        hdr,archive,node=unpacked[row['country']]
        unique='CustomAssetBundle-'+hashlib.md5(node).hexdigest()
        fixed=pack_pc(hdr,unique,node)if archive in conflicting else data
        _h,new_archive,new_node=unpack_pc(fixed);assert new_node==node
        rel='bundles/chara/'+Path(path).name;target=args.out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(fixed)
        original=args.out/'originals/chara'/Path(path).name;original.parent.mkdir(parents=True,exist_ok=True);original.write_bytes(data)
        proof.append(dict(country=row['country'],path=path,relative=rel,before_sha256=sha(data),sha256=sha(fixed),
                          old_archive=archive,archive=new_archive,serialized_sha256=sha(node),changed=fixed!=data,bytes=len(fixed)))
    by_archive=defaultdict(set)
    for row in proof:by_archive[row['archive']].add(row['serialized_sha256'])
    assert all(len(v)==1 for v in by_archive.values())
    manifest=dict(original_app_sha256=APP_SHA,app_sha256=sha(app),assembly_sha256=sha(args.assembly.read_bytes()),
                  app_relative='web/client/app.unity3d',app_original_entries_preserved_except=['Assembly-CSharp.dll'],
                  missing_countries=[r['country']for r in rows if r['status']==404],files=proof)
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(available=len(proof),changed=sum(r['changed']for r in proof),missing=len(manifest['missing_countries']),app_sha256=sha(app))))
if __name__=='__main__':main()
