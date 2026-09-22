// Same administrator Access, separate finite I3 release. Loading never builds.
export const ITERATION3_HTML=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Iteration 3 restricted validation | Funding Finder</title><link rel="stylesheet" href="/admin/styles.css">
<script src="/admin/contextual/iteration3-control.js" defer></script></head><body><main>
<h1>Iteration 3 restricted validation</h1><p>Public recommendations remain off. Only these three named corrective cases can run under the existing allowance. Historical results remain separate.</p>
<button id="enable" disabled>Enable three corrective builds</button><button id="disable" disabled>Stop new paid builds</button>
<p id="status" role="status">Reading controls. No assessment requested.</p><ul id="cases"></ul>
<a href="/admin/contextual/iteration3/match_explorer.html">Open the restricted interface</a>
</main></body></html>`;
export const ITERATION3_JS=`(()=>{'use strict';
const status=document.getElementById('status'),enable=document.getElementById('enable'),disable=document.getElementById('disable');let release;
async function read(path,body){const r=await fetch('/admin/api/contextual/'+path,{credentials:'same-origin',cache:'no-store',redirect:'error',
  ...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  if(!r.ok)throw Error('Restricted control unavailable: '+r.status);return r.json();}
async function control(paid){const c=await read('controls?release_id='+release,paid===undefined?undefined:{cached_enabled:true,new_paid_enabled:paid});
  status.textContent=c.new_paid_enabled?'Three corrective builds enabled. No build has been requested here.':'New paid builds disabled. Cached reads remain available.';}
for(const [button,paid]of [[enable,true],[disable,false]])button.addEventListener('click',()=>control(paid).catch(e=>status.textContent=e.message));
read('manifest?iteration=3').then(async m=>{release=m.release_id;if(m.public_activation!==false||m.scopes.length!==3)throw Error('Restricted manifest required');
  for(const s of m.scopes){const li=document.createElement('li'),a=document.createElement('a');
    a.href='/admin/contextual/iteration3/match_explorer.html?q='+encodeURIComponent(s.title);a.textContent=s.id+' — '+s.title+' ('+s.state+')';li.appendChild(a);document.getElementById('cases').appendChild(li);}
  await control();enable.disabled=false;disable.disabled=false;
}).catch(e=>status.textContent=e.message);
})();`;
