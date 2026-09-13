/* Explicit restricted validation connection; no credentials leave Access. */
(function(g){
  'use strict';
  const origin='https://funding-finder-researchers.urochestercheme.workers.dev',protocol='contextual-access-v1';
  const enabled=()=>g.location?.origin==='http://127.0.0.1:8876'&&g.document.querySelector('meta[name="contextual-validation-transport"]')?.content==='access-window-v1';
  const id=()=>Array.from(crypto.getRandomValues(new Uint8Array(16))).map(v=>v.toString(16).padStart(2,'0')).join('');
  let connection=null;const pending=new Map(),counts={opens:0,reads:0,explicit_posts:0},measurements=[];
  function prepare(){
    if(!enabled())return;
    if(connection&&!connection.window.closed)return;
    const channel=id(),win=g.open(origin+'/admin/contextual/access#'+channel,'_blank','popup,width=580,height=260');
    if(!win)return;
    counts.opens++;let ready;
    const promise=new Promise((resolve,reject)=>{ready=resolve;setTimeout(()=>reject(Error('contextual_access_connection_timeout')),30000);});
    promise.catch(()=>{});connection={window:win,channel,promise,ready};
  }
  g.addEventListener('message',event=>{
    const c=connection,m=event.data;
    if(!c||event.origin!==origin||event.source!==c.window||!m||m.protocol!==protocol||m.channel!==c.channel)return;
    if(m.action==='ready'){c.ready();return;}
    const p=pending.get(m.id);if(m.action!=='response'||!p||p.channel!==c.channel)return;
    pending.delete(m.id);clearTimeout(p.timer);
    measurements.push({method:p.method,status:m.status||null,elapsed_ms:performance.now()-p.started});
    if(measurements.length>256)measurements.shift();
    if(m.error||typeof m.body!=='string'||new TextEncoder().encode(m.body).length>200000||!Number.isInteger(m.status)||m.status<200||m.status>599)
      p.reject(Error('contextual_protected_connection_unavailable'));
    else p.resolve(new Response(m.body,{status:m.status,headers:{'Content-Type':'application/json'}}));
  });
  async function request(url,options={}){
    if(!enabled()||!connection||connection.window.closed)throw Error('contextual_access_connection_required');
    const u=new URL(url),method=options.method||'GET';
    if(u.origin!==origin||u.pathname!=='/admin/api/contextual/jobs'||!['GET','POST'].includes(method))throw Error('contextual_access_operation_rejected');
    const ids=method==='POST'?JSON.parse(options.body):Object.fromEntries(u.searchParams);
    if(Object.keys(ids).sort().join(',')!=='person_id,release_id,scope_id')throw Error('contextual_access_identity_rejected');
    const c=connection;await c.promise;
    if(c!==connection||c.window.closed)throw Error('contextual_access_connection_changed');
    if(pending.size>=16)throw Error('contextual_access_concurrency_bound');
    const requestId=id();counts[method==='POST'?'explicit_posts':'reads']++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{pending.delete(requestId);reject(Error('contextual_access_response_timeout'));},20000);
      pending.set(requestId,{resolve,reject,timer,channel:c.channel,method,started:performance.now()});
      c.window.postMessage({protocol,channel:c.channel,action:'request',id:requestId,method,ids},origin);
    });
  }
  g.document.addEventListener('click',event=>{
    if(event.target.closest('[data-opportunity-team],[data-opportunity-team-retry],[data-contextual-assess]'))prepare();
  },true);
  g.ContextualTeamAccess=Object.freeze({prepare,fetch:request,statistics:()=>({...counts,pending:pending.size,measurements:measurements.map(v=>({...v}))})});
})(globalThis);
