"""One fixed offline check of actual contextual outputs, through the same ledger.

Group IDs are bounded data from the experimental composer. Original source and
full person evidence are resolved here; callers cannot supply prompts or prose.
"""
import argparse
import json
import os
from pathlib import Path
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, scope_inputs
from tools.contextual_team_policy import inputs as configuration, INPUT_SHA
from tools.contextual_team_cost import JUDGE_BODY_BYTES
from tools.contextual_team_contract import obj, array, string, enum
from tools.offline_ai import request_body, response_value, validate_schema
from tools.offline_spend import identity, atomic_json


def graphs(state,config):
    selected=[];seen=set()
    for scope in config['scopes']:
        key=identity(['contextual-graph',config['snapshot_id'],scope['id'],''])
        path=state/'cache'/(key+'.json')
        if not path.exists():continue
        wrapper=json.loads(path.read_bytes());graph=wrapper['value']
        if (wrapper['kind']!='contextual_graph' or graph['snapshot_id']!=config['snapshot_id']
            or graph['source_id']!=scope['source_id'] or graph['graph_id']!=identity({k:v for k,v in graph.items() if k not in ('graph_id','requests')})):
            raise ValueError('contextual_check_graph_identity')
        if graph['state'] not in ('ready','ready_with_gaps'):continue
        if scope['group_id'] in seen:continue
        seen.add(scope['group_id'])
        selected.append((scope,graph))
        if len(selected)==2:break
    return selected


def packet(scope,graph,members,kind,config):
    useful=[e for e in graph['edges'] if e['coverage'] in ('direct','method_transfer')]
    if not 2<=len(members)<=4 or len(set(members))!=len(members):raise ValueError('contextual_check_member_count')
    if any(not any(e['person_id']==pid for e in useful) for pid in members) or not any(e['person_id'] in members and e['central'] for e in useful):
        raise ValueError('contextual_check_requires_actual_assessed_members')
    people=[p for p in config['people'] if p['person_id'] in members]
    evidence=scope_inputs(scope)|{'profile_documents':people}
    questions=[]
    if kind=='group':
        questions=[{'item_id':'group','task_type':'group_usefulness','people':members}]
        questions += [{'item_id':'person-'+str(i+1),'task_type':'call_person','people':[pid]} for i,pid in enumerate(members)]
    else:
        for i,pid in enumerate(members):
            edge=sorted([e for e in useful if e['person_id']==pid],key=lambda e:(-int(e['central']),e['role_id'],e['claim_id']))[0]
            questions.append({'item_id':'explanation-'+str(i+1),'task_type':'explanation_audit','people':[pid],
                'assertion':{'contribution':edge['reason'],'retained_evidence_excerpt':edge['evidence_quote'],'limitation':edge['gap'],
                  'coverage':'Model-assessed possible transfer' if edge['coverage']=='method_transfer' else 'Model-assessed contribution',
                  'qualification':'This is not a capability certificate.'}})
    evidence['items']=questions
    schema=obj(verdicts=array(obj(item_id=enum(*(q['item_id'] for q in questions)),
        verdict=enum(*(['faithful','unsupported','insufficient-information'] if kind=='explanation' else ['strong','plausible','unrelated','insufficient-information'])),
        evidence_ref=string(100),reason=string(60)),len(questions)))
    prompt=(existing.CONFIG/'judge-d1.md').read_text(encoding='utf8')+'\nThe source object contains the full retained scope and governing conditions. Read the requested activity; do not substitute a different research project. Each person document contains the unchanged audited summary and all active labels/evidence. Cite scope.science or a supplied person/claim ID. Assess every person separately from group usefulness.'
    body=request_body({'provider':'anthropic','model':'claude-sonnet-5'},
        {'schema_version':'contextual-check-v1','max_output_tokens':512},prompt,evidence,schema)
    if len(existing.encoded(body))>JUDGE_BODY_BYTES:raise ValueError('contextual_check_full_evidence_exceeds_bound')
    refs={'scope.science'}|{p['person_id'] for p in people}|{c['claim_id'] for p in people for c in p['claims']}
    def check(value,cached):
        value=validate_schema(value if cached else response_value('anthropic',value),schema)
        if len(value['verdicts'])!=len(questions) or {v['item_id'] for v in value['verdicts']}!={q['item_id'] for q in questions}:
            raise ValueError('contextual_check_missing_verdict')
        if any(v['evidence_ref'] not in refs or not v['reason'].isascii() for v in value['verdicts']):raise ValueError('contextual_check_invalid_reference')
        return value
    return body,check


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','execute'])
    p.add_argument('--state',type=Path,required=True);p.add_argument('--reservation',type=Path)
    p.add_argument('--result',type=Path);args=p.parse_args();existing.trusted_environment();config=configuration()
    requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    if not isinstance(requested,list) or len(requested)>2:raise ValueError('contextual_check_two_groups_only')
    if args.action=='prepare':
        if os.environ.get('CONTEXTUAL_JOB') or os.environ.get('PACKET_HASH') or os.environ.get('PACKET_COMMIT'):
            raise ValueError('contextual_check_mutually_exclusive_operation')
        ledger=existing.restore(args.state,existing.policy());existing.checkpoint(args.state)
    selected=graphs(args.state,config)
    if [r.get('scope_id') for r in requested]!=[scope['id'] for scope,graph in selected]:
        raise ValueError('contextual_check_fixed_first_two_output_sources_required')
    packets=[]
    for row,(scope,graph) in zip(requested,selected):
        if set(row)!={'scope_id','graph_id','members'} or row['graph_id']!=graph['graph_id']:
            raise ValueError('contextual_check_exact_graph_required')
        for kind in ('group','explanation'):
            body,check=packet(scope,graph,row['members'],kind,config);packets.append((scope,kind,body,check))
    if args.action=='prepare':
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,'run_id':os.environ['GITHUB_RUN_ID'],
            'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'code_sha':os.environ['GITHUB_SHA'],'input_sha256':INPUT_SHA,
            'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),'maximum_logical_spend_usd':10,
            'contextual_task_maximum_usd':5,'requests':len(packets)})
        return
    runner=Runner(args.state,config);results=[]
    try:
        for scope,kind,body,check in packets:
            # One fixed logical question per scope/kind: changed group membership
            # or rebatching does not grant another paid attempt after a claim.
            result=runner.request('cb-check',['cb-check',config['snapshot_id'],scope['id'],kind],body,check,ceiling=JUDGE_BODY_BYTES+1024)
            results.append({'scope_id':scope['id'],'kind':kind,'body_sha256':identity(body),'value':result})
    finally:
        atomic_json(args.result,{'version':'contextual-check-v1','results':results,'requests':runner.used,
            'selected_scopes':[scope['id'] for scope,graph in selected],'maximum_scopes':2,
            'same_model_family_limitation':True,'human_judgments':0})
        existing.checkpoint(args.state)


if __name__=='__main__':main()
