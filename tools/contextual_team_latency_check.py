"""Exact finite evidence checks and immutable route selection; no judge panel."""
import json
import os
from tools import team_recommender_executor as existing
from tools.contextual_team_latency import (LatencyRunner, configuration, eclipse_data,
    result_path, exact_prior)
from tools.contextual_team_latency_policy import RELEASE, plan, operation, history, remaining_fits
from tools.contextual_team_contract import obj, enum, string
from tools.contextual_team_check import judge_prompt
from tools.contextual_team_executor import scope_inputs
from tools.contextual_team_phase2_check import validator, select
from tools.offline_ai import request_body, validate_schema
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure


def saved(state,name):
    value=json.loads(result_path(state,name).read_bytes())
    if value.get('release_id')!=RELEASE:raise ConfigurationFailure('latency_saved_identity')
    return value


def assessment(state,route):
    from tools.contextual_team_latency_contract import body as build, validate_resolved
    from tools.team_recommender_budget import ExperimentLedger
    data,_=eclipse_data(state)
    c,body=build('adjudication',data,route,24000)
    logical=[RELEASE,route,identity(c),identity(data)]
    key=identity([existing.AUTHORIZATION_ID,'contextual-v1',logical])
    rows=[r for r in ExperimentLedger(state/'ledger.json').read()['requests'] if r['key']==key]
    if len(rows)!=1 or rows[0]['status']!='valid':raise ConfigurationFailure('latency_assessment_not_complete')
    row=rows[0];value=json.loads((state/'cache'/(key+'.json')).read_bytes())
    if (value['request_id']!=row['id'] or value['body_sha256']!=identity(body)
        or value['model']!=body['model']):raise ConfigurationFailure('latency_assessment_cache_identity')
    validate_resolved('adjudication',value['value'],data)
    return row,value['value']


def comparison_packet(state, *, sizing_arms=None):
    data,reference=eclipse_data(state);arms=sizing_arms or {r:assessment(state,r)[1] for r in ('S','L')}
    # Union is independent of provider ordering. No arm, score, time, old grade or
    # generation rationale enters the evidence shown to this one checker.
    union={}
    for value in [*arms.values(),reference]:
        for edge in value['edges']:
            key=identity([edge[k] for k in ('role_id','person_id','claim_id','claim_revision')])
            union[key]={k:edge[k] for k in ('role_id','person_id','claim_id','claim_revision')}
    questions=[{'item_id':'rel-'+key,'task_type':'aspect_person',**row} for key,row in union.items()]
    questions += [{'item_id':'person-'+identity(p['person_id']),'task_type':'call_person','person_id':p['person_id']}
                  for p in data['people']]
    questions.sort(key=lambda q:identity(['latency-blind-order-v1',q['item_id']]))
    people={p['person_id']:p for p in data['people']};fields={}
    for q in questions:
        refs=['scope.science',q['person_id'],*([q['claim_id']] if q['task_type']=='aspect_person'
              else [c['claim_id'] for c in people[q['person_id']]['claims']])]
        fields[q['item_id']]=obj(verdict=enum('strong','plausible','unrelated','insufficient-information'),
            supported_coverage=enum('direct','method_transfer','adjacent','insufficient_information'),
            central_supported={'type':'boolean'},evidence_ref=enum(*sorted(refs)),reason=string(300))
    schema=obj(verdicts=obj(**fields))
    evidence={'scope':data['scope'],'interpretation':data['interpretation'],'profile_documents':data['people'],'items':questions}
    prompt=judge_prompt(owned_references=True)+'''
Judge each explicit relationship or person against original complete evidence.
For a relationship assess its cited claim in the person's full document and the
target role. Return the strongest supported coverage category, and whether the
connection actually addresses central purpose. Do not infer facilities, access,
willingness or identical prior work. Credible evidenced transfer is acceptable.
For a person assess worth a conversation on this call, without inventing support.
Follow this supplied keyed schema. Reasons at most 300 characters, one evidence
reference belonging to this question. There are no requested teams or winners.
'''
    return checker_body('comparison-check',prompt,evidence,schema),questions,schema,arms,reference


def checker_body(name,prompt,evidence,schema):
    b=request_body({'provider':'anthropic','model':'claude-sonnet-5'},
        {'schema_version':'contextual_latency_check_v1','max_output_tokens':operation(name)['output_token_ceiling']},
        prompt,evidence,schema)
    b['thinking']={'type':'disabled'}
    return b


def run_check(runner,name,body,questions,schema):
    # Same exact reference-enumerated local/native schema used successfully in
    # Phase 1/2. No missing verdict can be silently accepted.
    result=runner.request('cb-lr-'+name,[RELEASE,name,identity(body)],body,validator(questions,schema,65536))
    value={'release_id':RELEASE,'body_sha256':identity(body),'questions':questions,'value':result,
           'request_id':runner.used[-1]['request_id']}
    atomic_json(result_path(runner.state,name),value)
    return value


def validate_selection(state,value):
    check=saved(state,'comparison-check')
    if value.get('comparison_sha256')!=identity(check):raise ConfigurationFailure('latency_selection_check_identity')
    body,questions,schema,_,_=comparison_packet(state)
    key=identity([existing.AUTHORIZATION_ID,'contextual-v1',[RELEASE,'comparison-check',identity(body)]])
    ledger=json.loads((state/'ledger.json').read_bytes())
    claims=[r for r in ledger['requests'] if r['key']==key]
    cached=json.loads((state/'cache'/(key+'.json')).read_bytes())
    if (len(claims)!=1 or claims[0]['status']!='valid' or check['body_sha256']!=identity(body)
        or cached['body_sha256']!=identity(body) or cached['request_id']!=claims[0]['id']
        or check['request_id']!=claims[0]['id'] or cached['value']!=check['value']):
        raise ConfigurationFailure('latency_complete_exact_check_required')
    validator(questions,schema,65536)(cached['value'],True)
    route=value['route'];row,arm=assessment(state,route)
    receipt=json.loads((state/'receipts'/(row['id']+'.json')).read_bytes())
    if receipt['elapsed_seconds']>231.551469/2:raise ConfigurationFailure('latency_no_material_assessment_gain')
    labels={q['item_id']:q for q in check['value']['verdicts']}
    strength={'direct':2,'method_transfer':1,'adjacent':0,'insufficient_information':-1}
    useful=[e for e in arm['edges'] if e['coverage'] in ('direct','method_transfer')]
    if len({e['person_id'] for e in useful})<2:raise ConfigurationFailure('latency_no_credible_supported_pool')
    for edge in useful:
        key='rel-'+identity([edge[k] for k in ('role_id','person_id','claim_id','claim_revision')])
        label=labels[key];person=labels['person-'+identity(edge['person_id'])]
        if (label['verdict'] not in ('strong','plausible') or person['verdict'] not in ('strong','plausible')
            or strength[label['supported_coverage']]<strength[edge['coverage']]
            or edge['central'] and not label['central_supported']):
            raise ConfigurationFailure('latency_unsupported_or_unresolved_automatic_relationship')
    return value


def final_packet(state):
    config=configuration();scope=config['scopes'][0];graph=saved(state,'DOE')['value']
    selection=select(graph);groups=selection['groups'][:1];byid={p['person_id']:p for p in config['people']}
    ids=groups[0] if groups else [p['person_id'] for p in graph.get('people',[])]
    people=[byid[pid] for pid in ids]
    questions=[{'item_id':'requirements','task_type':'explanation_audit','people':[],
        'assertion':{'objective':graph.get('objective'),'approach':graph.get('approach'),'roles':graph.get('roles'),
                     'limitations':graph.get('limitations'), 'instruction':'Check source meaning, alternative directions, genuine conjunctions, applicable obligations and selected-approach needs; exact references do not certify interpretation.'}}]
    if groups:
        questions.append({'item_id':'primary-group','task_type':'group_usefulness','people':ids})
        for i,pid in enumerate(ids):
            questions.append({'item_id':'person-'+str(i+1),'task_type':'call_person','people':[pid]})
            shown=next(s['evidence'] for s in selection['primary_view'] if s['person_id']==pid)
            if len(shown['evidence_phrase'])<8 or not any(shown['evidence_phrase'] in c['evidence'] for c in byid[pid]['claims']):
                raise ValueError('latency_final_explanation_evidence_missing')
            questions.append({'item_id':'explanation-'+str(i+1),'task_type':'explanation_audit','people':[pid],
                              'assertion':shown['why_person']})
    else:
        questions.append({'item_id':'bounded-gap','task_type':'explanation_audit','people':ids,
                          'assertion':{k:graph.get(k) for k in ('state','objective','approach','roles','people','edges','limitations')}})
    fields={}
    for q in questions:
        refs={'scope.science',*q['people'],*(c['claim_id'] for p in people if p['person_id'] in q['people'] for c in p['claims'])}
        labels=('faithful','unsupported','insufficient-information') if q['task_type']=='explanation_audit' else ('strong','plausible','unrelated','insufficient-information')
        fields[q['item_id']]=obj(verdict=enum(*labels),evidence_ref=enum(*sorted(refs)),reason=string(300))
    schema=obj(verdicts=obj(**fields))
    evidence=scope_inputs(scope)|{'profile_documents':people,'selected_approach':graph.get('approach'),'items':questions}
    body=checker_body('final-check',judge_prompt(owned_references=True),evidence,schema)
    return body,questions,schema


def run(args):
    existing.trusted_environment();request=json.loads(os.environ['CONTEXTUAL_CHECK'])
    action=request.get('requirements_latency')
    if (action not in ('S','L','comparison-check','select','final-check','preflight') or
        set(request)!=({'requirements_latency','route','comparison_sha256'} if action=='select' else {'requirements_latency'})
        or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB','PACKET_HASH','PACKET_COMMIT'))):
        raise ConfigurationFailure('latency_exact_manual_operation')
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy());history(ledger.read());remaining_fits(ledger.read())
        existing.checkpoint(args.state)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
                stream.write('text_provider='+('openai' if action=='L' else 'none' if action=='select' else 'anthropic')+'\n')
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,'run_id':os.environ['GITHUB_RUN_ID'],
            'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'code_sha':os.environ['GITHUB_SHA'],
            'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),'latency_lock':RELEASE,
            'maximum_new_microusd':1500000,'maximum_new_attempts':8,'preserved_microusd':1267862,'preserved_attempts':2})
        return
    runner=LatencyRunner(args.state,configuration());result=None
    try:
        if action in ('S','L'):
            from tools.contextual_team_latency_contract import body as make_body
            preflight=saved(args.state,'preflight')
            data,_=eclipse_data(args.state)
            _,expected_body=make_body('adjudication',data,action,24000)
            matches=[r for r in preflight['fixed_packets'] if r['operation']==action]
            if (len(matches)!=1 or matches[0]['body_sha256']!=identity(expected_body)
                or preflight['all_eight_reserved_microusd']!=plan()['maximum_inventory_microusd']):
                raise ConfigurationFailure('latency_complete_preflight_contract_changed')
            value=runner.scientific_request('adjudication',data,action,action)
            result={'release_id':RELEASE,'value':value,'timings':runner.timings}
        elif action=='comparison-check':
            body,questions,schema,_,_=comparison_packet(args.state)
            result=run_check(runner,action,body,questions,schema)
        elif action=='select':
            if request['route'] not in ('S','L'):raise ConfigurationFailure('latency_named_route_only')
            result=validate_selection(args.state,{'release_id':RELEASE,'route':request['route'],
                                                 'comparison_sha256':request['comparison_sha256']})
            p=result_path(args.state,'selection')
            if p.exists() and json.loads(p.read_bytes())!=result:raise ConfigurationFailure('latency_selection_already_frozen')
            atomic_json(p,result)
        elif action=='final-check':
            body,questions,schema=final_packet(args.state);result=run_check(runner,action,body,questions,schema)
        else:
            from tools.contextual_team_latency_preflight import preflight
            result=preflight(runner)
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result,result or {'release_id':RELEASE,'status':'incomplete','paid_retries':0})
