import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

test('restricted serving proof rejects changed bindings, mixed traffic and changed module bytes',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'contextual-proof-test-'));
  try{
    const preload=path.join(dir,'transport.mjs'),receipt=path.join(dir,'before.json'),build=path.join(dir,'build');
    fs.mkdirSync(build);fs.writeFileSync(path.join(build,'index.js'),'export default {};');
    fs.writeFileSync(preload,`import fs from 'node:fs';const config=JSON.parse(fs.readFileSync('workers/researcher-intake/wrangler.jsonc'));
      const secrets=['ADMIN_EMAILS','ACCESS_TEAM_DOMAIN','ACCESS_AUD','RECEIPT_TOKEN_SECRET','REGISTRY_WORKFLOW_TOKEN','GITHUB_DISPATCH_TOKEN','RESEND_API_KEY','ADMIN_NOTIFICATION_EMAIL','NOTIFICATION_FROM'];
      const first='11111111-1111-4111-8111-111111111111',second='22222222-2222-4222-8222-222222222222';globalThis.fetch=async url=>{
      if(!url.startsWith('https://api.cloudflare.com/client/v4/accounts/fixture/workers/'))throw Error('Unexpected transport');
      const mode=process.env.PROOF_FIXTURE;let result;
      if(url.endsWith('/deployments'))result={deployments:[{id:'deployment',created_on:'2026-09-12T00:00:00Z',versions:
        mode==='mixed'?[{version_id:first,percentage:50},{version_id:second,percentage:50}]:[{version_id:first,percentage:100}]}]};
      else if(url.endsWith('?include=modules'))result={id:first,modules:[{name:'index.js',content_type:'application/javascript+module',
        content_base64:Buffer.from(mode==='bytes'?'changed':'export default {};').toString('base64')}]};
      else if(url.endsWith('/subdomain'))result={enabled:mode!=='route',previews_enabled:mode!=='preview'};
      else if(url.endsWith('/schedules'))result={schedules:(mode==='cron'?['* * * * *']:config.triggers.crons).map(cron=>({cron}))};
      else if(url.includes('/routes?'))result=mode==='zone'?[{pattern:'unexpected.example/*'}]:[];
      else if(url.includes('/domains/records?'))result=mode==='domain'?[{hostname:'unexpected.example'}]:[];
      else result={resources:{script_runtime:{compatibility_date:mode==='runtime'?'2020-01-01':config.compatibility_date,exports:{},usage_model:'standard'},
        bindings:[...Object.entries(config.vars).map(([name,text])=>({name,type:'plain_text',text:mode==='bindings'?'drift':text})),
          ...config.d1_databases.map(d=>({name:d.binding,type:'d1',id:mode==='database'?'wrong-id':d.database_id})),
          ...config.ratelimits.map(r=>({...r,type:'ratelimit'})),...secrets.map(name=>({name,type:'secret_text'}))]}};
      return new Response(JSON.stringify({success:true,result}));};`);
    const run=(action,mode='good')=>spawnSync(process.execPath,['--import',pathToFileURL(preload).href,'tools/contextual_worker_checkpoint.mjs',action,receipt,build],{
      encoding:'utf8',env:{...process.env,CLOUDFLARE_API_TOKEN:'fixture-not-a-secret',CLOUDFLARE_ACCOUNT_ID:'fixture',GITHUB_OUTPUT:'',GITHUB_SHA:'a'.repeat(40),PROOF_FIXTURE:mode}});
    let r=run('capture');assert.equal(r.status,0,r.stderr);r=run('verify');assert.equal(r.status,0,r.stderr);
    const proof=JSON.parse(fs.readFileSync(receipt.replace('.json','-verified.json')));assert.equal(proof.public_recommender_activation,false);
    for(const mode of ['bindings','database','runtime','mixed','bytes','route','preview','cron','zone','domain'])assert.notEqual(run('verify',mode).status,0,mode);
    assert.notEqual(run('capture','bindings').status,0,'already-drifted bindings must fail before deployment');
    const mismatch=run('capture','bindings');
    assert.match(mismatch.stderr,/bindings\.PUBLIC_APP_ORIGIN\.text/);
    assert.match(mismatch.stderr,/expected_sha256/);
    assert.doesNotMatch(mismatch.stderr,/"drift"|https:\/\/mporosoff\.github\.io|fixture-not-a-secret/);
    assert.match(run('capture','runtime').stderr,/runtime\.compatibility_date/);
    assert.doesNotMatch(fs.readFileSync(receipt,'utf8'),/fixture-not-a-secret/);
  }finally{
    assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));
    assert(path.basename(dir).startsWith('contextual-proof-test-'));
    fs.rmSync(dir,{recursive:true,force:true});
  }
});
