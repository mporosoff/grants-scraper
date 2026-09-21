// Exact restricted composer; stdin is one durable verified graph. No providers.
import fs from 'node:fs';
import vm from 'node:vm';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
const base=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const overlay=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
if(overlay.base_bundle_id!==base.bundle_id)throw Error('iteration2_preview_base_identity');
const data=JSON.parse(fs.readFileSync(0,'utf8')),graph=data.graph,c=vm.createContext({URL,Date});
for(const name of ['data/researcher_directory.js','assets/contextual-team-engine.js']){
  const file=overlay.files[name]||base.files[name],raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));
  if(createHash('sha256').update(raw).digest('hex')!==file.sha256)throw Error('iteration2_composer_identity');
  vm.runInContext(raw.toString('utf8'),c,{filename:name,timeout:5000});
}
const directory=c.RESEARCHER_DIRECTORY,record={};
const engine=c.ContextualTeamEngine.create(graph,directory,{...graph,scope_id:graph.scope.id,parent_id:graph.scope.parent_id,
  directory_content:c.ContextualTeamEngine.canonical(directory.researchers)},
  // Output audit only. This never authorizes a new action against an old clock.
  {record,parentRecord:record,currentness:()=>true});
const state=engine.proposal(),options=engine.proposalOptions(state),view=engine.proposalView(state);
console.log(JSON.stringify({bundle_id:overlay.bundle_id,composer_sha256:overlay.files['assets/contextual-team-engine.js'].sha256,
  graph_id:graph.graph_id,groups:options.slice(0,2).map(o=>o.state.selectedIds),option_count:options.length,
  primary_view:view.selected.map(s=>({person_id:s.profile.id,evidence:s.evidence})),
  missing_skills:view.opportunity.missing_skills,statistics:engine.statistics()}));
