import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
// The corrective work order expands profile/adapter changes at this inspected
// snapshot. Keep the original interface-freeze manifest and reports as history.
const BASE='16ed8ff1ca6e7e57199d3d4fafabeebb07f7cdb2';
const old=p=>execFileSync('git',['show',BASE+':'+p],{encoding:'utf8',maxBuffer:10*1024*1024});
const read=p=>fs.readFileSync(p,'utf8');
const normal=s=>s.replace(/(\?v=)[a-f0-9]{64}/g,'$1HASH').replace(/(name="opportunity-team-generation" content=")[a-f0-9]{64}/g,'$1HASH');
test('all frozen presentation functions and fixed output strings are unchanged',()=>{
 const before=old('assets/opportunity-team-panel.js'),after=read('assets/opportunity-team-panel.js');
 for(const name of ['panelShell','memberCard','roleRow','stateLabel','renderProposal','renderScopeChoice','renderUnavailable','renderFailure','teamMatchHref']){
  const regex=new RegExp('  function '+name+'\\([^]*?\\n  }');assert.equal(after.match(regex)?.[0],before.match(regex)?.[0],name);
 }
});
test('HTML changes are content hashes and the authorized nonvisual profile normalization only',()=>{
 assert.equal(normal(read('match_explorer.html')),normal(old('match_explorer.html')));
 const adapters=s=>['directoryFacultyKey','memberProfile'].reduce((v,name)=>v.replace(new RegExp('  function '+name+'\\([^]*?\\n  }'),'PROFILE_ADAPTER'),s);
 assert.equal(adapters(normal(read('team_match.html'))),adapters(normal(old('team_match.html'))));
 assert.equal(normal(read('faculty_interests.html')),normal(old('faculty_interests.html')));
});
test('remaining frozen files, Stage 1 report, old services and policies retain exact bytes',()=>{
 const manifest=JSON.parse(read('docs/team-recommender/manifests/interface-freeze.json'));
 const allowed=new Set(['assets/opportunity-team.js','assets/opportunity-team-panel.js','match_explorer.html','team_match.html','faculty_interests.html']);
 for(const file of Object.keys(manifest.files))if(!allowed.has(file))assert.equal(read(file),old(file),file);
 for(const p of ['AGENTS.md','config/sonnet_production_qualification.json','.github/workflows/offline-ai-evaluation.yml','docs/team-recommender/reports/stage-1-report.md'])assert.equal(read(p),old(p),p);
});
