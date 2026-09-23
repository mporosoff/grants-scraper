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


RESPONSE_CONTRACT = {
    'version': 'contextual-check-response-v2',
    'max_output_tokens': 2048,
    'max_response_bytes': 32768,
    'reason': 'nonempty complete string; short requested, never truncated',
    'completion': 'end_turn; complete JSON; exact question IDs/count; owned evidence references',
    'thinking': 'disabled',
}
LEGACY_FORMAT = 'Return exactly one verdict per item, one supplied evidence reference and a concise reason of at most 60 ASCII characters. No shared verdict, extra commentary or request for reruns.'
REVISED_FORMAT = 'Return exactly one verdict per item, one supplied evidence reference and a short explanation. Preserve the complete reason. No shared verdict, extra commentary or request for reruns.'
OWNED_FORMAT = 'Return a verdicts object keyed by the exact question IDs. For each question, select evidence_ref verbatim from its schema enum: one exact scope, person or claim identifier, never a field path, combined citation or another person\'s claim. Give a short complete explanation; never truncate it. No extra commentary or request for reruns.'
OWNED_RESPONSE_CONTRACT = RESPONSE_CONTRACT | {
    'version': 'contextual-check-response-v3',
    'references': 'provider-enforced per-question enum; exact keyed questions; canonical array cache',
}


def judge_prompt(*,revised=False,owned_references=False):
    prompt=(existing.CONFIG/'judge-d1.md').read_text(encoding='utf8')+'\nThe source object contains the full retained scope and governing conditions. Read the requested activity; do not substitute a different research project. Each person document contains the unchanged audited summary and all active labels/evidence. Cite scope.science or a supplied person/claim ID. Assess every person separately from group usefulness.'
    if revised or owned_references:
        if prompt.count(LEGACY_FORMAT)!=1:raise ValueError('contextual_check_original_format_changed')
        prompt=prompt.replace(LEGACY_FORMAT,REVISED_FORMAT)
    if owned_references:prompt=prompt.replace(REVISED_FORMAT,OWNED_FORMAT)
    return prompt


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


def packet(scope,graph,members,kind,config,*,revised=False,owned_references=False):
    revised = revised or owned_references
    if kind not in ('group','explanation'):raise ValueError('contextual_check_kind')
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
    owned={q['item_id']:{'scope.science'}|set(q['people'])|
        {c['claim_id'] for p in people if p['person_id'] in q['people'] for c in p['claims']} for q in questions}
    schema=obj(verdicts=array(obj(item_id=enum(*(q['item_id'] for q in questions)),
        verdict=enum(*(['faithful','unsupported','insufficient-information'] if kind=='explanation' else ['strong','plausible','unrelated','insufficient-information'])),
        evidence_ref=string(100),reason=string(60)),len(questions)))
    prompt=judge_prompt(revised=revised,owned_references=owned_references)
    if revised:
        schema['properties']['verdicts']['items']['properties']['reason']={'type':'string','minLength':1}
    if owned_references:
        fields=schema['properties']['verdicts']['items']['properties']
        schema=obj(verdicts=obj(**{q['item_id']:obj(verdict=fields['verdict'],
            evidence_ref=enum(*sorted(owned[q['item_id']])),reason=fields['reason']) for q in questions}))
    response_contract=OWNED_RESPONSE_CONTRACT if owned_references else RESPONSE_CONTRACT
    body=request_body({'provider':'anthropic','model':'claude-sonnet-5'},
        {'schema_version':response_contract['version'] if revised else 'contextual-check-v1',
         'max_output_tokens':RESPONSE_CONTRACT['max_output_tokens'] if revised else 512},prompt,evidence,schema)
    # Match the established compact judge transport: output capacity belongs to
    # the explicit verdicts, not an implicit adaptive-thinking allocation.
    body['thinking']={'type':'disabled'}
    if len(existing.encoded(body))>JUDGE_BODY_BYTES:raise ValueError('contextual_check_full_evidence_exceeds_bound')
    refs={'scope.science'}|{p['person_id'] for p in people}|{c['claim_id'] for p in people for c in p['claims']}
    def check(value,cached):
        if revised and len(existing.encoded(value))>RESPONSE_CONTRACT['max_response_bytes']:
            raise ValueError('contextual_check_complete_response_byte_bound')
        if owned_references:
            if cached:
                rows=value.get('verdicts') if isinstance(value,dict) else None
                if (not isinstance(rows,list) or len(rows)!=len(questions)
                    or any(not isinstance(row,dict) or 'item_id' not in row for row in rows)
                    or len({row['item_id'] for row in rows})!=len(rows) or set(value)!={'verdicts'}):
                    raise ValueError('contextual_check_invalid_canonical_cache')
                value={'verdicts':{row['item_id']:{k:v for k,v in row.items() if k!='item_id'} for row in rows}}
            else:
                value=response_value('anthropic',value)
            value=validate_schema(value,schema)
            return {'verdicts':[{'item_id':q['item_id'],**value['verdicts'][q['item_id']]} for q in questions]}
        value=validate_schema(value if cached else response_value('anthropic',value),schema)
        if len(value['verdicts'])!=len(questions) or {v['item_id'] for v in value['verdicts']}!={q['item_id'] for q in questions}:
            raise ValueError('contextual_check_missing_verdict')
        if any(v['evidence_ref'] not in (owned[v['item_id']] if revised else refs)
               or (not revised and not v['reason'].isascii()) for v in value['verdicts']):
            raise ValueError('contextual_check_invalid_reference')
        return value
    return body,check


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','execute'])
    p.add_argument('--state',type=Path,required=True);p.add_argument('--reservation',type=Path)
    p.add_argument('--result',type=Path);args=p.parse_args();existing.trusted_environment()
    requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    if isinstance(requested,dict) and 'iteration3_ec_disposition' in requested:
        from tools.contextual_team_ec_recovery import run
    elif isinstance(requested,dict) and 'iteration3_continuation' in requested:
        from tools.contextual_team_iteration3_continuation import run
    elif isinstance(requested,dict) and 'iteration3_capacity' in requested:
        from tools.contextual_team_iteration3_capacity import run
    elif isinstance(requested,dict) and 'iteration3_check' in requested:
        from tools.contextual_team_iteration3_check import run
    elif isinstance(requested,dict) and 'iteration2_checkpoint_disposition' in requested:
        from tools.contextual_team_checkpoint_recovery import run
    elif isinstance(requested,dict) and 'iteration2_check_recovery' in requested:
        from tools.contextual_team_iteration2_check_recovery import run
    elif isinstance(requested,dict) and 'iteration2_check' in requested:
        from tools.contextual_team_iteration2_check import run
    elif isinstance(requested,dict) and requested.get('completion_iteration1') == 'retained-response':
        from tools.contextual_team_retained_check import run
    elif isinstance(requested,dict) and 'completion_iteration1' in requested:
        from tools.contextual_team_completion_check import run
    elif isinstance(requested,dict) and 'compact_wire_repair' in requested:
        from tools.contextual_team_wire_repair import run
    elif isinstance(requested,dict) and 'compact_check_continuation' in requested:
        from tools.contextual_team_compact_check import run
    elif isinstance(requested,dict) and 'luna_contract_repair' in requested:
        from tools.contextual_team_luna_repair import run
    elif isinstance(requested,dict) and 'requirements_latency' in requested:
        from tools.contextual_team_latency_check import run
    elif isinstance(requested,dict) and 'phase2_token_preflight' in requested:
        from tools.contextual_team_token_preflight import run
    elif isinstance(requested,dict) and 'phase2_output_check' in requested:
        from tools.contextual_team_phase2_check import run
    else:
        from tools.contextual_team_phase1 import run
    run(args)


if __name__=='__main__':main()
