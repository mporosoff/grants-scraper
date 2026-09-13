import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {ACCESS_JS} from '../../workers/researcher-intake/src/contextual-access.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
function fixture(){
  const messages=[],calls=[],handlers={},status={textContent:''};
  const owner={postMessage:(value,origin)=>messages.push({value,origin})};
  const context=vm.createContext({window:{opener:owner},location:{hash:'#'+'a'.repeat(32)},
    document:{getElementById:()=>status},addEventListener:(name,cb)=>{handlers[name]=cb;},
    URLSearchParams,TextDecoder,AbortSignal,Set,
    fetch:async(url,options)=>{calls.push({url,options});return Response.json(url.endsWith('/fixture')?
      {fixture:true,purpose:'routing_only',provider_work:false,scientific_graph:false}:
      {state:'unassessed',fixture:true});}});
  vm.runInContext(ACCESS_JS,context);
  const data={protocol:'contextual-access-v1',channel:'a'.repeat(32),action:'request',id:'b'.repeat(32),method:'GET',
    ids:{release_id:'c'.repeat(64),scope_id:'332894',person_id:''}};
  return {owner,messages,calls,handlers,status,data,context};
}
test('protected window starts with a labeled read-only routing fixture, not paid work',async()=>{
  const f=fixture();await tick();assert.equal(f.calls.length,1);assert.equal(f.calls[0].url,'/admin/api/contextual/fixture');
  assert.equal(f.calls[0].options.credentials,'same-origin');assert.equal(f.messages[0].value.routing_fixture,true);
  assert.equal(f.messages[0].origin,'http://127.0.0.1:8876');
});
test('wrong origin, window, channel, fields and arbitrary paths never reach the authenticated API',async()=>{
  const f=fixture();await tick();
  const good={origin:'http://127.0.0.1:8876',source:f.owner,data:f.data};
  for(const changed of [{origin:'https://evil.example'},{source:{}},{data:{...f.data,channel:'x'}},
    {data:{...f.data,url:'https://evil.example'}},{data:{...f.data,method:'DELETE'}},
    {data:{...f.data,ids:{...f.data.ids,secret:'arbitrary'}}}])await f.handlers.message({...good,...changed});
  assert.equal(f.calls.length,1);
  await f.handlers.message(good);assert.equal(f.calls.length,2);
  assert.match(f.calls[1].url,/^\/admin\/api\/contextual\/jobs\?/);
  assert.equal(f.calls[1].options.method,'GET');assert.equal(f.messages.at(-1).value.status,200);
  assert(!JSON.stringify(f.messages).includes('cookie'));assert(!JSON.stringify(f.messages).includes('Authorization'));
});
test('only the exact explicit POST shape can create a job; repeated message IDs cannot duplicate in-flight work',async()=>{
  const f=fixture();await tick();const event={source:f.owner,origin:'http://127.0.0.1:8876',data:{...f.data,method:'POST'}};
  await Promise.all([f.handlers.message(event),f.handlers.message(event)]);
  const posts=f.calls.filter(c=>c.options.method==='POST');assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/admin/api/contextual/jobs');assert.deepEqual(JSON.parse(posts[0].options.body),f.data.ids);
});
