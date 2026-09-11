"""Consolidate existing receipts; never recalculate grades or fit a scorer."""
from collections import Counter
from tools.team_recommender_decision_closeout import ROOT,DOC,read,write,digest


def consolidate():
    r=DOC/'receipts';c2=read(r/'c2-final-analysis.json');d1=read(r/'d1-final-analysis.json');d2=read(r/'d2-development-results-34510982749.json');d3=read(r/'d3-development-results-34538646232.json');audit=read(r/'closeout-evidence-coverage.json')
    def ref(path):return {'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path)}
    def resources(name):
        x=read(r/name)
        return {'receipt':ref(r/name),**{k:v for k,v in x.items() if k in {'package_bytes','package_gzip_bytes','total_asset_bytes','total_gzip_bytes','hydration_ms','hydration','matrix_plus_group','measurements','scope_count','people','physical_browser','kind'}}}
    rows=[{'checkpoint':'engineering','candidate':ref(DOC/'stage2-candidate.json'),'real_prepared':0,'unattempted_real_reservations':90,'source_dispositions':'Not yet audited at engineering checkpoint','semantic_results':'Not run; zero human/model observations','resource_receipt':ref(r/'stage2-resource-measurements.json'),'resource_limit':'Synthetic/repetitive gzip only, not a real transfer estimate','new_usd':0,'cumulative_usd':0}]
    middle=next(c for c in c2['candidates'] if c['candidate']=='bounded-middle')
    cm=read(ROOT/'outputs/team-recommender-c2/judge-item-map-v3.json');ca=read(ROOT/'outputs/team-recommender-c2/analysis-private/c2-judge-results-34472949357.json')
    def selected(kind,primary=False):
        occ=[o for o in cm['occurrences'] if o.get('candidate')=='bounded-middle' and o['kind']==kind and (o.get('mode')=='B' if kind=='automatic-member' else o.get('arm')=='coverage') and (not primary or o.get('position',1)==1)]
        return {'occurrences':len(occ),'unique_questions':len({o['key'] for o in occ}), 'labels':dict(Counter(ca['labels'].get(o['key'],{}).get('label','missing') for o in occ))}
    rows.append({'checkpoint':'C2','receipt':ref(r/'c2-final-analysis.json'),'representation':'voyage-4-lite original evidence passages; coverage-v2.2 bounded-middle','judge_task':'C2 individual relevance lacks D1 retained labels/types/summary and changed rubric; not pooled with D1+','prepared':34,'unprepared':56,'scientific_out_of_scope':51,'genuine_context_gap':5,'action_eligible':26,'action_blocked':8,'groups':1,'no_group':33,'useful_primary':1,'primary_members':selected('automatic-member',True),'all_graded_primary_members_reasonable':1,'all_primary_members_observed_reasonable':0,'primary_group_missing_members':1,'all_option_members':selected('automatic-member'),'all_option_groups':{'useful':3,'observed':7,'missing':1,'occurrences':8},'top5':middle['arms'],'paired':middle['paired_macro_B_minus_A'],'resources':resources('c2-real-measurements-final.json'),'new_usd':1.082518,'cumulative_usd':1.082518,'exact_cache_reuse':c2['budget']['exact_cache_hit_events'],'valid_unique_judgments':c2['valid_unique_items']})
    for name,x in [('D1',d1),('D2',d2)]:
        one=name=='D1';summary=x['summaries'];pg=summary['primary-group']['B'] if one else summary['D2']['primary_groups'];pm=summary['members']['B']['primary'] if one else summary['D2']['primary_members'];allg=summary['alternative']['B'] if one else summary['D2']['all_option_groups'];allm=summary['members']['B']['all_options'] if one else summary['D2']['all_option_members']
        rows.append({'checkpoint':name,'receipt':ref(r/('d1-final-analysis.json' if one else 'd2-development-results-34510982749.json')),'candidate':ref(DOC/('stage2-diagnostic-candidate.json' if one else 'stage2-ranking-d2-candidate.json')),'representation':'voyage-4-lite original passages','judge_task':'D1F call-person + full retained summary/labels but selected passages only; exact items reused where unchanged','prepared':35,'unprepared':55,'scientific_out_of_scope':51,'genuine_context_gap':4,'action_eligible':26,'action_blocked':9,'groups':5 if one else 8,'no_group':30 if one else 27,'primary_groups':pg,'primary_members':pm,'all_primary_members_observed_reasonable':4 if one else 6,'all_option_groups':allg,'all_option_members':allm,'top5':x['arms'],'paired':x['paired'],'resources':resources('d1-real-measurements-v1.json' if one else 'd2-real-measurements-uncontended.json'),'new_usd':1.055784 if one else .140808,'cumulative_usd':2.138302 if one else 2.279110,'exact_cache_reuse':{'ledger_cache_events':5,'semantic_task_changed_from_C2':True} if one else {'unique_questions':269,'occurrences':712},'valid_new_judgments':328 if one else 29})
    for arm in ['E0','E0-C','E1','E2','E3']:
        s=d3['summary'][arm]
        rows.append({'checkpoint':'D3-'+arm,'receipt':ref(r/'d3-development-results-34538646232.json'),'candidate':ref(DOC/'stage2-embedding-d3-candidate.json'),'prepared':35,'unprepared':55,'scientific_out_of_scope':51,'genuine_context_gap':4,'action_eligible':26,'action_blocked':9,'representation':{'E0':'exact D2 lite','E0-C':'lite with D3 model-specific calibration','E1':'voyage-4-large phrases','E2':'voyage-4-large combined profile','E3':'voyage-context-4 chunks'}[arm],
          'judge_task':'D1F exact original selected-passage projection; D3 richer representation not always fully shown to judge',
          'primary_groups':s['primary_groups'],'primary_members':s['primary_members'],'all_members':audit['all_member_primary'][arm],'all_option_groups':s['all_option_groups'],'all_option_members':s['all_option_members'],'top5':d3['arms'][arm],'same_model_baseline_top5':d3['arms']['A-'+arm],
          'resources':resources('d3-resources-'+arm+'.json') if arm!='E0-C' else {'status':'not separately measured'},
          'cost':'Shared D3 batch: $0.856223 new/$3.135333 cumulative; not charged once per arm.',
          'cache':'250 identical prior questions/1516 occurrences reused across all D3 arms, not independent observations.'})
    write(r/'closeout-consolidated-results.json',{'version':'stage2-evidence-consolidation-v1','comparison_clock':'2026-09-10T12:00:00Z','directory_people':155,'researcher_updates':0,'human_observations':0,'rows':rows,'D3_paired':d3['paired'],
          'source_counts':'Out-of-scope and context-gap counts classify the unprepared denominator, not lack of capable people. All 30 derived controls remain separate from 90 scientific reservations.',
          'occurrence_warning':'All-option summaries include primary rank 1. Additional alternatives = ranks 2Ã¢â‚¬â€œ8. Unique questions are not independent source groups.',
          'D3_original_artifact_hashes_unchanged':True,'new_judgments':0,'old_tasks_not_pooled':True})
    print('Consolidated engineering, C2, D1, D2 and five stored D3 arms without rerunning comparisons.')


if __name__=='__main__':consolidate()
