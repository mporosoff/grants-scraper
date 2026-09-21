// Existing administrator Access owns this finite development control.
export const ITERATION2_HTML=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Iteration 2 restricted validation | Funding Finder</title><link rel="stylesheet" href="/admin/styles.css">
<script src="/admin/contextual/iteration2-control.js" defer></script></head><body><main>
<h1>Iteration 2 restricted validation</h1><p>Public recommendations remain off. This control enables only the frozen development cases under the existing pooled allowance. Confirmation cases are unavailable.</p>
<button id="enable" disabled>Enable finite development builds</button><button id="disable" disabled>Stop new paid builds</button>
<p id="status" role="status">Reading controls. No assessment requested.</p><ul id="cases"></ul>
<a href="/admin/contextual/iteration2/match_explorer.html">Open the existing restricted interface</a>
</main></body></html>`;
export const ITERATION2_JS=`(()=>{'use strict';
const status=document.getElementById('status'),enable=document.getElementById('enable'),disable=document.getElementById('disable');let release;
async function read(path,body){const r=await fetch('/admin/api/contextual/'+path,{credentials:'same-origin',cache:'no-store',redirect:'error',
  ...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  if(!r.ok)throw Error('Restricted control unavailable: '+r.status);return r.json();}
async function control(paid){const c=await read('controls?release_id='+release,paid===undefined?undefined:{cached_enabled:true,new_paid_enabled:paid});
  status.textContent=c.new_paid_enabled?'Finite development builds enabled. No build has been requested here.':'New paid builds disabled. Cached reads remain available.';}
for(const [button,paid]of [[enable,true],[disable,false]])button.addEventListener('click',()=>control(paid).catch(e=>status.textContent=e.message));
read('manifest?iteration=2').then(async m=>{release=m.release_id;if(m.public_activation!==false)throw Error('Restricted manifest required');
  for(const s of m.scopes){const li=document.createElement('li'),a=document.createElement('a');
    a.href='/admin/contextual/iteration2/match_explorer.html?q='+encodeURIComponent(s.title);a.textContent=s.id+' — '+s.title+' ('+s.state+')';li.appendChild(a);document.getElementById('cases').appendChild(li);}
  await control();enable.disabled=false;disable.disabled=false;
}).catch(e=>status.textContent=e.message);
})();`;
