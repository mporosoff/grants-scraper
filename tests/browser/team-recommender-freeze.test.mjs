import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const BASE='b6f71ae0396bd2670043291bc676ee8af0d222b2';
const old=p=>execFileSync('git',['show',BASE+':'+p],{encoding:'utf8',maxBuffer:10*1024*1024});
const read=p=>fs.readFileSync(p,'utf8');
const normal=s=>s.replace(/(assets\/(?:opportunity-team|opportunity-team-panel)\.js\?v=)[a-f0-9]{64}/g,'$1HASH');
test('all frozen presentation functions and fixed output strings are unchanged',()=>{
 const before=old('assets/opportunity-team-panel.js'),after=read('assets/opportunity-team-panel.js');
 for(const name of ['panelShell','memberCard','roleRow','stateLabel','renderProposal','renderScopeChoice','renderUnavailable','renderFailure','teamMatchHref']){
  const regex=new RegExp('  function '+name+'\\([^]*?\\n  }');assert.equal(after.match(regex)?.[0],before.match(regex)?.[0],name);
 }
});
test('HTML changes are content hash references and the declared directory-loading seam only',()=>{
 assert.equal(normal(read('match_explorer.html')),normal(old('match_explorer.html')));
 const expected=old('team_match.html').replace('OPPORTUNITY_TEAM_API.loadData(OPPORTUNITY_TEAM_API.pageGenerationId())','OPPORTUNITY_TEAM_API.loadDirectory()');
 assert.equal(normal(read('team_match.html')),normal(expected));
});
test('remaining frozen files, Stage 1 report, old services and policies retain exact bytes',()=>{
 const manifest=JSON.parse(read('docs/team-recommender/manifests/interface-freeze.json'));
 const allowed=new Set(['assets/opportunity-team.js','assets/opportunity-team-panel.js','match_explorer.html','team_match.html']);
 for(const [file,hash]of Object.entries(manifest.files))if(!allowed.has(file))assert.equal(createHash('sha256').update(fs.readFileSync(file)).digest('hex'),hash,file);
 for(const p of ['AGENTS.md','config/sonnet_production_qualification.json','.github/workflows/offline-ai-evaluation.yml','docs/team-recommender/reports/stage-1-report.md'])assert.equal(read(p),old(p),p);
});
