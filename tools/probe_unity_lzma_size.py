#!/usr/bin/env python3
"""Read-only Frida length probe for the verified x86 Unity 4.3.7 WebPlayer DLL.

Optional analysis dependency: Frida 17. Refuses any other binary fingerprint.
Logs no HTTP bodies, credentials, or player state; never changes return values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

ENGINE_SHA256 = '0163227eb92c799322ea26ade936216c766d9d44397d095e8dcec34bbdc00fb5'
JS = r'''
const engine = Process.getModuleByName('webplayer_win.dll');
Interceptor.attach(engine.base.add(0x279905), {
  onEnter(args) {
    this.object = this.context.ecx;
    try {
      const n = args[1].readU32();
      if (n < 13) return;
      const p = args[0], bytes = new Uint8Array(p.readByteArray(13));
      send({event:'lzma_header', header:Array.from(bytes).map(x=>x.toString(16).padStart(2,'0')).join(''),
            low32:p.add(5).readU32(), high32:p.add(9).readU32()});
    } catch (e) { send({event:'read_error', error:String(e)}); }
  },
  onLeave() {
    try { send({event:'parsed_size', bytes:this.object.add(0xc0).readU32()}); } catch(e) {}
  }
});
Interceptor.attach(engine.base.add(0x279ae7), {
  onEnter() {
    try { const n=this.context.ecx.add(0xc0).readU32();
      send({event:'buffer_plan', decoded_bytes:n, block_bytes:102400, blocks:Math.floor(n/102400)+1});
    } catch(e) {}
  }
});
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import frida
    session = frida.attach(args.pid)
    try:
        lookup = session.create_script("rpc.exports.path = () => Process.getModuleByName('webplayer_win.dll').path;")
        lookup.load(); path = Path(lookup.exports_sync.path())
        if hashlib.sha256(path.read_bytes()).hexdigest() != ENGINE_SHA256:
            raise RuntimeError('unsupported engine binary; offsets must be verified again')
        lookup.unload()
        script = session.create_script(JS)
        with args.output.open('x', encoding='utf-8') as output:
            def record(message, data):
                output.write(json.dumps({'time':time.time(), 'message':message})+'\n');output.flush()
            script.on('message', record);script.load();time.sleep(args.seconds)
    finally:
        session.detach()


if __name__ == '__main__':
    main()
