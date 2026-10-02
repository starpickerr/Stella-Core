"""Exercise the real backend hook with delayed Electron IPC and a live old port."""
import subprocess
from pathlib import Path


def test_hook_waits_for_owned_port_and_retires_old_ipc_after_status_event():
    desktop=Path(__file__).parents[1]/'desktop'
    script=r'''
const fs=require('fs'),ts=require('typescript'),assert=require('assert');
const source=fs.readFileSync('src/renderer/src/hooks/useBackend.ts','utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const sleep=()=>new Promise(r=>setImmediate(r));
async function scenario(eventFirst,invalid=false) {
  let state,resolvePort,statusCallback,visibilityCallback,cleanup;
  const requests=[];
  const react={useState:initial=>{state=initial;return [state,value=>{state=typeof value==='function'?value(state):value}]},useRef:initial=>({current:initial}),useCallback:callback=>callback,useEffect:callback=>{cleanup=callback()}};
  global.window={electronAPI:{getBackendPort:()=>new Promise(resolve=>{resolvePort=resolve}),onBackendStatus:callback=>{statusCallback=callback;return ()=>{}},getBackendError:async()=>null}};
  global.document={visibilityState:'visible',addEventListener:(_,callback)=>{visibilityCallback=callback},removeEventListener:()=>{}};
  global.fetch=async url=>{requests.push(url);return {ok:true}};
  const module={exports:{}};
  new Function('require','module','exports',code)(name=>name==='react'?react:require(name),module,module.exports);
  module.exports.useBackend();
  visibilityCallback();
  await sleep();
  assert.equal(requests.length,0,'Must not probe a possibly unrelated preferred-port backend before IPC');
  if(eventFirst) statusCallback({status:'ready',port:19987});
  resolvePort(invalid?0:eventFirst?9876:19987);
  await sleep();
  if(invalid) { assert.equal(state.status,'error');assert.equal(requests.length,0);cleanup();return; }
  assert.equal(state.port,19987);
  assert.equal(state.status,'ready');
  assert.ok(requests.every(url=>url.startsWith('http://127.0.0.1:19987/')));
  cleanup();
}
(async()=>{await scenario(false);await scenario(true);await scenario(false,true)})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result=subprocess.run(['node','-e',script],cwd=desktop,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
