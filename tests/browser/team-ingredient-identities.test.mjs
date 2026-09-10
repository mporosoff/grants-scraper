import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import {fixture, NOW} from '../fixtures/team-ingredients.mjs';

const nsf = 'nsf-funding:https://www.nsf.gov/funding/opportunities/dmsnigms-joint-dmsnigms-initiative-support-research-interface/nsf22-600';
function rename(f, parent, id = parent) {
  f.record.opportunity_id = parent;
  Object.assign(f.childRecord, {opportunity_id:id, subtopic_id:id, parent_id:parent});
  Object.assign(f.scope, {id, parent_id:parent});
  Object.assign(f.source, {id, parent_id:parent, record_key:f.api.recordKey(id===parent?f.record:f.childRecord)});
  Object.assign(f.source.receipt, {scope_id:id, parent_id:parent, source_record_key:f.source.record_key});
  Object.assign(f.index.scopes[0], {id, parent_id:parent});
  Object.assign(f.manifest.source_validations[0], {scope_id:id, parent_id:parent});
}
test('every actual canonical URL-shaped NSF catalog identifier hydrates unchanged', async()=>{
  const raw=fs.readFileSync('data/opportunities.js','utf8');
  const ids=JSON.parse(raw.slice(raw.indexOf('{'),raw.lastIndexOf('}')+1)).opportunities.map(r=>r.opportunity_id).filter(id=>id.includes('://'));
  assert.ok(ids.includes(nsf)); assert.equal(ids.length,11);
  for(const id of [...ids,'ordinary-123:scope_2']){
    const f=await fixture({count:2}); rename(f,id);
    const e=f.api.create(await f.hydrate());
    const result=e.resolveScope({record:f.record,parentId:id,scopeId:id,now:NOW});
    assert.equal(result.ok,true,id);
  }
});
test('canonical NSF identity preserves exact parent-child ownership', async()=>{
  const f=await fixture({count:2,child:true}); rename(f,nsf,'child-owned-by-nsf');
  const e=f.api.create(await f.hydrate());
  const ctx={record:f.record,parentId:nsf,scopeId:f.scope.id,childCatalog:{opportunities:[f.childRecord]},now:NOW};
  assert.equal(e.resolveScope(ctx).ok,true);
  assert.equal(e.resolveScope({...ctx,childCatalog:{opportunities:[{...f.childRecord,parent_id:'different-parent'}]}}).ok,false);
  f.source.receipt.parent_id='different-parent'; await assert.rejects(f.hydrate,/ownership/);
});
test('malformed URLs and noncanonical aliases do not create alternative identities',async()=>{
  for(const id of [nsf+'/',nsf+'?x=1',nsf+'#fragment',nsf.replace('https:','http:'),nsf.replace('www.nsf.gov','www.nsf.gov.evil.org'),
    nsf.replace('www.nsf.gov','user@www.nsf.gov'),nsf.replace('www.nsf.gov','www.nsf.gov:443'),nsf.replace('/funding/','/funding/../funding/'),
    nsf.replace('nsf22-600','%6Esf22-600'),nsf.replace('https://','https:\\\\'),nsf.replace('www.nsf.gov','WWW.NSF.GOV'),
    'https://www.nsf.gov/example','nsf-funding:https://www.nsf.gov/arbitrary/file',nsf+'\n']){
    const f=await fixture({count:2});rename(f,id);await assert.rejects(f.hydrate,/source identity|scope identity/,id);
  }
  const f=await fixture({count:2});rename(f,nsf);
  f.bundle.sources.push(structuredClone(f.source));f.bundle.scopes.push(structuredClone(f.scope));
  f.manifest.source_validations.push(structuredClone(f.manifest.source_validations[0]));
  await assert.rejects(f.hydrate,/source identity/);
});
