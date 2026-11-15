// Temporary diagnostic for the exact WebPlayer engine gated by the Python driver.
// Loads named bundles on Unity Update, mutes playback, stops/destroys QA sources,
// then unloads each bundle. Does not call game APIs or write player state.
if(Process.pointerSize!==4)throw new Error('x86 player required');
const mono=Process.findModuleByName('mono-1-vc.dll');if(!mono)throw new Error('Mono not loaded');
const fn=(n,r,a)=>new NativeFunction(mono.getExportByName(n),r,a);
const root=fn('mono_get_root_domain','pointer',[])();let domain=root;
fn('mono_domain_foreach','void',['pointer','pointer'])(new NativeCallback(d=>{if(!d.equals(root))domain=d;},'void',['pointer','pointer']),ptr(0));
fn('mono_thread_attach','pointer',['pointer'])(domain);
const image=fn('mono_image_loaded','pointer',['pointer'])(Memory.allocUtf8String('UnityEngine'));
const cls=fn('mono_class_from_name','pointer',['pointer','pointer','pointer']);
const getmethod=fn('mono_class_get_method_from_name','pointer',['pointer','pointer','int']);
const names=fn('mono_method_get_name','pointer',['pointer']);
const invoke=fn('mono_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
const unbox=fn('mono_object_unbox','pointer',['pointer']);
const str=fn('mono_string_new','pointer',['pointer','pointer']);
const getclass=fn('mono_object_get_class','pointer',['pointer']);
const classname=fn('mono_class_get_name','pointer',['pointer']);
const keep=fn('mono_gchandle_new','uint',['pointer','int']),free=fn('mono_gchandle_free','void',['uint']);
function klass(n){return cls(image,Memory.allocUtf8String('UnityEngine'),Memory.allocUtf8String(n));}
function method(c,n,a){const m=getmethod(klass(c),Memory.allocUtf8String(n),a);if(m.isNull())throw new Error('missing '+c+'.'+n);return m;}
function string(s){return str(domain,Memory.allocUtf8String(s));}
function call(m,obj,args=[]){const argv=Memory.alloc(Math.max(4,args.length*4));args.forEach((v,i)=>argv.add(i*4).writePointer(v));const ex=Memory.alloc(4);ex.writePointer(ptr(0));const r=invoke(m,obj||ptr(0),argv,ex);if(!ex.readPointer().isNull())throw new Error('managed '+classname(getclass(ex.readPointer())).readUtf8String());return r;}
const create=method('AssetBundle','CreateFromMemory',1),requestBundle=method('AssetBundleCreateRequest','get_assetBundle',0),isDone=method('AsyncOperation','get_isDone',0),load=method('AssetBundle','Load',1),unload=method('AssetBundle','Unload',1);
const getlen=method('AudioClip','get_length',0),getsamples=method('AudioClip','get_samples',0),getchannels=method('AudioClip','get_channels',0),getfreq=method('AudioClip','get_frequency',0);
const getwidth=method('Texture','get_width',0),getheight=method('Texture','get_height',0);
const byteclass=fn('mono_get_byte_class','pointer',[])(),arraynew=fn('mono_array_new','pointer',['pointer','pointer','uint']);
const objectnew=fn('mono_object_new','pointer',['pointer','pointer']);
const destroy=method('Object','Destroy',1),play=method('AudioSource','Play',0),stop=method('AudioSource','Stop',0),playing=method('AudioSource','get_isPlaying',0),setclip=method('AudioSource','set_clip',1),volume=method('AudioSource','set_volume',1);
// The first 1-argument AddComponent overload in this engine is System.String,
// verified separately via mono_class_get_methods/signature parameter names.
const addcomponent=method('GameObject','AddComponent',1),ctor=method('GameObject','.ctor',1);
const yes=Memory.alloc(4);yes.writeU32(1);const zero=Memory.alloc(4);zero.writeFloat(0);
let queue=[],current=null,guard=false,steps=0,cancelled=false;
function cleanup(){if(!current)return;const c=current;try{if(c.source){call(stop,c.source);call(destroy,null,[c.go]);}if(c.bundle)call(unload,c.bundle,[yes]);}finally{for(const h of c.handles)free(h);current=null;}}
function step(){steps++;if(cancelled){cleanup();return;}if(!current){if(!queue.length)return;current=queue.shift();current.handles=[];current.started=Date.now();const bytes=new Uint8Array(current.bytes);delete current.bytes;const arr=arraynew(domain,byteclass,bytes.length);arr.add(16).writeByteArray(bytes);current.handles.push(keep(arr,1));current.request=call(create,null,[arr]);if(current.request.isNull())throw new Error('null bundle request');current.handles.push(keep(current.request,1));return;}
 const c=current;if(Date.now()-c.started>20000)throw new Error('native load/playback timed out');
 if(c.playStarted){const active=unbox(call(playing,c.source)).readU8()!==0;if(!active){c.result.playback_finished=true;send({result:c.result});cleanup();}return;}
 if(unbox(call(isDone,c.request)).readU8()===0)return;
 c.bundle=call(requestBundle,c.request);if(c.bundle.isNull())throw new Error('native AssetBundle load failed');c.handles.push(keep(c.bundle,1));
 const media=call(load,c.bundle,[string(c.name)]);if(media.isNull())throw new Error('native named asset missing');c.handles.push(keep(media,1));
 const kind=classname(getclass(media)).readUtf8String();const r={name:c.name,kind,loaded:true};
 if(kind==='AudioClip'){
  r.seconds=unbox(call(getlen,media)).readFloat();r.samples=unbox(call(getsamples,media)).readS32();r.channels=unbox(call(getchannels,media)).readS32();r.frequency=unbox(call(getfreq,media)).readS32();if(r.seconds<=0||r.samples<=0)throw new Error('native audio has no decoded duration/samples');
  if(c.play){c.go=objectnew(domain,klass('GameObject'));c.handles.push(keep(c.go,1));call(ctor,c.go,[string('OniSoulMediaQA')]);c.source=call(addcomponent,c.go,[string('AudioSource')]);c.handles.push(keep(c.source,1));call(volume,c.source,[zero]);call(setclip,c.source,[media]);call(play,c.source);r.playback_started=unbox(call(playing,c.source)).readU8()!==0;if(!r.playback_started)throw new Error('native audio did not start');c.playStarted=Date.now();c.result=r;return;}
 }else if(kind==='Texture2D'){r.width=unbox(call(getwidth,media)).readS32();r.height=unbox(call(getheight,media)).readS32();if(r.width<=0||r.height<=0)throw new Error('empty native texture');}else throw new Error('unexpected native class '+kind);
 send({result:r});cleanup();
}
Interceptor.attach(mono.getExportByName('mono_runtime_invoke'),{onEnter(args){if(guard||(!queue.length&&!current))return;try{this.run=names(args[0]).readUtf8String()==='Update';}catch(e){}},onLeave(){if(!this.run||guard)return;guard=true;try{step();}catch(e){send({error:String(e),name:current?current.name:null});try{cleanup();}catch(e){send({cleanupError:String(e)});}}finally{guard=false;}}});
rpc.exports={enqueue(job){if(cancelled)throw new Error('probe cancelled');queue.push(job);return queue.length;},cancel(){queue=[];cancelled=true;},status(){return{queued:queue.length,current:current?current.name:null,steps};}};
send({ready:true,domain:domain.toString()});
