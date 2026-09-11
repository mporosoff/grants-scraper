import test from 'node:test';
import assert from 'node:assert/strict';
import {context} from '../helpers/shared-team-inputs.mjs';
const c=context(), q=c.FUNDING_SEARCH_QUERY, api=c.FUNDING_RETRIEVAL.sourceEvidence;
function fit(source, claims, summary='') {
 const r={opportunity_id:'scope',title:'Scientific opportunity',status:'posted',close_date:'2027-01-01',...source};
 const m=c.FUNDING_TEAM_MATCHER.create({opportunities:[r]}, {}, q, {now:new Date('2026-09-11')});
 const p=c.FUNDING_TEAM_MATCHER.normalizeProfile({id:'person',name:'Researcher',research_summary:summary,summary_evidence:summary?[{url:'https://example.edu/research'}]:[],claims:claims.map((x,i)=>({claim_id:'c'+i,status:'active',label:x[0],evidence:x[1]||x[0],source_urls:['https://example.edu/research']}))});
 return m.scoreProfile(p,m.records[0]);
}
test('derived facets and excluded scope statements never supply scientific membership',()=>{
 const claims=[['Artificial intelligence','Develops machine learning methods for materials.']];
  for(const source of [
    {description:'Marine biological collections.',topic_areas:['Artificial intelligence and machine learning']},
    {description:'Marine biological collections.',document_program_areas:['artificial intelligence']},
    {description:'Marine biological collections.',program_area_labels:['artificial intelligence']},
  {description:'We do not support artificial intelligence research.'},
  {description:'This program aligns with artificial intelligence administration priorities.'},
 ]) assert(!fit(source,claims)?.automaticEligible);
});
test('partial plasma/physics matches cannot sum into a scientific anchor',()=>{
 const f=fit({title:'Geospace science',description:'Plasma physics in the ionosphere and magnetosphere. Solar wind heating and geomagnetic storms.'},[
  ['Laser-produced plasma physics'],['Thermonuclear plasma theory for confinement fusion'],['Magnetic and inertial fusion'],
 ]);
 assert(!f?.automaticEligible);assert(!f?.strong);
});
test('a complete method survives a long audited statement and controlled aliases',()=>{
 const f=fit({title:'Artificial intelligence for solar forecasting',description:'Machine learning methods will analyze solar observations.'},[
  ['Materials forecasting','Develops materials experiments, applies artificial intelligence to model measurements, and reports material behavior using established procedures.'],
 ]);
 assert(f.automaticEligible);assert(f.strong);
 assert(f.supportedConnections.some(x=>x.concept_ids.includes('artificial-intelligence')));
 assert(f.supportedConnections.every(x=>x.source_excerpt&&x.profile_excerpt&&x.field&&x.source_unit));
});
test('summary evidence reaches shared matching without manufacturing a claim certificate',()=>{
 const f=fit({title:'Quantum sensing',description:'Quantum sensing methods for magnetic measurements.'},[],'Investigates quantum sensing for nanoscale magnetic measurements.');
 assert(f.automaticEligible);assert(f.supportedConnections.some(x=>x.summary));
 assert(f.supportedConnections.every(x=>!x.claims.length));
});
test('duplicate labels, evidence and repeated claims do not add scientific coverage or strength',()=>{
 const source={title:'Raman spectroscopy',description:'Raman spectroscopy of solids.'};
 const a=fit(source,[['Raman spectroscopy','Studies Raman spectroscopy of solids.']]);
 const b=fit(source,Array.from({length:12},()=>['Raman spectroscopy','Studies Raman spectroscopy of solids.']));
 assert.deepEqual(JSON.parse(JSON.stringify(a.supportedConnections)),JSON.parse(JSON.stringify(b.supportedConnections)));
 assert.equal(a.strong,b.strong);
});
test('separated clauses cannot form a complete relationship; source field locations survive',()=>{
 const groups=q.expandGroups('laser plasma',()=>true,{searchV2:true});
 const separate=api.createScientificContext({title:'Laser instrumentation',description:'Plasma phenomena are studied elsewhere.'},q);
 assert.equal(separate.connections(groups).length,0);
 const joined=api.createScientificContext({title:'Laser plasma',description:'Investigates laser plasma interactions.'},q).connections(groups);
 assert(joined.length);assert.equal(joined[0].field,'parent_title');assert.equal(joined[0].source_offset,0);
});
test('scientific clauses preserve controlled compounds and reject facet-only aliases',()=>{
 const groups=q.expandGroups('high performance computing',()=>true,{searchV2:true});
 assert(api.createScientificContext({title:'High-performance computing',description:'Develops computing methods.'},q).connections(groups).length);
 assert.equal(api.createScientificContext({title:'Workforce awards',topic_areas:['High-performance computing']},q).connections(groups).length,0);
});
test('canonical hashing uses exactly the old full JSON identity, including non-BMP and escaped text',async()=>{
 const values=[null,true,4.2,{b:'😀 a\n"\\é\ud800',a:[1,null,false,{},['x']]},Array.from({length:10000},(_,i)=>({b:i,a:[i,-i,1e-7]}))];
 for(const value of values){
  const expected=new TextEncoder().encode(c.SharedTeamEngine.canonical(value));
  assert.deepEqual(Buffer.from(c.SharedTeamEngine.canonicalBytes(value)),Buffer.from(expected));
 }
});
