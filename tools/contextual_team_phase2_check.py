"""Once-per-scope output checks, from actual graphs and the exact preview composer."""
import json
import os
import shutil
import subprocess
from tools import team_recommender_executor as existing
from tools.contextual_team_check import judge_prompt, OWNED_RESPONSE_CONTRACT
from tools.contextual_team_contract import obj, enum
from tools.contextual_team_executor import scope_inputs, RecoveryRequired
from tools.contextual_team_phase2 import configuration, plan, operation, RELEASE, Phase2Runner, scope_result_path, ensure_remaining_plan_fits
from tools.offline_ai import request_body, response_value, validate_schema
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure


def select(graph):
    node=shutil.which('node')
    if not node:raise ConfigurationFailure('phase2_exact_composer_runtime_unavailable')
    # Child process executes only reviewed pure composition, without secrets.
    safe_env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'}}
    raw=subprocess.check_output([node,'tools/contextual_phase2_selection.mjs'],input=encoded({'graph':graph}),env=safe_env,timeout=30)
    return json.loads(raw)


def packet(scope,graph,selection,kind,config):
    groups=selection['groups'];people_by_id={p['person_id']:p for p in config['people']}
    people_ids=list(dict.fromkeys(pid for group in groups for pid in group))
    if not groups:people_ids=[p['person_id'] for p in graph.get('people',graph.get('verification',{}).get('people',[]))]
    people=[people_by_id[pid] for pid in people_ids]
    questions=[]
    if kind=='group' and groups:
        questions=[{'item_id':'group-'+str(i+1),'task_type':'group_usefulness','people':ids} for i,ids in enumerate(groups)]
        questions += [{'item_id':'person-'+str(i+1),'task_type':'call_person','people':[pid]} for i,pid in enumerate(people_ids)]
    elif kind=='group':
        questions=[{'item_id':'bounded-gap','task_type':'explanation_audit','people':people_ids,
            'assertion':{'state':graph['state'],'objective':graph.get('objective'),
                'interpretation':graph.get('interpretation'),'verification':graph.get('verification'),
                'assessed_people':graph.get('people',[]),'relationships':graph.get('edges',[]),
                'qualification':'No supported group was produced within this assessed set under the frozen composer. This is not directory-wide infeasibility.'}}]
    elif kind=='explanation' and groups:
        for i,pid in enumerate(groups[0]):
            shown=next(s['evidence'] for s in selection['primary_view'] if s['person_id']==pid)
            claim=next((c for c in people_by_id[pid]['claims'] if c['evidence'].find(shown['evidence_phrase'])>=0
                        and c['label']==shown['evidence_term']),None)
            if not claim or len(shown['evidence_phrase'])<8:raise ValueError('phase2_actual_explanation_evidence_missing')
            questions.append({'item_id':'explanation-'+str(i+1),'task_type':'explanation_audit','people':[pid],
                'assertion':{'explanation':shown['why_person'],'source_url':shown['source_url']}})
        people=[people_by_id[pid] for pid in groups[0]]
    else:return None
    if any(not 2<=len(group)<=4 or len(set(group))!=len(group) for group in groups) or len(groups)>2:
        raise ValueError('phase2_frozen_group_selection_conflict')
    fields={}
    for q in questions:
        refs={'scope.science'}|set(q['people'])|{c['claim_id'] for p in people if p['person_id'] in q['people'] for c in p['claims']}
        labels=['faithful','unsupported','insufficient-information'] if q['task_type']=='explanation_audit' else ['strong','plausible','unrelated','insufficient-information']
        fields[q['item_id']]=obj(verdict=enum(*labels),evidence_ref=enum(*sorted(refs)),reason={'type':'string','minLength':1})
    schema=obj(verdicts=obj(**fields));op=operation(scope['id'],'check-'+kind)
    output=min(op['output_token_ceiling'],512+256*len(questions))
    evidence=scope_inputs(scope)|{'profile_documents':people,'items':questions}
    body=request_body({'provider':'anthropic','model':'claude-sonnet-5'},
        {'schema_version':'contextual-phase2-output-check-v1','max_output_tokens':output},
        judge_prompt(owned_references=True),evidence,schema)
    body['thinking']={'type':'disabled'}
    if len(encoded(body))>plan()['maximum_wire_bytes']:raise ValueError('phase2_full_check_wire_capacity')
    def check(value,cached):
        if len(encoded(value))>OWNED_RESPONSE_CONTRACT['max_response_bytes']:raise ValueError('phase2_complete_check_response_too_large')
        if cached:
            rows=value.get('verdicts') if isinstance(value,dict) else None
            if not isinstance(rows,list) or len(rows)!=len(questions) or len({r['item_id'] for r in rows})!=len(rows):
                raise ValueError('phase2_invalid_exact_judge_cache')
            value={'verdicts':{r['item_id']:{k:v for k,v in r.items() if k!='item_id'} for r in rows}}
        else:value=response_value('anthropic',value)
        value=validate_schema(value,schema)
        return {'verdicts':[{'item_id':q['item_id'],**value['verdicts'][q['item_id']]} for q in questions]}
    return op,body,check


def prepared(state,requested):
    if not isinstance(requested,dict) or set(requested)!={'phase2_output_check','release_id','result_id'} or requested['release_id']!=RELEASE:
        raise ConfigurationFailure('phase2_exact_output_check_request')
    config=configuration();scope=next((s for s in config['scopes'] if s['id']==requested['phase2_output_check']),None)
    if not scope:raise ConfigurationFailure('phase2_unapproved_check_scope')
    path=scope_result_path(state,scope['id'])
    if not path.exists():raise RecoveryRequired('phase2_actual_completed_scope_result_required')
    wrapper=json.loads(path.read_bytes());graph=wrapper['value']
    if (wrapper['kind']!='contextual_scope_result' or wrapper['snapshot_id']!=RELEASE
        or wrapper['source_id']!=scope['source_id'] or identity(graph)!=requested['result_id']):
        raise ConfigurationFailure('phase2_actual_result_identity_conflict')
    selection=select(graph) if graph.get('graph_id') else {'groups':[],'option_count':0,'primary_view':[]}
    packets=[p for kind in ('group','explanation') if (p:=packet(scope,graph,selection,kind,config)) is not None]
    return config,scope,selection,packets


def run(args):
    requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    if os.environ.get('CONTEXTUAL_JOB') or os.environ.get('PACKET_HASH') or os.environ.get('PACKET_COMMIT'):
        raise ConfigurationFailure('phase2_check_exclusive_operation')
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy());existing.checkpoint(args.state)
    else:
        from tools.team_recommender_budget import ExperimentLedger
        ledger=ExperimentLedger(args.state/'ledger.json')
    ensure_remaining_plan_fits(ledger.read());config,scope,selection,packets=prepared(args.state,requested)
    if args.action=='prepare':
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,'run_id':os.environ['GITHUB_RUN_ID'],
            'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'code_sha':os.environ['GITHUB_SHA'],'phase2_lock':RELEASE,
            'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),'selection':selection,
            'packets':[{'operation':op['id'],'body_sha256':identity(body),'bytes':len(encoded(body))} for op,body,_ in packets],
            'maximum_new_microusd':plan()['maximum_new_microusd'],'maximum_new_attempts':18})
        return
    runner=Phase2Runner(args.state,config);runner.scope_id=scope['id'];results=[]
    try:
        for op,body,check in packets:
            value=runner.request(op['purpose'],[op['purpose'],RELEASE,scope['id'],requested['result_id'],identity(body)],body,check)
            results.append({'operation':op['id'],'body_sha256':identity(body),'evidence':json.loads(body['messages'][0]['content']),
                'value':value})
            atomic_json(args.result,{'results':results,'selection':selection,'requests':runner.used})
    finally:
        atomic_json(args.result,{'version':'contextual-phase2-output-check-v1','results':results,'selection':selection,
            'scope_id':scope['id'],'requests':runner.used,'durable_requests':[r for r in ledger.read()['requests']
                if r.get('phase2_operation') in {op['id'] for op,_,_ in packets}],
            'human_judgments':0,'same_model_family_limitation':True})
        existing.checkpoint(args.state)
