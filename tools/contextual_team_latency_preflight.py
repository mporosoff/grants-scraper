"""Complete fixed packets and conservative remaining scientific-input bounds."""
import json
import math
from tools.contextual_team_latency import eclipse_data, configuration, result_path
from tools.contextual_team_latency_policy import RELEASE, plan, operation, history, remaining_fits
from tools import contextual_team_latency_contract as wire
from tools.contextual_team_executor import scope_inputs
from tools.contextual_team_check import judge_prompt
from tools.contextual_team_contract import obj
from tools.offline_spend import identity, encoded, atomic_json, Deferred


def preflight(runner):
    history(runner.ledger.read());remaining_fits(runner.ledger.read())
    data,_=eclipse_data(runner.state);scope=configuration()['scopes'][0]
    science=scope_inputs(scope);rows=[]
    for name,stage,d,repaired in [('S','adjudication',data,False),('interpret','decomposition',science,True)]:
        c,b=wire.body(stage,d,'S',operation(name)['output_token_ceiling'],repaired)
        n=runner.counter.count({'id':'latency:'+name,'body':b})
        bound=math.ceil(n*1.2)+1024
        if bound>operation(name)['input_token_ceiling']:raise Deferred('latency_preflight_'+name+'_input_capacity')
        rows.append({'operation':name,'input_sha256':identity(d),'body_sha256':identity(b),
                     'wire_bytes':len(encoded(b)),'native_input_tokens':n,'reserved_input_tokens':bound})
    _,l=wire.body('adjudication',data,'L',24000)
    rows.append({'operation':'L','input_sha256':identity(data),'body_sha256':identity(l),
                 'wire_bytes':len(encoded(l)),'reserved_input_tokens':len(encoded(l))+1024})
    from tools.contextual_team_latency_check import comparison_sizing_packet
    # Count every permitted question/schema, including all twelve people. Bound
    # every unknown relationship identity separately by bytes, never by a
    # guessed overlap discount or placeholder compression ratio.
    comparison,bounds,extra=comparison_sizing_packet(runner.state)
    n=runner.counter.count({'id':'latency:comparison-complete-sizing','body':comparison})
    bound=math.ceil(n*1.2)+1024+extra
    if bound>operation('comparison-check')['input_token_ceiling']:
        raise Deferred('latency_complete_comparison_input_capacity_'+str(bound))
    rows.append({'operation':'comparison-check','sizing_only':True,'questions':bounds['relationships']+bounds['people'],
                 'maximum_questions':sum(bounds[k] for k in ('relationships','people')),
                 'variable_relationship_bytes':extra,'body_sha256':identity(comparison),'wire_bytes':len(encoded(comparison)),
                 'native_input_tokens':n,'reserved_input_upper_bound':bound})
    # Count one source/prompt envelope. Known complete profile token counts are
    # reused individually; new model-authored text remains bounded in bytes,
    # never estimated using repetitive placeholder compression/tokenization.
    from tools.contextual_team_references import contract as legacy
    from tools.contextual_team_requirements import POLICY
    prompt=legacy('adjudication')['prompt']+legacy('verification')['prompt']+POLICY+judge_prompt(owned_references=True)
    base={'model':'claude-sonnet-5','system':prompt,'messages':[{'role':'user','content':json.dumps(science,ensure_ascii=False)}]}
    native=runner.counter.count({'id':'latency:complete-source-and-policies','body':base})
    checkpoint=json.loads((runner.state/'checkpoint.json').read_bytes())
    profile_counts={r['id'].removeprefix('profile:'):r['input_tokens']
        for r in checkpoint['phase2_token_preflight']['rows'] if r['id'].startswith('profile:') and r['status']=='complete'}
    people=configuration()['people']
    if set(profile_counts)!=set(p['person_id'] for p in people):raise ValueError('latency_complete_profile_sizing_missing')
    top12=sum(sorted(profile_counts.values(),reverse=True)[:12]);top4=sum(sorted(profile_counts.values(),reverse=True)[:4])
    ref_bytes=sorted([sum(len(encoded(c['claim_id']+'@'+str(c['revision'])))+1 for c in p['claims']) for p in people],reverse=True)
    # Existing unchanged generated-input caps: interpretation12,000 wire bytes,
    # verifier identities4,096. Flat references avoid six repeated claim enums.
    future={'assess':math.ceil((native+top12)*1.2)+1024+12000+sum(ref_bytes[:12])+5000,
            'verify':math.ceil((native+top12)*1.2)+1024+12000+4096+4096+5000,
            'final-check':math.ceil((native+top4)*1.2)+1024+12000+9000}
    # These deliberately conservative bounds include all original source and
    # worst full-directory selected documents, not just the previously used team.
    for name,bound in future.items():
        rows.append({'operation':name,'source_and_prompt_native_tokens':native,
                     'reserved_input_upper_bound':bound,'unknown_text_treated_as_bytes':True})
        if bound>operation(name)['input_token_ceiling']:
            raise Deferred('latency_complete_future_'+name+'_capacity_'+str(bound))
    result={'release_id':RELEASE,'fixed_packets':rows,'profile_documents':len(people),
            'profile_count_cache_reuse':len(profile_counts),'all_eight_reserved_microusd':plan()['maximum_inventory_microusd'],
            'maximum_new_attempts':8,'paid_dispatches':0,'no_profile_or_source_truncation':True,
            'comparison_question_bound':bounds['relationships']+bounds['people'],
            'comparison_input_ceiling':operation('comparison-check')['input_token_ceiling'],
            'comparison_output_ceiling':8000,'final_question_bound':10,'final_output_ceiling':4000}
    atomic_json(result_path(runner.state,'preflight'),result)
    return result
