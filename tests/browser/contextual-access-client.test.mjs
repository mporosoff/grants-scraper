import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const origin='https://funding-finder-researchers.urochestercheme.workers.dev';
function fixture(){
  const handlers={},clicks={},sent=[],opens=[];
  const popup={closed:false,postMessage:(value,target)=>sent.push({value,target})};
  const context=vm.createContext({URL,Response,TextEncoder,Uint8Array,crypto:webcrypto,performance,
    // Timers are unref'ed in this local protocol test, never the browser runtime.
    setTimeout:(cb,ms)=>{const timer=setTimeout(cb,ms);timer.unref();return timer;},clearTimeout,
    location:{origin:'http://127.0.0.1:8876'},document:{querySelector:()=>({content:'access-window-v1'}),addEventListener:(key,fn)=>{clicks[key]=fn;}},
    addEventListener:(key,fn)=>{handlers[key]=fn;},open:(...args)=>{opens.push(args);return popup;}});
  vm.runInContext(fs.readFileSync('assets/contextual-team-access.js','utf8'),context);
  return {context,handlers,clicks,sent,opens,popup,api:context.ContextualTeamAccess};
}
test('loading the connection helper is inert and ordinary paths cannot open an authenticated window',async()=>{
  const f=fixture();assert.equal(f.opens.length,0);assert.equal(f.sent.length,0);
  f.clicks.click({target:{closest:()=>null}});assert.equal(f.opens.length,0);
  await assert.rejects(f.api.fetch(origin+'/admin/api/contextual/jobs'),/connection_required/);
  f.context.location.origin='https://public.example';f.api.prepare();assert.equal(f.opens.length,0);
});
test('exact origin/window/channel binding, fixed API and bounded read response; no credential export',async()=>{
  const f=fixture();f.api.prepare();assert.equal(f.opens.length,1);f.api.prepare();assert.equal(f.opens.length,1);
  const channel=new URL(f.opens[0][0]).hash.slice(1),message={protocol:'contextual-access-v1',channel};
  f.handlers.message({origin,source:f.popup,data:{...message,action:'ready'}});
  await assert.rejects(f.api.fetch('https://evil.example/jobs'),/operation_rejected/);
  const promise=f.api.fetch(origin+'/admin/api/contextual/jobs?'+new URLSearchParams({release_id:'a'.repeat(64),scope_id:'332894',person_id:''}));
  await new Promise(r=>setTimeout(r,0));const request=f.sent[0].value;
  assert.equal(request.method,'GET');assert.equal(f.api.statistics().explicit_posts,0);
  const response={...message,action:'response',id:request.id,status:200,body:JSON.stringify({state:'unassessed'})};
  f.handlers.message({origin:'https://evil.example',source:f.popup,data:response});assert.equal(f.api.statistics().pending,1);
  f.handlers.message({origin,source:{},data:response});assert.equal(f.api.statistics().pending,1);
  f.handlers.message({origin,source:f.popup,data:response});assert.deepEqual(await (await promise).json(),{state:'unassessed'});
  assert.equal(f.api.statistics().pending,0);assert.equal(f.api.statistics().measurements.length,1);
  assert(!JSON.stringify(f.sent).includes('Authorization'));assert(!JSON.stringify(f.sent).includes('cookie'));
});
