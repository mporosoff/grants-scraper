// A restricted operator control, not the public recommender interface. It uses
// the existing Access session on its own origin and never exports credentials.
export const CONSOLE_HTML=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Restricted contextual validation | Funding Finder</title><link rel="stylesheet" href="/admin/styles.css">
<script src="/admin/contextual/app.js" defer></script></head><body><main><h1>Restricted contextual validation</h1>
<p>Public team serving is off. Only the explicit assessment button may start metered work within the existing finite allowance.</p>
<label for="scope">Locked funding scope</label><select id="scope" disabled></select>
<label for="person">Canonical person ID (leave empty for Build)</label><input id="person" maxlength="10" pattern="urh-[0-9]{6}">
<p>Providing a person ID requests the single permitted extension for an unassessed eligible person. It does not change the registry.</p>
<button id="build" disabled>Build or explicitly assess this person</button><button id="read" disabled>Read status only</button>
<p id="status" role="status" aria-live="polite">Loading the approved manifest. No assessment has been requested.</p>
<label for="result">Bounded result receipt</label><textarea id="result" readonly rows="18"></textarea>
</main></body></html>`;

export const CONSOLE_JS=`(()=>{'use strict';
const scope=document.getElementById('scope'),person=document.getElementById('person'),build=document.getElementById('build'),read=document.getElementById('read');
const status=document.getElementById('status'),result=document.getElementById('result');let manifest,sequence=0,timer;
const root='/admin/api/contextual';
async function json(url,options={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',redirect:'error',...options});
  const text=await r.text();if(text.length>200000)throw Error('Response exceeds the validation bound.');
  const value=JSON.parse(text);if(!r.ok)throw Error(value.error||value.state||('HTTP '+r.status));return value;}
function reset(){sequence++;clearTimeout(timer);build.disabled=!manifest;read.disabled=!manifest;result.value='';status.textContent='Selection changed. Read status or explicitly request assessment.';}
async function action(paid){clearTimeout(timer);const own=++sequence;build.disabled=true;read.disabled=true;
  try{const ids={release_id:manifest.release_id,scope_id:scope.value,person_id:person.value.trim()};
    if(ids.person_id&&!/^urh-[0-9]{6}$/.test(ids.person_id))throw Error('Use an existing canonical researcher ID.');
    let value=await json(root+'/jobs'+(paid?'':'?'+new URLSearchParams(ids)),paid?
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ids)}:{});
    let polls=0;
    const display=async()=>{if(own!==sequence)return;
      if(value.release_id!==manifest.release_id||value.scope_id&&value.scope_id!==ids.scope_id)throw Error('Response identity conflict.');
      status.textContent=value.state;result.value=JSON.stringify(value,null,2);
      if(['dispatch_claimed','in_progress'].includes(value.state)&&polls++<120)timer=setTimeout(async()=>{
        try{value=await json(root+'/jobs?'+new URLSearchParams(ids));await display();}
        catch(error){if(own===sequence)status.textContent=error.message+' No automatic new request was sent.';}},5000);
    };await display();
  }catch(error){if(own===sequence)status.textContent=error.message+' No automatic new request was sent.';}
  finally{if(own===sequence){build.disabled=false;read.disabled=false;}}
}
scope.addEventListener('change',reset);person.addEventListener('input',reset);
build.addEventListener('click',()=>action(true));read.addEventListener('click',()=>action(false));
addEventListener('pagehide',()=>{sequence++;clearTimeout(timer);});
json(root+'/manifest').then(value=>{manifest=value;if(value.public_activation!==false)throw Error('Restricted manifest required.');
  for(const item of value.scopes){const option=document.createElement('option');option.value=item.id;option.textContent=item.id+' — '+item.title;scope.appendChild(option);}
  scope.disabled=false;build.disabled=false;read.disabled=false;status.textContent='Ready. No assessment requested.';
}).catch(error=>{status.textContent=error.message;});
})();`;
