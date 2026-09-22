// Exact restricted composer; direct_source is a zero-network preflight mode only.
import fs from 'node:fs';
import vm from 'node:vm';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
const hash=raw=>createHash('sha256').update(raw).digest('hex');
const base=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const historical=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
if(historical.base_bundle_id!==base.bundle_id)throw Error('iteration3_historical_base_identity');
const data=JSON.parse(fs.readFileSync(0,'utf8')),graph=data.graph,c=vm.createContext({URL,Date});
if(Object.keys(data).some(k=>!['graph','direct_source'].includes(k))||
   data.direct_source!==undefined&&typeof data.direct_source!=='boolean')throw Error('iteration3_selection_arguments');
const direct=data.direct_source===true;
const overlay=direct?null:JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration3-preview-v1.json'));
if(overlay&&overlay.historical_iteration2_bundle_id!==historical.bundle_id)throw Error('iteration3_preview_base_identity');
let composer;
for(const name of ['data/researcher_directory.js','assets/contextual-team-engine.js']){
  let raw;
  if(direct&&name==='assets/contextual-team-engine.js')raw=fs.readFileSync('workers/researcher-intake/iteration2-source/'+name);
  else{
    const file=overlay?.files[name]||historical.files[name]||base.files[name];raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));
    if(hash(raw)!==file.sha256)throw Error('iteration3_composer_identity');
  }
  if(name==='assets/contextual-team-engine.js')composer=hash(raw);
  vm.runInContext(raw.toString('utf8'),c,{filename:name,timeout:5000});
}
const api=c.ContextualTeamEngine,directory=c.RESEARCHER_DIRECTORY,record={};
if(api.VERSION!=='contextual-composition-v4')throw Error('iteration3_composer_version');
const eligibleIds=directory.researchers.filter(api.eligible).map(p=>p.id).sort();
const engine=api.create(graph,directory,{...graph,scope_id:graph.scope.id,parent_id:graph.scope.parent_id,
  directory_content:api.canonical(directory.researchers)},
  // Output audit only; source action currentness is separately enforced before dispatch.
  {record,parentRecord:record,currentness:()=>true});
const state=engine.proposal(),options=engine.proposalOptions(state),view=engine.proposalView(state);
console.log(JSON.stringify({bundle_id:overlay?.bundle_id??null,direct_source:direct,composer_sha256:composer,
  composer_version:api.VERSION,graph_id:graph.graph_id,eligible_ids:eligibleIds,
  candidate_groups:api.candidateGroups(graph,eligibleIds),groups:options.map(o=>o.state.selectedIds),option_count:options.length,
  primary_view:view.selected.map(s=>({person_id:s.profile.id,evidence:s.evidence})),
  group_explanation:view.opportunity.why_team,missing_skills:view.opportunity.missing_skills,statistics:engine.statistics()}));
