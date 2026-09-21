// Restricted measurement only. No credentials, provider content or public telemetry.
(()=>{
  const original=globalThis.fetch.bind(globalThis),calls=[],observations=[];
  const startHeap=performance.memory?.usedJSHeapSize??null;
  let active=null,serial=0,scheduled=false,outputNode;
  const output=()=>{
    if(!document.body)return;
    if(!outputNode){outputNode=document.createElement('output');outputNode.id='contextual-validation-boundary';outputNode.hidden=true;document.body.appendChild(outputNode);}
    outputNode.textContent=JSON.stringify({version:'iteration2-measurement-v1',calls,observations,active,
      hardware:{userAgent:navigator.userAgent,logicalProcessors:navigator.hardwareConcurrency},
      initialHeap:startHeap,heap:performance.memory?.usedJSHeapSize??null});
  };
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href),method=options.method||'GET';
    const allowed=url.origin===location.origin&&(url.pathname.startsWith('/admin/contextual/iteration2/')||url.pathname.startsWith('/admin/api/contextual/'));
    const row={path:url.pathname,query:url.search,method,allowed,started:performance.timeOrigin+performance.now()};
    if(calls.length<2048)calls.push(row);
    if(!allowed){output();throw Error('Restricted validation blocks unrelated service traffic.');}
    try{const response=await original(input,options);row.status=response.status;return response;}
    catch(error){row.error=error.name;throw error;}
    finally{row.duration=performance.timeOrigin+performance.now()-row.started;output();}
  };
  function rendered(){
    if(!active||scheduled)return;
    const panel=document.getElementById('team-builder');
    if(!panel||!panel.querySelector('.opportunity-team-next'))return;
    const own=active.id;scheduled=true;
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      scheduled=false;
      if(active?.id!==own)return;
      const end=performance.timeOrigin+performance.now();
      observations.push({...active,end,elapsed_ms:end-active.start,post_count:calls.filter(r=>r.method==='POST').length,
        heap:performance.memory?.usedJSHeapSize??null,endpoint:'validated-composer-render'});
      active=null;output();
    }));
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-opportunity-team], [data-opportunity-team-scope], [data-opportunity-team-remove], [data-opportunity-team-add-replacement], [data-opportunity-team-variant]');
    if(!target)return;
    if(active)observations.push({...active,disposition:'superseded-before-completion'});
    active={id:++serial,kind:target.hasAttribute('data-opportunity-team')||target.hasAttribute('data-opportunity-team-scope')?'build':target.hasAttribute('data-opportunity-team-variant')?'option':'local-edit',
      start:performance.timeOrigin+performance.now(),post_count_before:calls.filter(r=>r.method==='POST').length,
      heap:performance.memory?.usedJSHeapSize??null};
    output();queueMicrotask(rendered);
  },true);
  addEventListener('DOMContentLoaded',()=>{
    output();new MutationObserver(records=>{if(records.some(r=>r.target!==outputNode))rendered();}).observe(document.body,{childList:true,subtree:true});
  });
})();
