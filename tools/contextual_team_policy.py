"""Fixed, named contextual allowance inside the original experiment ledger."""
import hashlib
import json
from pathlib import Path
from tools.offline_spend import identity, Deferred, ConfigurationFailure

ROOT=Path(__file__).resolve().parents[1]
INPUT_SHA='d72ba3a24200133a6fdfed0b33d3d72b3c22462499a7932e5b01b5de14ba23f9'
PURPOSES={'cb-documents':(2,'voyage',0),'cb-query':(7,'voyage',0),
          'cb-interpret':(7,'anthropic',8000),'cb-assess':(7,'anthropic',8000),
          'cb-verify':(7,'anthropic',16000),'cb-extend-assess':(1,'anthropic',8000),
          'cb-extend-verify':(1,'anthropic',16000),'cb-check':(4,'anthropic',512)}


def inputs():
    raw=(ROOT/'config/contextual_team/inputs-v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=INPUT_SHA:raise ValueError('contextual_unapproved_input_bytes')
    value=json.loads(raw)
    from tools.contextual_team_contract import contract
    if any(identity(contract(stage))!=key for stage,key in value['budget']['contract_ids'].items()):
        raise ValueError('contextual_effective_contract_changed')
    return value


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    purpose=metadata.get('purpose');rule=PURPOSES.get(purpose)
    from tools.contextual_team_cost import CAPACITY_VERSION, ASSESSMENT_OUTPUT_TOKENS
    if 'execution_capacity' in metadata and metadata['execution_capacity']!=CAPACITY_VERSION:
        raise ConfigurationFailure('unapproved_contextual_execution_capacity')
    capacity_v2=(purpose in {'cb-assess','cb-extend-assess'}
                 and metadata.get('execution_capacity')==CAPACITY_VERSION)
    expected_output=ASSESSMENT_OUTPUT_TOKENS if capacity_v2 else rule[2] if rule else None
    if not rule or provider!=rule[1] or output_tokens!=expected_output:
        raise ConfigurationFailure('unapproved_contextual_purpose_or_capacity')
    rows=state['requests'];task=[r for r in rows if r.get('purpose','').startswith('cb-')]
    if (len(rows)>=669 or len(task)>=40 or sum(r['charged_microusd'] for r in rows)+amount>9_290_655
        or sum(r['charged_microusd'] for r in task)+amount>5_000_000):
        raise Deferred('contextual_task_or_preserved_reserve_exhausted')
    if sum(r.get('purpose')==purpose for r in task)>=rule[0]:
        raise Deferred('contextual_finite_stage_inventory_exhausted')
    # The executor enforces tighter source-specific complete-packet bounds.
    ceiling=80_000 if purpose=='cb-documents' else 25_000 if purpose=='cb-query' else 85_000
    if input_tokens>ceiling:raise Deferred('contextual_input_token_envelope_exhausted')
    minimum=(input_tokens*3+24)//25 if provider=='voyage' else input_tokens*2+output_tokens*10
    if amount<minimum:raise ValueError('contextual_underreserved_request')
