// Build an unactivated validation index; no generated team inventory or provider.
import fs from 'node:fs';
import {hash,SOURCE_FIELDS,CONDITION_FIELDS} from './contextual_team_inputs.mjs';
const folder='docs/team-recommender/contextual-stage-b';
const lock=JSON.parse(fs.readFileSync(folder+'/input-lock-v1.json'));
const snapshot=JSON.parse(fs.readFileSync('outputs/contextual-stage-b/snapshot-'+lock.snapshot_id+'.json'));
const body={schema_version:4,release_id:snapshot.snapshot_id,registry_generation:snapshot.registry_generation,
  roster_id:snapshot.roster_id,directory_id:snapshot.directory_id,public_activation:false,
  endpoint:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual',
  source_fields:SOURCE_FIELDS,condition_fields:CONDITION_FIELDS,
  runtime:{contextual_engine:hash(fs.readFileSync('assets/contextual-team-engine.js','utf8')),
    contextual_client:hash(fs.readFileSync('assets/contextual-team-client.js','utf8'))},
  scopes:snapshot.scopes.map(s=>({id:s.id,parent_id:s.parent_id,scope_label:s.science.title,
    record_type:s.id===s.parent_id?'specific_parent':'publishable_child',engine:'contextual-v1',
    state:s.state,source_id:s.source_id}))};
const index={...body,generation_id:hash(body)};
const target='outputs/contextual-stage-b/validation-index-'+index.generation_id+'.json';
fs.writeFileSync(target,JSON.stringify(index,null,2)+'\n');
console.log(JSON.stringify({index:target,generation_id:index.generation_id,release_id:index.release_id,scopes:index.scopes.length,public_activation:false}));
