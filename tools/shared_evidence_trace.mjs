// Private executable diagnostic. It never fetches sources or calls a provider.
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const root='outputs/team-recommender-post-audit/';
const c=vm.createContext({Date});
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js','assets/team-matcher.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js']) {
 let text=fs.readFileSync(p,'utf8');
 if(p==='assets/team-matcher.js') text=text.replace('      buildThemes,','      trace: (profile, prepared) => ({profile, source: prepared.record, phrases: profilePhrases(profile).map(phrase => ({phrase, groups: groupDefinitions(phrase, profileContext(profile)), evidence: phraseEvidence(phrase, prepared, profileContext(profile))})), fit: scoreProfile(profile, prepared)}),\n      buildThemes,');
 vm.runInContext(text,c);
}
const index=read('docs/team-recommender/post-audit/semantic-index.json'), packet=read(index.shared.path);
const child=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG);
const matchers=[c.GRANT_CATALOG,child].map(cat=>c.FUNDING_TEAM_MATCHER.create(cat,packet.config,c.FUNDING_SEARCH_QUERY,{now:new Date('2026-09-11T12:00:00Z')}));
const items=read(root+'judge-proposed-items-v2.json'),judgments=read(root+'judgments-v1.json'),saved=read(root+'semantic-outputs-v2.json');
const rows=[];
for(const j of judgments.filter(x=>x.kind==='call_person')) {
 const item=items[j.key],pid=item.item.candidates[0],person=c.RESEARCHER_DIRECTORY.researchers.find(p=>p.id===pid);
 const matcher=matchers.find(m=>m.records.some(r=>r.id===j.scope_id)),prepared=matcher.records.find(r=>r.id===j.scope_id);
 const trace=matcher.trace(c.FUNDING_TEAM_MATCHER.normalizeProfile(person),prepared),outcome=saved.rows.find(r=>r.id===j.scope_id);
 const sourceFields=Object.entries(prepared.record).filter(([k])=>['title','description','document_search_text','topic_areas','disciplines'].includes(k));
 for(const p of trace.phrases) if(p.evidence) p.locations=p.evidence.matchedTerms.map(term=>({term,fields:sourceFields.flatMap(([field,value])=>{
  const text=String(value),locations=[];let offset=-1;while((offset=text.toLowerCase().indexOf(term,offset+1))!==-1)locations.push(offset);
  return locations.length?[{field,locations}]:[];
 })}));
 rows.push({key:j.key,scope_id:j.scope_id,person_id:pid,name:person.name,verdict:j.verdict,trace,group_decision:outcome});
}
const result={baseline:'adedd242dc727d85bc2db42776abce5132c882b8',clock:saved.clock,unique_pairs:rows.length,provider_calls:0,rows};
fs.writeFileSync('outputs/team-recommender-evidence-repair/baseline-traces.json',JSON.stringify(result,null,2)+'\n');
const compact=rows.map(r=>({scope:r.scope_id,id:r.person_id,name:r.name,verdict:r.verdict,score:r.trace.fit?.score,strong:r.trace.fit?.strong,connections:r.trace.phrases.filter(x=>x.evidence).map(x=>({phrase:x.phrase,...x.evidence,fields:[...new Set(x.locations.flatMap(l=>l.fields.map(f=>f.field)))]}))}));
fs.writeFileSync('outputs/team-recommender-evidence-repair/baseline-compact.json',JSON.stringify(compact,null,2)+'\n');
console.log(JSON.stringify({pairs:rows.length,sha256:createHash('sha256').update(fs.readFileSync('outputs/team-recommender-evidence-repair/baseline-traces.json')).digest('hex')}));
