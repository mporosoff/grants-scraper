// Use the exact preview composer. Only OS path necessities and JSON data enter.
// No model credentials, network, saved teams or judge answers enter this process.
import fs from 'node:fs';
import vm from 'node:vm';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
const bundle=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const data=JSON.parse(fs.readFileSync(0,'utf8'));
const c=vm.createContext({URL,Date});
for(const name of ['data/researcher_directory.js','assets/contextual-team-engine.js']){
  const file=bundle.files[name],raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));
  if(createHash('sha256').update(raw).digest('hex')!==file.sha256)throw Error('preview_composer_identity');
  vm.runInContext(raw.toString('utf8'),c,{filename:name,timeout:5000});
}
const graph=data.graph,directory=c.RESEARCHER_DIRECTORY,record={};
const engine=c.ContextualTeamEngine.create(graph,directory,{...graph,scope_id:graph.scope.id,parent_id:graph.scope.parent_id,
  directory_content:c.ContextualTeamEngine.canonical(directory.researchers)},
  // This is an output audit of an already completed graph, not authorization of
  // a new source assessment. Live actions independently recheck currentness.
  {record,parentRecord:record,currentness:()=>true});
const state=engine.proposal(),options=engine.proposalOptions(state);
console.log(JSON.stringify({bundle_id:bundle.bundle_id,composer_sha256:bundle.files['assets/contextual-team-engine.js'].sha256,
  groups:options.slice(0,2).map(o=>o.state.selectedIds),option_count:options.length,
  primary_view:engine.proposalView(state).selected.map(s=>({person_id:s.profile.id,evidence:s.evidence}))}));
