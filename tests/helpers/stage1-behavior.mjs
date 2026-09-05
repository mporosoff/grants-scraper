import {createHash} from 'node:crypto';
import vm from 'node:vm';
export async function captureBehavior(app) {
function fn(name) {
  const start=app.indexOf(`  function ${name}(`);
  if(start<0) throw Error(name);
  const tail=app.slice(start);
  const end=tail.slice(3).search(/\n  (?:async )?function /);
  return end<0 ? tail : tail.slice(0,end+3);
}
const record={opportunity_id:'stage1-fixture',opportunity_number:'STAGE-1',title:'Fixture, official notice',agency:'NSF',source:'Grants.gov',status:'posted',close_date:'2026-12-31',primary_document_url:'https://www.nsf.gov/notice.pdf',funding_opportunity_url:'https://www.nsf.gov/funding/notice',detail_page:'https://www.grants.gov/search-results-detail/stage1-fixture',contact_email:'public@example.org'};
const controls=new Map();
const $=id=>{if(!controls.has(id)) controls.set(id,{value:'',checked:false});return controls.get(id)};
$('status-posted').checked=true;$('status-forecasted').checked=true;
let blob, urlState, alert;
class Url extends URL {static createObjectURL(value){blob=value;return 'blob:fixture'} static revokeObjectURL(){}}
const state={savedItems:[],ready:true,searched:true,query:'carbon capture',sort:'relevance',filters:{agency:new Set(['NSF'])},profile:{active:false},refinement:{assessments:new Map()},ai:{assessments:new Map()},deployment:{review:{}},strongMatches:[{index:0}]};
const sandbox={URL:Url,Blob,Set,Map,Date,encodeURIComponent,state,$,FACETS:{agency:{}},catalog:{opportunities:[record]},location:{href:'https://example.org/match_explorer.html?q=old',protocol:'https:'},history:{replaceState(a,b,url){urlState=String(url)}},currentDisplayMatches:()=>[{index:0,workflowTier:'strong'}],hybridFilterState:()=>({agencies:['NSF']}),ALERTS_API:{open(value){alert=value}},recordById:()=>record,RESULT_WORKFLOW_API:{potentialEvidence:()=>null,workflowTierLabel:()=> 'Strong'},hasPlaceholderAward:()=>false,evidenceFacts:()=>[],recordDeploymentUsage:()=>{},document:{createElement:()=>({click(){},remove(){}}),body:{appendChild(){}}}};
vm.createContext(sandbox);
for(const name of ['escapeHtml','escapeAttribute','safeUrl','safeEmail','recordId','primaryContact','programContactAction','officialActions','deadlineEvidenceLabel','fundingEvidenceLabel','csvCell','exportCsv','syncStateToUrl','savedSearchAlertDefinition','openSavedSearchAlert','openOpportunityAlert']) vm.runInContext(fn(name),sandbox);
sandbox.exportCsv(); sandbox.syncStateToUrl();sandbox.openSavedSearchAlert();
const searchAlert=JSON.parse(JSON.stringify(alert));sandbox.openOpportunityAlert(record.opportunity_id,null);
const immutable=['exportCsv','syncStateToUrl','hydrateStateFromUrl','savedSearchAlertDefinition','openSavedSearchAlert','openOpportunityAlert','openProgramAlert','officialActions','opportunityTeamScopeId','opportunityHasAvailableTeam'];
const functionHashes=Object.fromEntries(immutable.map(name=>[name,createHash('sha256').update(fn(name)).digest('hex')]));
const result={record,source:sandbox.officialActions(record),contact:sandbox.programContactAction(record),csv:await blob.text(),url:urlState,searchAlert,opportunityAlert:alert,functionHashes};
return result;
}
