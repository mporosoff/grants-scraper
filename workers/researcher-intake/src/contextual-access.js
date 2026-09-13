// Restricted same-origin Access session adapter. Never exports cookies/tokens.
// Only the already allowed local validation origin can request the fixed jobs API.
export const ACCESS_HTML='<!doctype html><html lang="en"><meta charset="utf-8"><title>Funding Finder validation connection</title><h1>Protected validation connection</h1><p id="status">Connecting the authorized local Funding Finder application. No assessment starts when this page opens.</p><script src="/admin/contextual/access.js"></script></html>';
export const ACCESS_JS=String.raw`(()=>{
  'use strict';
  const origin='http://127.0.0.1:8876',protocol='contextual-access-v1',owner=window.opener;
  const channel=location.hash.slice(1),pending=new Set();let connected=false;
  const status=document.getElementById('status');
  if(!owner||! /^[a-f0-9]{32}$/.test(channel)){status.textContent='Open this connection from the authorized validation application.';return;}
  const send=value=>owner.postMessage({protocol,channel,...value},origin);
  const ids=v=>v&&Object.keys(v).sort().join(',')==='person_id,release_id,scope_id'&&
    /^[a-f0-9]{64}$/.test(v.release_id)&&typeof v.scope_id==='string'&&v.scope_id.length<=100&&
    typeof v.person_id==='string'&&v.person_id.length<=80;
  addEventListener('message',async event=>{
    const m=event.data;
    if(event.source!==owner||event.origin!==origin||!m||m.protocol!==protocol||m.channel!==channel)return;
    if(m.action==='connect'){if(connected)send({action:'ready'});return;}
    if(!connected)return;
    if(m.action!=='request'||! /^[a-f0-9]{32}$/.test(m.id)||pending.has(m.id)||pending.size>=16||
      !['GET','POST'].includes(m.method)||!ids(m.ids)||Object.keys(m).sort().join(',')!=='action,channel,id,ids,method,protocol')return;
    pending.add(m.id);
    try{
      const url='/admin/api/contextual/jobs'+(m.method==='GET'?'?'+new URLSearchParams(m.ids):'');
      const response=await fetch(url,{method:m.method,credentials:'same-origin',redirect:'error',cache:'no-store',
        signal:AbortSignal.timeout(15000),...(m.method==='POST'?{headers:{'Content-Type':'application/json'},body:JSON.stringify(m.ids)}:{})});
      const bytes=await response.arrayBuffer();if(bytes.byteLength>200000)throw Error('bounded_result_exceeded');
      const body=new TextDecoder('utf-8',{fatal:true}).decode(bytes);JSON.parse(body);
      send({action:'response',id:m.id,status:response.status,body});
      status.textContent='Connected to the restricted validation application. Closing this window prevents new requests but does not cancel an assessment already dispatched.';
    }catch{send({action:'response',id:m.id,error:'protected_connection_unavailable'});}
    finally{pending.delete(m.id);}
  });
  fetch('/admin/api/contextual/fixture',{credentials:'same-origin',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(15000)})
    .then(async response=>{if(!response.ok)throw Error();const value=await response.json();
      if(value.fixture!==true||value.purpose!=='routing_only'||value.provider_work!==false||value.scientific_graph!==false)throw Error();
      connected=true;status.textContent='Authenticated routing fixture passed. No scientific graph or provider request was created.';
      send({action:'ready',routing_fixture:true});})
    .catch(()=>{status.textContent='Protected connection unavailable. No assessment was requested.';});
})();`;
