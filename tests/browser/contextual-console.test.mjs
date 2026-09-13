import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';
import {shellDom} from '../helpers/shell-dom.mjs';
import {CONSOLE_HTML,CONSOLE_JS} from '../../workers/researcher-intake/src/contextual-console.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
test('protected operator startup/status are reads; only the explicit action sends canonical IDs',async()=>{
  const dom=shellDom(CONSOLE_HTML),calls=[],release='a'.repeat(64),c=dom.context;
  Object.assign(c,{URLSearchParams,clearTimeout,fetch:async(url,options)=>{calls.push({url,options});
    return Response.json(url.endsWith('/manifest')?{release_id:release,public_activation:false,scopes:[{id:'call',title:'Approved scope'}]}:
      {release_id:release,scope_id:'call',state:'insufficient_source'});}});
  vm.createContext(c);vm.runInContext(CONSOLE_JS,c);await tick();
  assert.equal(calls.length,1);assert.equal(calls[0].options.method,undefined);
  dom.document.getElementById('scope').value='call';
  dom.dispatch('click',dom.document.getElementById('read'));await tick();assert.equal(calls.at(-1).options.method,undefined);
  dom.dispatch('click',dom.document.getElementById('build'));await tick();
  assert.equal(calls.filter(r=>r.options.method==='POST').length,1);
  assert.deepEqual(JSON.parse(calls.at(-1).options.body),{release_id:release,scope_id:'call',person_id:''});
  assert.equal(dom.document.getElementById('status').textContent,'insufficient_source');
  dom.document.getElementById('person').value='https://untrusted.example';
  dom.dispatch('click',dom.document.getElementById('build'));await tick();assert.equal(calls.length,3);
  assert.match(dom.document.getElementById('status').textContent,/canonical researcher ID/);
});
