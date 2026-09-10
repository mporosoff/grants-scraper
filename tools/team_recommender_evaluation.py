"""Finite blinded development packet contracts. Contains no judge execution."""
import hashlib
import json
from pathlib import Path
from tools.offline_ai import request_body
from tools.offline_spend import encoded, Deferred

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender'
RUBRIC='E1-B1-batched-v2'
LABELS={'strong','plausible','unrelated','insufficient-information'}

def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def development_only(scope_id):
    manifest=json.loads((DOC/'manifests/development.json').read_bytes())
    if scope_id not in {s['id'] for s in manifest['scopes']}:
        raise ValueError('scope_outside_development_manifest')

def deduplicate(items):
    """Scientific evidence and task determine identity; algorithm/rank only count occurrences."""
    unique={}; occurrences=[]
    for item in items:
        safe={k:v for k,v in item.items() if k in {'scope_id','task_type','source_evidence','profile_evidence','candidates','explanation'}}
        development_only(safe['scope_id'])
        if not safe.get('source_evidence') or not safe.get('profile_evidence') and safe['task_type']!='source_control':
            raise ValueError('original_evidence_required')
        if safe['task_type']!='explanation_audit' and 'explanation' in safe:
            raise ValueError('persuasive_explanation_in_semantic_packet')
        key=identity([RUBRIC,safe]);unique.setdefault(key,{'item_id':key,**safe})
        occurrences.append({'item_id':key,'algorithm':item.get('algorithm'),'rank':item.get('rank')})
    return list(unique.values()),occurrences

def balanced_orientation(pairs):
    ordered=sorted(pairs,key=lambda p:identity([RUBRIC,p['item_id']]))
    return [{**p,'swap':bool(i%2)} for i,p in enumerate(ordered)]

def request_contract(packet,prompt,schema):
    if not packet or len(packet)>10 or len({p['scope_id'] for p in packet})!=1:
        raise ValueError('bounded_same_scope_packet_required')
    kinds={p['task_type']=='explanation_audit' for p in packet}
    if len(kinds)>1:raise ValueError('explanations_require_separate_packet')
    source=packet[0]['source_evidence']
    if any(row['source_evidence']!=source for row in packet):raise ValueError('substantive_source_evidence_differs')
    ordered=sorted(packet,key=lambda p:p['item_id'])
    aliases={f'i{i+1:02d}':row['item_id'] for i,row in enumerate(ordered)}
    compact=[{'item_id':f'i{i+1:02d}',**{k:v for k,v in row.items() if k not in {'item_id','scope_id','source_evidence'}}} for i,row in enumerate(ordered)]
    body=request_body({'provider':'anthropic','model':'claude-sonnet-5'},
        {'max_output_tokens':512,'schema_version':RUBRIC},prompt,{'source_evidence':source,'items':compact},schema)
    # Same conservative UTF-8-byte token bound and framing margin as the trusted client.
    ceiling=len(encoded(body))+1024
    if ceiling>12000: raise Deferred('original_evidence_packet_exceeds_budgeted_bound')
    return {'body':body,'aliases':aliases,'cache_identity':identity([RUBRIC,body]),'input_token_reservation':ceiling,
        'output_token_reservation':512,'reserve_microusd':(ceiling*5+1)//2+5120,'provider_calls':0}

def agreement(human,model):
    table={};assessable=agree=0
    for item_id,label in human.items():
        prediction=model.get(item_id)
        if label not in LABELS or prediction not in LABELS:continue
        assessable+=1;agree+=label==prediction;key=label+'/'+prediction;table[key]=table.get(key,0)+1
    return {'requested_human_items':len(human),'paired_assessable':assessable,'exact_agreement':agree/assessable if assessable else None,
        'confusion':table,'calibrated_human_preference':False}
