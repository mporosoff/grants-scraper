(()=>{
  const original=globalThis.fetch.bind(globalThis),calls=[];let initial=null;
  const output=()=>{if(!document.body)return;let node=document.getElementById('contextual-validation-boundary');if(!node){node=document.createElement('output');node.id='contextual-validation-boundary';node.hidden=true;document.body.appendChild(node);}
    node.textContent=JSON.stringify({calls,initial,access:globalThis.ContextualTeamAccess?.statistics(),heap:performance.memory?.usedJSHeapSize??null});};
  globalThis.fetch=async(input,options={})=>{const url=new URL(typeof input==='string'?input:input.url,location.href),method=options.method||'GET';
    const allowed=url.origin===location.origin&&(url.pathname.startsWith('/admin/contextual/preview/')||url.pathname.startsWith('/admin/api/contextual/'));
    const row={origin:url.origin,path:url.pathname,query:url.search,method,allowed,started:performance.now()};calls.push(row);
    if(!allowed){output();throw Error('Private validation blocks unrelated service traffic.');}
    try{const response=await original(input,options);row.status=response.status;return response;}catch(error){row.error={name:error.name,message:error.message};throw error;}finally{row.duration=performance.now()-row.started;output();}};
  document.addEventListener('click',event=>{if(event.target.closest('[data-opportunity-team]')&&!initial){initial={time:performance.now(),heap:performance.memory?.usedJSHeapSize??null};output();}},true);
  addEventListener('DOMContentLoaded',output);
  addEventListener('message',()=>setTimeout(output,0));
})();
