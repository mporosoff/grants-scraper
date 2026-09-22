// Deterministic observer and real-panel contracts; no browser, providers or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {shellDom} from '../helpers/shell-dom.mjs';

const source=fs.readFileSync('workers/researcher-intake/iteration2-source/assets/contextual-preview-observer.js','utf8');
const panelSource=fs.readFileSync('workers/researcher-intake/iteration2-source/assets/opportunity-team-panel.js','utf8');
function fixture({longTasks='unsupported',pageState=true}={}){
  const dom=shellDom('<html><body><article class="result-card"><button id="build" data-opportunity-team="fixture" data-opportunity-team-scope="fixture">Build</button></article>'+
    '<button id="option" data-opportunity-team-variant="0">Option</button><button id="edit" data-opportunity-team-remove="fixture">Remove</button>'+
    '<dialog id="team-builder"><div id="team-builder-content"></div></dialog><p id="search-status"></p></body></html>');
  const c=dom.context,clock={time:0,focused:true},frames=new Map(),microtasks=[],network=[],mutations=[];
  const dispatch=dom.dispatch;
  dom.dispatch=(type,target,extra)=>{
    target.hasAttribute=name=>target.getAttribute(name)!==null;
    return dispatch(type,target,extra);
  };
  let nextFrame=0,longTaskCallback,observeOptions;
  if(pageState){dom.document.visibilityState='visible';dom.document.hasFocus=()=>clock.focused;}
  class Observer{
    static supportedEntryTypes=longTasks==='unsupported'?[]:['longtask'];
    constructor(callback){longTaskCallback=callback;}
    observe(options){if(longTasks==='error')throw Error('synthetic unsupported observer');observeOptions=options;}
  }
  Object.assign(c,{URL,location:{href:'https://example.test/admin/contextual/iteration2/match_explorer.html',origin:'https://example.test'},
    navigator:{userAgent:'synthetic observer fixture',hardwareConcurrency:4},performance:{timeOrigin:100000,now:()=>clock.time},
    fetch:async(...args)=>{network.push(args);return {status:200};},
    requestAnimationFrame:callback=>{frames.set(++nextFrame,callback);return nextFrame;},cancelAnimationFrame:id=>frames.delete(id),
    queueMicrotask:callback=>microtasks.push(callback),
    MutationObserver:class{constructor(callback){mutations.push(callback);}observe(){}},PerformanceObserver:Observer});
  vm.createContext(c);vm.runInContext(source,c);
  const emit=(type,extra={})=>dom.windowListeners.filter(x=>x.type===type).forEach(x=>x.callback({type,...extra}));
  emit('DOMContentLoaded');
  const drawer=dom.document.getElementById('team-builder'),content=dom.document.getElementById('team-builder-content');
  const read=()=>JSON.parse(dom.document.getElementById('contextual-validation-boundary').textContent);
  const mutate=()=>mutations.forEach(callback=>callback([{target:content}]));
  const flush=()=>{while(microtasks.length)microtasks.shift()();};
  return {c,dom,clock,frames,network,drawer,content,read,emit,mutate,flush,
    click:(kind='build')=>{dom.dispatch('click',dom.document.getElementById(kind));flush();},
    render:()=>{content.innerHTML='<div class="opportunity-team-next">Synthetic proposal</div>';mutate();},
    frame:time=>{clock.time=time;const pending=[...frames.values()];frames.clear();pending.forEach(callback=>callback(time));},
    longTasks:entries=>longTaskCallback({getEntries:()=>entries}),observeOptions:()=>observeOptions};
}

test('v2 keeps click-to-second-frame completion and exposes exact phase attribution',()=>{
  const f=fixture();f.clock.time=100;f.click();f.clock.time=150;f.render();
  assert.equal(f.read().observations.length,0);assert.equal(f.frames.size,1);
  f.frame(1150);assert.equal(f.read().observations.length,0);assert.equal(f.frames.size,1);
  f.frame(2150);
  const report=f.read(),row=report.observations[0];
  assert.equal(report.version,'iteration2-measurement-v2');assert.equal(row.start,100100);
  assert.equal(row.end,102150);assert.equal(row.elapsed_ms,2050);assert.equal(row.endpoint,'validated-composer-render');
  assert.equal(row.post_count_before,0);assert.equal(row.post_count,0);assert.equal(report.active,null);
  assert.deepEqual(row.diagnostics,{start_state:{visibility:'visible',focused:true},dom_ready_at:100150,
    raf1_at:101150,raf2_at:102150,end_state:{visibility:'visible',focused:true},
    phase_ms:{click_to_dom:50,dom_to_raf1:1000,raf1_to_raf2:1000}});
  assert.equal(Object.values(row.diagnostics.phase_ms).reduce((a,b)=>a+b,0),row.elapsed_ms);
  assert.deepEqual(f.network,[]);
});

test('fresh-owned-proposal guard rejects pre-existing DOM and DOM removed between frames',()=>{
  const f=fixture();f.render();f.click('option');f.mutate();f.flush();
  assert.equal(f.frames.size,0);assert.equal(f.read().observations.length,0);
  f.clock.time=20;f.render();f.frame(30);f.content.innerHTML='<p>Temporarily unavailable</p>';f.mutate();f.frame(40);
  assert.equal(f.read().observations.length,0);assert.equal(f.frames.size,0);
  f.clock.time=50;f.render();f.frame(60);f.frame(70);
  assert.equal(f.read().observations.length,1);assert.equal(f.read().observations[0].diagnostics.dom_ready_at,100050);
});

test('superseding actions cancel old frame work and replacement DOM requires its own two frames',()=>{
  const f=fixture();f.click();f.render();f.frame(10);f.clock.time=20;f.click('edit');
  assert.equal(f.frames.size,0);assert.equal(f.read().observations[0].disposition,'superseded-before-completion');
  assert.equal(f.read().observations[0].end,undefined);
  f.clock.time=30;f.render();f.frame(40);f.clock.time=45;f.render();f.frame(50);
  assert.equal(f.read().observations.length,1);assert.equal(f.frames.size,1);
  f.frame(60);assert.equal(f.read().observations.length,1);f.frame(70);
  const row=f.read().observations[1];assert.equal(row.id,2);assert.equal(row.kind,'local-edit');
  assert.equal(row.start,100020);assert.equal(row.diagnostics.dom_ready_at,100050);assert.equal(row.elapsed_ms,50);
});

test('visibility, focus and lifecycle changes are supplementary and never shorten completion',()=>{
  const f=fixture();f.click();f.clock.time=2;f.dom.document.visibilityState='hidden';f.clock.focused=false;
  f.dom.dispatch('visibilitychange',f.dom.document.body);f.emit('blur');f.emit('pagehide',{persisted:true});
  f.clock.time=10;f.render();f.frame(1010);assert.equal(f.read().observations.length,0);
  f.clock.time=1500;f.dom.document.visibilityState='visible';f.clock.focused=true;
  f.dom.dispatch('visibilitychange',f.dom.document.body);f.emit('focus');f.emit('pageshow',{persisted:true});f.frame(2010);
  const report=f.read(),row=report.observations[0];
  assert.equal(row.elapsed_ms,2010);assert.deepEqual(row.diagnostics.start_state,{visibility:'visible',focused:true});
  assert.deepEqual(row.diagnostics.end_state,{visibility:'visible',focused:true});
  assert.deepEqual(report.diagnostics.lifecycle.map(e=>e.type),['visibilitychange','blur','pagehide','visibilitychange','focus','pageshow']);
  assert.equal(report.diagnostics.lifecycle[2].persisted,true);assert.equal(report.diagnostics.lifecycle[0].action_id,1);
  assert.deepEqual(f.network,[]);
});

test('optional long tasks retain numeric timing only and publish without additional fetch or timers',()=>{
  const f=fixture({longTasks:'available'});assert.equal(f.read().diagnostics.availability.long_tasks,'available');
  assert.deepEqual(JSON.parse(JSON.stringify(f.observeOptions())),{type:'longtask',buffered:true});
  f.longTasks([{startTime:5,duration:80,name:'PRIVATE CONTENT',attribution:[{containerSrc:'https://private.invalid'}]},
    {startTime:NaN,duration:80},{startTime:10,duration:-1}]);
  f.emit('focus');const d=f.read().diagnostics;
  assert.deepEqual(d.long_tasks,[{start:100005,duration:80,end:100085}]);assert.equal(d.dropped.invalid_long_tasks,2);
  assert.equal(d.availability.long_task_publication,'next-observer-output');
  assert(!JSON.stringify(f.read()).includes('PRIVATE'));assert(!JSON.stringify(f.read()).includes('private.invalid'));
  assert.deepEqual(f.network,[]);assert.equal(f.frames.size,0);
});

test('unsupported or failed supplemental APIs are explicit and do not block the existing endpoint',()=>{
  for(const mode of ['unsupported','error']){
    const f=fixture({longTasks:mode,pageState:false});f.click();f.render();f.frame(5);f.frame(10);
    const report=f.read();assert.equal(report.observations[0].elapsed_ms,10);
    assert.equal(report.diagnostics.availability.long_tasks,mode==='error'?'observe-failed':'unsupported');
    assert.equal(report.diagnostics.availability.visibility,false);assert.equal(report.diagnostics.availability.focus,false);
    assert.deepEqual(report.observations[0].diagnostics.start_state,{visibility:null,focused:null});
    assert.deepEqual(report.diagnostics.long_tasks,[]);
  }
});

test('observation, lifecycle, long-task and request caps expose dropped denominators',async()=>{
  const f=fixture({longTasks:'available'}),limits=f.read().diagnostics.limits;
  for(let n=0;n<limits.observations+2;n++)f.click();
  for(let n=0;n<limits.lifecycle+3;n++)f.emit('focus');
  f.longTasks(Array.from({length:limits.long_tasks+4},(_,i)=>({startTime:i,duration:60})));
  for(let n=0;n<limits.calls+5;n++)await f.c.fetch('/admin/api/contextual/jobs');
  const report=f.read(),d=report.diagnostics;
  for(const [key,count] of [['observations',limits.observations+1],['lifecycle',limits.lifecycle+3],
    ['long_tasks',limits.long_tasks+4],['calls',limits.calls+5]]){
    assert.equal(d.totals[key],count);assert.equal(d.dropped[key],count-limits[key]);
    assert.equal((report[key]||d[key]).length,limits[key]);
  }
  assert.equal(report.active.id,limits.observations+2);assert.equal(f.frames.size,0);
  assert.equal(f.network.length,limits.calls+5);
});

test('route restriction and forwarding remain exact, with zero supplemental HTTP calls',async()=>{
  const f=fixture();const options={method:'POST',body:'synthetic'};
  await f.c.fetch('/admin/api/contextual/jobs',options);
  await f.c.fetch('/admin/contextual/iteration2/asset.js');
  for(const url of ['/admin/contextual/preview/asset.js','https://foreign.test/admin/api/contextual/jobs','/unrelated'])
    await assert.rejects(f.c.fetch(url),/Restricted validation blocks unrelated service traffic/);
  f.click();f.render();f.frame(5);f.frame(10);f.emit('focus');
  assert.equal(f.network.length,2);assert.equal(f.network[0][0],'/admin/api/contextual/jobs');assert.equal(f.network[0][1],options);
  assert.deepEqual(f.read().calls.map(row=>row.allowed),[true,true,false,false,false]);
  assert.equal(f.read().observations[0].post_count,1);
});

test('actual panel build, option, removal and restoration replace the proposal marker',async()=>{
  const f=fixture(),opportunity={id:'fixture',parent_id:'fixture',record_type:'parent',scope_label:'Synthetic scope',
    members:[],missing_skills:[],gate_state:'pass'},profiles=['one','two'].map(id=>({id,name:'Synthetic '+id,source_url:'https://example.test'}));
  const state=ids=>({opportunityId:'fixture',selectedIds:ids}),engine={
    opportunityById:new Map([['fixture',opportunity]]),facultyById:new Map(profiles.map(p=>[p.id,p])),
    scopesFor:()=>[opportunity],resolveScope:()=>({ok:true,opportunity}),proposal:()=>state(['one']),
    proposalOptions:()=>[{label:'First',state:state(['one'])},{label:'Second',state:state(['two'])}],
    removeMember:(s,id)=>state(s.selectedIds.filter(x=>x!==id)),addReplacement:(s,id)=>state([...s.selectedIds,id]),
    proposalView:s=>({opportunity,selectedIds:s.selectedIds,complete:true,roles:[],unfilledRoles:[],
      selected:profiles.filter(p=>s.selectedIds.includes(p.id)).map(profile=>({profile,roles:[],relevantTerms:[]})),
      replacements:profiles.filter(p=>!s.selectedIds.includes(p.id)).map(profile=>({profile,roles:[],reviewed:true}))})};
  Object.assign(f.c,{SiteShell:{openDrawer:d=>{d.open=true;},closeDrawer:d=>{d.open=false;}},
    GRANT_CATALOG:{opportunities:[{opportunity_id:'fixture'}]},
    OpportunityTeam:{pageGenerationId:()=> 'fixture',loadData:async()=>({}),create:()=>engine}});
  vm.runInContext(panelSource,f.c);
  const complete=async()=>{for(let i=0;i<10;i++)await Promise.resolve();f.mutate();f.flush();f.frame(f.clock.time+5);f.frame(f.clock.time+5);};
  f.click();await complete();let marker=f.drawer.querySelector('.opportunity-team-next');assert(marker);
  for(const action of ['option','remove','restore']){
    let target;
    if(action==='option')target=f.drawer.querySelector('[data-opportunity-team-variant="1"]');
    if(action==='remove')target=f.drawer.querySelector('[data-opportunity-team-remove]');
    if(action==='restore'){
      const select=f.drawer.querySelector('[data-opportunity-team-replacement]');select.value='one';f.dom.dispatch('change',select);
      target=f.drawer.querySelector('[data-opportunity-team-add-replacement]');
    }
    assert(target);f.dom.dispatch('click',target);await complete();
    const next=f.drawer.querySelector('.opportunity-team-next');assert(next);assert.notEqual(next,marker);assert.equal(marker.isConnected,false);marker=next;
  }
  assert.deepEqual(f.read().observations.map(row=>row.kind),['build','option','local-edit','local-edit']);
  assert(f.read().observations.every(row=>row.endpoint==='validated-composer-render'));
  assert.deepEqual(f.network,[]);
});
