"""Run the actual embedded ES5 script against a persistent browser-store model."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.transport import login_page


@unittest.skipUnless(shutil.which("node"), "Node required for browser JavaScript behavior")
class RememberLoginTest(unittest.TestCase):
    def test_reopen_uncheck_local_helper_and_offline_login(self):
        script = login_page.render().decode().rsplit("<script>", 1)[1].split("</script>", 1)[0]
        harness = r'''
const vm=require('vm'),assert=require('assert');
let disk={},online=true,requests=[];
function open(){
 const acc={value:''},pwd={value:''},box={className:'ui-radio checked'},hint={innerHTML:''};
 const form={querySelector:s=>s.includes('account')?acc:pwd,submit:()=>{form.submitted=true}};
 const doc={cookie:'',getElementById:id=>id==='remember'?box:hint,querySelector:()=>form};
 function XHR(){this.headers={};}
 XHR.prototype.open=function(method,url){this.method=method;this.url=url};
 XHR.prototype.setRequestHeader=function(k,v){this.headers[k]=v};
 XHR.prototype.abort=function(){};
 XHR.prototype.send=function(body){
  requests.push({url:this.url,method:this.method,headers:this.headers});
  if(online&&this.method==='POST')disk=JSON.parse(body);
  this.status=online?200:0;this.responseText=JSON.stringify(disk);this.readyState=4;this.onreadystatechange();
 };
 vm.runInNewContext(SCRIPT,{document:doc,window:{},XMLHttpRequest:XHR,screen:{},Image:function(){},location:{},
  setTimeout:()=>1,clearTimeout:()=>{}});
 return {acc,pwd,box,form,doc,hint};
}
let a=open();a.acc.value='测试账号';a.pwd.value='synthetic-only';a.form.onsubmit();
assert(a.form.submitted);assert(!a.doc.cookie.includes('synthetic-only'));
let b=open();assert.equal(b.acc.value,'测试账号');assert.equal(b.pwd.value,'synthetic-only');
b.box.onclick();assert.deepEqual(disk,{});assert.equal(open().acc.value,'');
online=false;let offline=open();offline.form.onsubmit();assert(offline.form.submitted);
assert(offline.box.title.includes('尚未启动'));
assert(requests.every(r=>r.url==='http://127.0.0.1:19765/credentials'&&r.headers['X-Oni-Login']==='1'));
console.log('remember behavior passed');
'''.replace("SCRIPT", json.dumps(script))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remember.js"
            path.write_text(harness, encoding="utf-8")
            result = subprocess.run([shutil.which("node"), str(path)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
