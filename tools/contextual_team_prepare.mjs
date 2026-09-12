import fs from 'node:fs';
import {gzipSync} from 'node:zlib';
import {loadCanonicalInputs,buildSnapshot,assessmentPerson,hash,canonical,resolveCanonicalScope} from './contextual_team_inputs.mjs';
const doc='docs/team-recommender/contextual-stage-b',out='outputs/contextual-stage-b';
fs.mkdirSync(doc,{recursive:true});fs.mkdirSync(out,{recursive:true});
const clock='2026-09-12T16:00:00Z';
const selection=[
 ['361207','Auditory tissue-resource provision; known topic-versus-task diagnostic'],
 ['361208','Auditory network coordination; distinct requested activity'],
 ['332894','Qubit research parent; prior quantum/technology discussion diagnostic'],
 ['344592:ab-0025','Native electrochemistry child; catalysis and method-transfer possibilities'],
 ['345241:tdac-baa-004','Second-parent quantum-analysis child; inspect known limited context'],
 ['362856','Bone-marrow multiomic resource; clinical/research resource distinction'],
 ['363069','Cemetery-history investigation; directory/no-supported-group diagnostic'],
 ['344592','Unselected broad parent; no inference should choose a child'],
].map(([id,reason])=>({id,reason}));
const inputs=loadCanonicalInputs(),snapshot=buildSnapshot(inputs,selection.map(s=>s.id),clock);
const lock={version:'contextual-eight-scopes-v1',clock,selection,
  rule:'Named canonical source/activity strata locked before new retrieval/assessment outputs; historical cases are diagnostics, not untouched confirmation.',
  shortlist:{per_contribution:12,maximum:12,allocation:'Contribution-order round robin by rank; deduplicate people; canonical-ID ties; no lexical gate or historical threshold.'},
  independent_check:{maximum_requests:4,rule:'First two coherent graph-producing source groups by fixed selection order: one compact group/every-member applicability packet and one explanation packet per group. If fewer output groups exist, report the unexecuted denominator. No replacement after grades.',
    model:'claude-sonnet-5',independence:'Separate call, same family; correlated errors remain possible.',human_items:0},
  recommendation_outputs_observed:0,registry_generation:snapshot.registry_generation,roster_id:snapshot.roster_id,snapshot_id:snapshot.snapshot_id};
const lockPath=doc+'/input-lock-v1.json';
if(fs.existsSync(lockPath)&&canonical(JSON.parse(fs.readFileSync(lockPath)))!==canonical(lock))throw Error('immutable_input_lock_changed');
fs.writeFileSync(lockPath,JSON.stringify(lock,null,2)+'\n');
const bytes=Buffer.from(canonical(snapshot));fs.writeFileSync(out+'/snapshot-'+snapshot.snapshot_id+'.json',bytes);
fs.writeFileSync(out+'/assessment-people.json',JSON.stringify(snapshot.people.map(assessmentPerson)));
const people=snapshot.people.map(p=>({id:p.person_id,input_id:p.input_id,evidence_id:p.evidence_id,
  text_bytes:Buffer.byteLength(p.text),assessment_bytes:Buffer.byteLength(canonical(assessmentPerson(p))),active_claims:p.evidence.claims.length}));
const routing=JSON.parse(fs.readFileSync('docs/team-recommender/manifests/rollout.json'));
const inventories=Object.fromEntries([50,150].map(n=>['rollout'+n,routing['cohort_'+n].map(id=>{
  const s=resolveCanonicalScope(inputs,id,clock);return {id,parent_id:s.parent_id,state:s.state,action_current:s.action_current===true,
    canonical:!!s.source_id,compatible_cached:false,source_id:s.source_id||null};})]));
const receipt={version:1,clock,registry_generation:snapshot.registry_generation,directory_records:inputs.directory.researchers.length,
  eligible_people:people.length,active_claims:people.reduce((n,p)=>n+p.active_claims,0),source_gaps:inputs.registry.researchers.filter(p=>p.source_audit?.disposition==='unresolved').map(p=>p.researcher_id),
  snapshot_id:snapshot.snapshot_id,snapshot_bytes:bytes.length,gzip_bytes:gzipSync(bytes).length,
  space:snapshot.space,people,scopes:snapshot.scopes.map(s=>({id:s.id,parent_id:s.parent_id,title:s.science?.title,state:s.state,source_id:s.source_id,
    scientific_bytes:Buffer.byteLength(canonical({science:s.science,conditions:s.conditions})),limitations:s.limitations})),
  input_files:inputs.files,computed_recommendations:0,new_provider_calls:0,public_activation:false};
fs.writeFileSync(doc+'/input-receipt-v1.json',JSON.stringify(receipt,null,2)+'\n');
fs.writeFileSync(doc+'/routing-inventory-v1.json',JSON.stringify({clock,paid_prewarming:0,inventories},null,2)+'\n');
console.log(JSON.stringify({registry:receipt.registry_generation,people:people.length,active_claims:receipt.active_claims,source_gaps:receipt.source_gaps,
  bytes:bytes.length,gzip:receipt.gzip_bytes,largest12_assessment_bytes:people.map(p=>p.assessment_bytes).sort((a,b)=>b-a).slice(0,12).reduce((a,b)=>a+b,0),
  scopes:receipt.scopes.map(s=>({id:s.id,state:s.state,bytes:s.scientific_bytes})),snapshot:out+'/snapshot-'+snapshot.snapshot_id+'.json'}));
