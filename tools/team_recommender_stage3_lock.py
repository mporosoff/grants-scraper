"""Persist the validation boundary before any held-out recommendation."""
from collections import defaultdict
import json
from pathlib import Path
from tools.team_recommender_real_prep import ROOT,DOC,sha,write

def read(path):return json.loads(path.read_bytes())
def ref(path):return {'path':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':sha(path.read_bytes())}

def main():
    source=read(ROOT/'outputs/team-recommender-stage3/source-inputs-v1.json')
    groups=defaultdict(list)
    for row in source['dispositions']:
        if row['scope_id'] in source['cohorts']['holdout_effective']:groups[row['family']].append(row)
    for rows in groups.values():rows.sort(key=lambda r:sha('stage3-e2-closeout-v1|'+r['group_id']+'|'+r['scope_id']))
    ordered=[]
    for i in range(max(map(len,groups.values()))):
        for family in sorted(groups):
            if i<len(groups[family]):ordered.append(groups[family][i]['scope_id'])
    nomination=read(DOC/'stage2-validation-candidate.json')
    files=['stage2-validation-candidate.json','manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json',
        'manifests/development.json','manifests/holdout.json','manifests/rollout.json',
        'manifests/human-final-source-overlay-c2.json','manifests/interface-freeze.json',
        'manifests/stage3-source-decisions-v1.json','receipts/stage3-source-preparation-v1.json',
        'receipts/stage3-unique-input-plan-v2.json','receipts/stage3-E2-identity-check.json',
        'reports/stage-2-decision-closeout.md','STAGE_3_VALIDATION_AUTHORITY.md']
    missing=[p for p in files if not (DOC/p).exists()]
    if missing:raise ValueError('actual_manifest_path_required:'+str(missing))
    inputs=read(DOC/'receipts/stage3-unique-input-plan-v2.json')
    lock={'version':'S3-E2-validation-lock-v1','stage':3,'authorized':True,'starting_closeout':'f4f38b32294c8e922c25a7c67d518be27f5f8e33',
        'candidate':nomination,'sole_comparator':'A-E2','fallback':None,'comparison_clock':'2026-09-10T12:00:00Z',
        'live_like_clock':'fresh authoritative clock for every separate action; fixed within each action',
        'references':[ref(DOC/p) for p in files],
        'runtime':{p:sha((ROOT/p).read_bytes()) for p in ['assets/team-recommender.js','assets/team-ingredients.js','assets/opportunity-team.js','assets/opportunity-team-panel.js','assets/search-retrieval.js','assets/submission-schedule.js']},
        'source_recipe':ref(ROOT/'outputs/team-recommender-stage3/source-inputs-v1.json'),
        'complete_projection':ref(ROOT/'tools/team_recommender_evidence_projection.py'),
        'rubric':ref(ROOT/'config/team_recommender_executor/judge-d1.md'),
        'trusted_helper_candidate':'7c42154733904b04cb261b5b3bf58884b3c9f72b','trusted_helper_status':'pending independent review and required CI; no dispatch allowed yet',
        'trusted_inputs_sha256':inputs['trusted_inputs_sha256'],'embedding_packet_sha256':inputs['embedding_packet_sha256'],
        'source_order':ordered,'source_order_rule':'family round-robin; family ASCII order; within family SHA256(stage3-e2-closeout-v1|group_id|scope_id)',
        'holdout_reservations':90,'controls':source['controls'],'prepared_scopes_at_lock':39,'holdout_replacements':0,
        'rollout':{'original50':source['cohorts']['rollout50'],'original150':source['cohorts']['rollout150'],
            'substitutions':[],'prepared50':30,'prepared150':81,'shortfall':'Original routing reservations retained with explicit unsupported statuses; no replacement selected or smaller count labeled a complete 150.'},
        'source_policy':'Use only locked recipe aspects and original source spans/conditions, same D1 weight policy. No source interpretation after recommendations; no profile changes. Scientific preparation, current action, applicant conditions and independent directory feasibility are separate.',
        'numerical_plan':'All 90 scientific and 30 separately identified controls; E2 and A-E2 over the same 155 people. A takes B size, or 2 if B abstains, only with enough whole-call floor-admitted people. No fitting/thresholds/model choice/MMR/new exception.',
        'judge_plan':{'protocol':'S3-E2-complete-v1','model':'claude-sonnet-5','semantic_rubric':'unchanged D1F',
            'primary_request_cap':134,'optional_caps':{'rank2_alternatives':12,'explanations':6,'order_swaps':6,'semantic_controls':6},
            'rounds':['E2 primary group and every primary member; when no group, fixed rank-1 person if available',
                      'matched-size A-E2 group/members and A/B comparison','remaining E2 and A-E2 top-five people'],
            'ordering':'In each round visit every source once before another item for that source; deterministic source order above; deduplicate exact questions with occurrence mappings.',
            'optional_selectors':'Rank-2 option on first 12 ordered sources, explanation on first six, comparison swap on first six, semantic controls on first six source-ordered control origins. Missing rank/group, indivisible oversized packet and unavailable origin stays unresolved; no favorable replacement.',
            'balanced_AB':'SHA256(stage3-e2-AB-v1|scope_id) low-bit chooses primary blinded A/B mapping; audit uses opposite mapping. Conflict remains unresolved.',
            'packing':'At most three independent same-source questions with complete documents; never truncate decisive text; input <=12000 including serialized envelope+1024, output <=512.',
            'allocation_seal':'Materialize exact items, dedup keys, occurrence mappings, oversized cases and request hashes after frozen numerical outputs, then commit before first judge response. Stop deterministic allocation before lower aggregate token/dollar/request cap; no response-informed reallocation.',
            'pre_embedding_inventory':'39 prepared source units; each may have primary group, every member, sole comparator, top-five, and fixed optional slots. Actual people/item hashes depend on 190 missing query vectors and are not falsely claimed known before preparation.',
            'exact_reuse':'Only complete identical questions; no historical incomplete D1 projection grades pooled as held-out evidence.'},
        'analysis':{'group_bootstrap_draws':5000,'seed':20260910,'confidence_interval':.95,
            'slices':['all reservations','all prepared','action-eligible prepared','common-source paired E2/A-E2'],
            'missing_label_bounds':'hold observed labels fixed; missing/insufficient/unresolved are reported separately and bounded pessimistically/optimistically, never silently dropped',
            'source_clusters':'preserved C2 source_group_map; controls are derived, not independent sources; repeated people/options remain occurrences',
            'targets':{'top_five':'mean reasonable (strong/plausible) proportion of available top-five >=.80; empty/short lists explicit',
                'unrelated_members':'<=.05 of audited automatic-member occurrences; primary and sampled alternatives separate with clustered uncertainty',
                'useful_primary':'>=.80; report graded primary groups separately from original independently feasible denominator',
                'feasible_yield':'>=.85 on independently evidenced feasible scopes; UNMEASURED if none established',
                'complementarity':'paired judge preference versus A-E2; numerical coverage alone is not scientific superiority; inconclusive is not equivalence'},
            'feasibility_at_lock':'unknown; no algorithm-output-defined feasible subset','no_retuning':True},
        'budget':{'authorization_id':'on-demand-team-offline-v2-20260909','starting_charged_microusd':3135333,'starting_requests':475,
            'starting_ledger_sha256':'a7065a2d4422a0006808343ac1dc54155bb7810096c4544d0e0d0b266555ee6c',
            'cloud_owner':'34538646232','total_dollars':10,'total_requests':690,'new_stage3_dollars':4,'new_stage3_requests':184,
            'embedding_requests':6,'embedding_input_bound':110464,'embedding_reserved_microusd':13258,
            'judge_max_requests':164,'judge_input_bound':1064960,'judge_output_bound':83968,
            'judge_conservative_usd_bound':3.50208,'combined_conservative_usd_bound':3.515338,
            'stage4_min_dollars':2.864667,'stage4_min_slots':25,'concurrency':1,'automatic_paid_retries':0,
            'prices':{'voyage-4-large':'.12 USD/M input','claude-sonnet-5':'2 USD/M input, 10 USD/M output; reserve 2.50 USD/M input including cache-write conservatism'},
            'price_verification_date':'2026-09-10','prices_sources':['https://docs.voyageai.com/docs/pricing','https://platform.claude.com/docs/en/about-claude/pricing'],
            'historical_other_task_spend':'11.971342 USD, reusable historical work only; no budget credit'},
        'required_validation':['focused Python source/projection/executor/accounting and numerical-reference contracts',
            'required Node/browser contracts and frozen retrieval/scoring checks','complete configured Playwright suite including accessibility',
            'real E2 package integration at original 50/150 routing with unsupported statuses','cold/warm build, options, add/remove/re-add, exclusions, full slots, saved/manual paths and all-member Team Match',
            'currentness between actions, child ownership, corrupt/mixed/stale/unavailable data, races and restoration',
            'browser-boundary zero provider traffic on prepared build/edit/retry/cache miss/error; no team asset load/compute during ordinary search',
            'real gzip/transfer/decode/hydration/memory/timings; offline rollback without production flip'],
        'resource_limits':{'cached_p95_ms':200,'post_input_ms':1000,'cold_seconds':5,'network_mbit_s':20,'latency_ms':150,'ingredients_MiB':8,'extra_heap_MiB':48},
        'human':{'reviewer':'Marc Porosoff','development_requested':20,'development_returned':0,'new_development_items':0,'final_cap':20,
            'final_policy':'exact preserved 12 individual/8 team scope/rank overlay; evidence first, hidden model verdicts, unable-to-assess permitted, no skip replacement'},
        'exposure':{'heldout_recommendations_generated':False,'heldout_judgments':0,'paid_stage3_requests':0},
        'stop_rule':'After finite validation: A ready to request Stage 4; B engineering validated/owner tradeoff for quality, coverage or audit; C integrity/security/access/budget/evidence failure. No deployment or Stage 4.'}
    print(write(DOC/'manifests/stage3-validation-lock-v1.json',lock))

if __name__=='__main__':main()
