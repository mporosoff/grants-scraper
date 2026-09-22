// Restricted measurement only. No credentials, provider content or public telemetry.
(()=>{
  const original=globalThis.fetch.bind(globalThis),calls=[],observations=[],lifecycle=[],longTasks=[];
  const limits={calls:2048,observations:512,lifecycle:128,long_tasks:128};
  const totals={calls:0,observations:0,lifecycle:0,long_tasks:0};
  const dropped={calls:0,observations:0,lifecycle:0,long_tasks:0,invalid_long_tasks:0};
  const now=()=>performance.timeOrigin+performance.now();
  const bounded=(value,limit)=>String(value).slice(0,limit);
  const retain=(name,rows,row)=>{totals[name]++;if(rows.length<limits[name])rows.push(row);else dropped[name]++;};
  const pageState=()=>({visibility:typeof document.visibilityState==='string'?bounded(document.visibilityState,32):null,
    focused:typeof document.hasFocus==='function'?document.hasFocus():null});
  const availability={visibility:typeof document.visibilityState==='string',focus:typeof document.hasFocus==='function',
    long_tasks:'unsupported',long_task_publication:'next-observer-output'};
  const startHeap=performance.memory?.usedJSHeapSize??null;
  let active=null,serial=0,scheduled=null,baseline=null,outputNode;
  const output=()=>{
    if(!document.body)return;
    if(!outputNode){outputNode=document.createElement('output');outputNode.id='contextual-validation-boundary';outputNode.hidden=true;document.body.appendChild(outputNode);}
    outputNode.textContent=JSON.stringify({version:'iteration2-measurement-v2',calls,observations,active,
      diagnostics:{availability,limits,totals,dropped,lifecycle,long_tasks:longTasks,
        completion_guard:'fresh-owned-proposal-through-two-animation-frames'},
      hardware:{userAgent:bounded(navigator.userAgent,512),logicalProcessors:navigator.hardwareConcurrency},
      initialHeap:startHeap,heap:performance.memory?.usedJSHeapSize??null});
  };
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href),method=options.method||'GET';
    const allowed=url.origin===location.origin&&(url.pathname.startsWith('/admin/contextual/iteration2/')||url.pathname.startsWith('/admin/api/contextual/'));
    const row={path:bounded(url.pathname,1024),query:bounded(url.search,2048),method:bounded(method,16),allowed,started:now()};
    retain('calls',calls,row);
    if(!allowed){output();throw Error('Restricted validation blocks unrelated service traffic.');}
    try{const response=await original(input,options);row.status=response.status;return response;}
    catch(error){row.error=bounded(error.name,80);throw error;}
    finally{row.duration=now()-row.started;output();}
  };
  const proposal=()=>document.getElementById('team-builder')?.querySelector('.opportunity-team-next');
  function cancelFrames(){if(scheduled){cancelAnimationFrame(scheduled.frame);scheduled=null;}}
  function rendered(){
    if(!active||scheduled)return;
    const node=proposal();
    // Every successful panel action replaces the proposal body. Old or removed DOM is not a new render.
    if(!node||node===baseline)return;
    const ticket={id:active.id,node,dom_ready_at:now(),frame:null};scheduled=ticket;
    const owned=()=>{
      if(scheduled!==ticket||active?.id!==ticket.id)return false;
      if(proposal()===ticket.node)return true;
      scheduled=null;rendered();return false;
    };
    ticket.frame=requestAnimationFrame(()=>{
      if(!owned())return;
      ticket.raf1_at=now();
      ticket.frame=requestAnimationFrame(()=>{
        if(!owned())return;
        scheduled=null;
        const end=now();
        retain('observations',observations,{...active,end,elapsed_ms:end-active.start,post_count:calls.filter(r=>r.method==='POST').length,
          heap:performance.memory?.usedJSHeapSize??null,endpoint:'validated-composer-render',
          diagnostics:{...active.diagnostics,dom_ready_at:ticket.dom_ready_at,raf1_at:ticket.raf1_at,raf2_at:end,end_state:pageState(),
            phase_ms:{click_to_dom:ticket.dom_ready_at-active.start,dom_to_raf1:ticket.raf1_at-ticket.dom_ready_at,raf1_to_raf2:end-ticket.raf1_at}}});
        active=null;baseline=null;output();
      });
    });
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-opportunity-team], [data-opportunity-team-scope], [data-opportunity-team-remove], [data-opportunity-team-add-replacement], [data-opportunity-team-variant]');
    if(!target)return;
    if(active)retain('observations',observations,{...active,disposition:'superseded-before-completion'});
    cancelFrames();baseline=proposal();
    active={id:++serial,kind:target.hasAttribute('data-opportunity-team')||target.hasAttribute('data-opportunity-team-scope')?'build':target.hasAttribute('data-opportunity-team-variant')?'option':'local-edit',
      start:now(),post_count_before:calls.filter(r=>r.method==='POST').length,
      heap:performance.memory?.usedJSHeapSize??null,diagnostics:{start_state:pageState()}};
    output();queueMicrotask(rendered);
  },true);
  const recordLifecycle=event=>{
    retain('lifecycle',lifecycle,{type:event.type,at:now(),action_id:active?.id??null,...pageState(),
      ...(typeof event.persisted==='boolean'?{persisted:event.persisted}:{})});output();
  };
  for(const type of ['visibilitychange','freeze','resume'])document.addEventListener(type,recordLifecycle);
  for(const type of ['focus','blur','pagehide','pageshow'])addEventListener(type,recordLifecycle);
  if(typeof PerformanceObserver==='function'&&PerformanceObserver.supportedEntryTypes?.includes('longtask')){
    try{
      const observer=new PerformanceObserver(list=>{
        // Deliberately omit names, attribution, URLs and content. Publish with the next existing output.
        for(const entry of list.getEntries()){
          if(!Number.isFinite(entry.startTime)||!Number.isFinite(entry.duration)||entry.startTime<0||entry.duration<0){dropped.invalid_long_tasks++;continue;}
          retain('long_tasks',longTasks,{start:performance.timeOrigin+entry.startTime,duration:entry.duration,
            end:performance.timeOrigin+entry.startTime+entry.duration});
        }
      });
      observer.observe({type:'longtask',buffered:true});availability.long_tasks='available';
    }catch{availability.long_tasks='observe-failed';}
  }
  addEventListener('DOMContentLoaded',()=>{
    output();new MutationObserver(records=>{if(records.some(r=>r.target!==outputNode))rendered();}).observe(document.body,{childList:true,subtree:true});
  });
})();
