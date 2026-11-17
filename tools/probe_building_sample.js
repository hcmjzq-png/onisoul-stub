// Isolated QA only. Loaded by the gated Python driver; all Unity calls run on Update.
if (Process.pointerSize !== 4) throw new Error('x86 Unity required');
const mono = Process.getModuleByName('mono-1-vc.dll');
const fn = (name, result, args) => new NativeFunction(mono.getExportByName(name), result, args);
const root = fn('mono_get_root_domain', 'pointer', [])(); let domain = root;
fn('mono_domain_foreach', 'void', ['pointer', 'pointer'])(new NativeCallback(d => { if (!d.equals(root)) domain = d; }, 'void', ['pointer', 'pointer']), ptr(0));
fn('mono_thread_attach', 'pointer', ['pointer'])(domain);
const image = fn('mono_image_loaded', 'pointer', ['pointer'])(Memory.allocUtf8String('UnityEngine'));
if (image.isNull()) throw new Error('QA Unity is not ready');
const findClass = fn('mono_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
const findMethod = fn('mono_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
const invoke = fn('mono_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
const unbox = fn('mono_object_unbox', 'pointer', ['pointer']);
const objectNew = fn('mono_object_new', 'pointer', ['pointer', 'pointer']);
const keep = fn('mono_gchandle_new', 'uint', ['pointer', 'int']);
const free = fn('mono_gchandle_free', 'void', ['uint']);
const handles = [], objects = [];
function klass(n) { return findClass(image, Memory.allocUtf8String('UnityEngine'), Memory.allocUtf8String(n)); }
function method(c, n, a, parameterType) {
  if (parameterType) {
    const iter = Memory.alloc(4); iter.writePointer(ptr(0));
    const next = fn('mono_class_get_methods', 'pointer', ['pointer', 'pointer']);
    const name = fn('mono_method_get_name', 'pointer', ['pointer']);
    const signature = fn('mono_method_signature', 'pointer', ['pointer']);
    const count = fn('mono_signature_get_param_count', 'uint', ['pointer']);
    const param = fn('mono_signature_get_params', 'pointer', ['pointer', 'pointer']);
    const typeName = fn('mono_type_get_name', 'pointer', ['pointer']);
    for (;;) {
      const m = next(klass(c), iter); if (m.isNull()) break;
      if (name(m).readUtf8String() !== n) continue;
      const sig = signature(m); if (count(sig) !== a) continue;
      const pi = Memory.alloc(4); pi.writePointer(ptr(0));
      if (typeName(param(sig, pi)).readUtf8String() === parameterType) return m;
    }
    throw new Error('missing overload ' + c + '.' + n + '(' + parameterType + ')');
  }
  const m = findMethod(klass(c), Memory.allocUtf8String(n), a); if (m.isNull()) throw new Error(c + '.' + n); return m;
}
function str(s) { return fn('mono_string_new', 'pointer', ['pointer', 'pointer'])(domain, Memory.allocUtf8String(s)); }
function call(m, obj, args = []) { const av = Memory.alloc(Math.max(4, args.length * 4)); args.forEach((v, i) => av.add(i * 4).writePointer(v)); const ex = Memory.alloc(4); ex.writePointer(ptr(0)); const value = invoke(m, obj || ptr(0), av, ex); if (!ex.readPointer().isNull()) throw new Error('managed exception in Unity call'); return value; }
function held(o) { if (o.isNull()) throw new Error('null managed object'); handles.push(keep(o, 1)); return o; }
function value(values, kind = 'float') { const p = Memory.alloc(values.length * 4); values.forEach((v, i) => kind === 'int' ? p.add(i * 4).writeS32(v) : p.add(i * 4).writeFloat(v)); return p; }
function make(c, args, arity) { const o = held(objectNew(domain, klass(c))); call(method(c, '.ctor', arity), o, args); return o; }
const yes = value([1], 'int'), no = value([0], 'int');
const newArray = fn('mono_array_new', 'pointer', ['pointer', 'pointer', 'uint']);
const bytesClass = fn('mono_get_byte_class', 'pointer', [])();
const getType = fn('mono_class_get_type', 'pointer', ['pointer']);
const typeObject = fn('mono_type_get_object', 'pointer', ['pointer', 'pointer']);
const goType = held(typeObject(domain, getType(klass('GameObject'))));
const create = method('AssetBundle', 'CreateFromMemory', 1);
const isDone = method('AsyncOperation', 'get_isDone', 0);
const getBundle = method('AssetBundleCreateRequest', 'get_assetBundle', 0);
const load = method('AssetBundle', 'Load', 2);
const instantiate = method('Object', 'Instantiate', 1);
const transformOf = method('Component', 'get_transform', 0);
const component = method('GameObject', 'GetComponent', 1, 'System.String');
let job = null, busy = false, finished = false, stage = 'initializing';

function setLayer(transform, stats) {
  const go = call(method('Component', 'get_gameObject', 0), transform);
  call(method('GameObject', 'set_layer', 1), go, [value([30], 'int')]);
  for (const kind of ['MeshRenderer', 'MeshCollider', 'Animation']) {
    const c = call(component, go, [str(kind)]);
    if (!c.isNull()) stats[kind] = (stats[kind] || 0) + 1;
  }
  const count = unbox(call(method('Transform', 'get_childCount', 0), transform)).readS32();
  for (let i = 0; i < count; i++) setLayer(call(method('Transform', 'GetChild', 1), transform, [value([i], 'int')]), stats);
}

function render() {
  stage = 'loading typed prefab';
  const bundle = held(call(getBundle, job.request));
  const prefab = held(call(load, bundle, [str(job.name), goType]));
  const model = held(call(instantiate, null, [prefab])); objects.push(model);
  const transform = call(method('GameObject', 'get_transform', 0), model), stats = {};
  stage = 'checking instantiated components';
  setLayer(transform, stats);
  call(method('Transform', 'set_localScale', 1), transform, [value([-1, 1, -1])]);
  call(method('Transform', 'set_position', 1), transform, [value([0, 0, 0])]);
  const cameraGO = make('GameObject', [str('OniSoulBuildingSampleCamera')], 1); objects.push(cameraGO);
  stage = 'creating preview camera';
  const camera = held(call(method('GameObject', 'AddComponent', 1, 'System.String'), cameraGO, [str('Camera')]));
  call(method('Transform', 'set_position', 1), call(transformOf, camera), [value([0, job.centerY, -1000])]);
  call(method('Camera', 'set_orthographic', 1), camera, [yes]);
  call(method('Camera', 'set_orthographicSize', 1), camera, [value([job.orthoSize])]);
  call(method('Camera', 'set_clearFlags', 1), camera, [value([2], 'int')]);
  call(method('Camera', 'set_backgroundColor', 1), camera, [value([0.12, 0.16, 0.12, 1])]);
  call(method('Camera', 'set_cullingMask', 1), camera, [value([1 << 30], 'int')]);
  const rt = make('RenderTexture', [value([680], 'int'), value([510], 'int'), value([24], 'int')], 3); objects.push(rt);
  call(method('Camera', 'set_targetTexture', 1), camera, [rt]);
  stage = 'rendering model';
  call(method('Camera', 'Render', 0), camera);
  call(method('RenderTexture', 'set_active', 1), null, [rt]);
  stage = 'reading rendered pixels';
  const texture = make('Texture2D', [value([680], 'int'), value([510], 'int')], 2); objects.push(texture);
  call(method('Texture2D', 'ReadPixels', 3), texture, [value([0, 0, 680, 510]), no, no]);
  call(method('Texture2D', 'Apply', 0), texture);
  const png = held(call(method('Texture2D', 'EncodeToPNG', 0), texture));
  const length = png.add(12).readU32();
  if (!length || length > 4 * 1024 * 1024) throw new Error('unexpected PNG size');
  const pixels = png.add(16).readByteArray(length);
  const result = {name: job.name, loaded: true, instantiated: true, components: stats, width: 680, height: 510,
    camera_center_y: job.centerY, orthographic_size: job.orthoSize, output_sha256: job.sha256};
  call(method('RenderTexture', 'set_active', 1), null, [ptr(0)]);
  for (const o of objects.reverse()) call(method('Object', 'DestroyImmediate', 1), null, [o]);
  call(method('AssetBundle', 'Unload', 1), bundle, [yes]);
  for (const h of handles) free(h);
  finished = true;
  send({result}, pixels);
}

const nameOf = fn('mono_method_get_name', 'pointer', ['pointer']);
Interceptor.attach(mono.getExportByName('mono_runtime_invoke'), {
  onEnter(args) { if (busy || finished || !job) return; this.update = nameOf(args[0]).readUtf8String() === 'Update'; },
  onLeave() {
    if (!this.update || busy || finished) return;
    busy = true;
    try {
      if (!job.request) {
        stage = 'creating bundle request';
        const data = new Uint8Array(job.bytes);
        const array = held(newArray(domain, bytesClass, data.length));
        array.add(16).writeByteArray(data);
        job.request = held(call(create, null, [array]));
        delete job.bytes;
      } else if (unbox(call(isDone, job.request)).readU8()) render();
    } catch (e) { finished = true; send({error: String(e), stage, stack:String(e.stack)}); }
    finally { busy = false; }
  }
});
rpc.exports = { enqueue(metadata, bytes) { if (job) throw new Error('one sample only'); job = metadata; job.bytes = bytes; } };
