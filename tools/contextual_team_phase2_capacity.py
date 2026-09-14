"""One named completed mechanical repair; no generic retry authority."""
import hashlib
import json
from copy import deepcopy
from tools.contextual_team_policy import ROOT
from tools.offline_spend import identity, ConfigurationFailure


def amendment():
    value=json.loads((ROOT/'config/contextual_team/phase2-output-capacity-v2.json').read_bytes())
    stamp=value.pop('amendment_id')
    if identity(value)!=stamp:raise ConfigurationFailure('phase2_capacity_identity')
    return value|{'amendment_id':stamp}


def apply(base):
    a=amendment()
    if base['release_id']!=a['base_release_id']:raise ConfigurationFailure('phase2_capacity_release')
    value=deepcopy(base);ops=value['operations']
    for op in ops:
        if op['scope_id']=='351715' and op['stage']=='assess':
            op.update(output_token_ceiling=a['assessment_output_tokens'],maximum_microusd=340000)
    value['operations']=[op for op in ops if not (op['scope_id'] in a['paired_group_scope_ids'] and op['stage']=='check-group')]
    template=next(op for op in ops if op['scope_id']==a['repair_scope_id'] and op['stage']=='assess')
    value['operations'].append(template|{'id':a['repair_scope_id']+':repair-assess','stage':'repair-assess',
        'purpose':'cb-p2-repair-assess','input_token_ceiling':a['repair_input_token_ceiling'],
        'output_token_ceiling':a['assessment_output_tokens'],'maximum_microusd':a['repair_maximum_microusd'],
        'repair_of':a['repair_of']})
    value['operations'].append({'id':'paired-remaining:check-group-pair','scope_id':'paired-remaining',
        'stage':'check-group-pair','purpose':'cb-p2-check-group-pair','provider':'anthropic',
        'input_token_ceiling':a['paired_group_input_token_ceiling'],
        'output_token_ceiling':a['paired_group_output_token_ceiling'],
        'maximum_microusd':a['paired_group_maximum_microusd']})
    value['capacity_amendment']=a
    return value


def check_original(state,a):
    from tools.contextual_team_executor import RecoveryRequired
    rows=state['requests'];n=a['prior_attempts']
    if len(rows)<n or identity(rows[:n])!=a['prior_rows_sha256']:
        raise RecoveryRequired('phase2_capacity_exact_history_required')
    row=next((r for r in rows[:n] if r['id']==a['repair_of']),None)
    if (not row or row['status']!='failed' or row.get('body_sha256')!=a['repair_original_body_sha256']
        or row.get('usage',{}).get('output_tokens')!=a['repair_original_output_tokens']):
        raise RecoveryRequired('phase2_capacity_completed_failure_required')


def check_receipt(state_path,state,a):
    from tools.contextual_team_executor import RecoveryRequired
    check_original(state,a)
    path=state_path/'receipts'/(a['repair_of']+'.json')
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=a['repair_receipt_sha256']:
        raise RecoveryRequired('phase2_exact_completed_failure_receipt_required')
    receipt=json.loads(path.read_bytes())
    if (receipt.get('http_status')!=200 or receipt.get('provider_stop_reason')!='max_tokens'
        or receipt.get('status')!='failed' or receipt.get('body_sha256')!=a['repair_original_body_sha256']):
        raise RecoveryRequired('phase2_output_limit_failure_not_proven')


def is_repair_job(job):
    a=amendment()
    return (job.get('release_id')==a['base_release_id'] and job.get('scope_id')==a['repair_scope_id']
            and job.get('person_id')=='' and job.get('job_id')==a['repair_job_id'])
