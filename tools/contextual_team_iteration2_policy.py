"""Twelve named development workflows inside the existing completion pool.

This records execution scope, never another allowance. Historical claims and
unknown holds remain immutable; a scope/stage cannot acquire a second identity.
"""
import json
import math
import os
from pathlib import Path

from tools import contextual_team_completion_policy as pool
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-iteration2-20260921-v1'
PREFIX = 'cb-fc-i2-'
STAGES = {'interpret': ('openai', 'gpt-5.6-luna', 8000),
          'query': ('voyage', 'voyage-4-large', 0),
          'assess': ('openai', 'gpt-5.6-luna', 24000),
          'verify': ('anthropic', 'claude-sonnet-5', 24000),
          'check': ('anthropic', 'claude-sonnet-5', 12000)}


def plan():
    value = json.loads((ROOT/'config/contextual_team/iteration2-authority-v1.json').read_bytes())
    release = value.get('release_id')
    if (value.get('version') != VERSION or value.get('authorization_id') != existing.AUTHORIZATION_ID
            or release != identity({k: v for k, v in value.items() if k != 'release_id'})
            or value.get('no_second_allowance') is not True
            or value.get('public_activation') is not False or value.get('recurring_paid_usage') is not False):
        raise ConfigurationFailure('iteration2_authority_identity')
    scopes = value['scope_ids']
    if (len(scopes) != 12 or len(set(scopes)) != 12 or value['first_scope_id'] != '363302:a-1'
            or value['first_scope_id'] not in scopes
            or value['stages'] != {k: {'provider': v[0], 'model': v[1], 'output_tokens': v[2]} for k, v in STAGES.items()}):
        raise ConfigurationFailure('iteration2_fixed_development_inventory')
    for filename, key in (('iteration2-development-v1.json', 'development_manifest_sha256'),
                          ('iteration2-source-inputs-v1.json', 'source_inputs_sha256'),
                          ('iteration2-confirmation-seal-v1.json', 'confirmation_seal_sha256'),
                          ('iteration2-source-selection-v1.json', 'source_selection_sha256')):
        if existing.sha((ROOT/'config/contextual_team'/filename).read_bytes()) != value[key]:
            raise ConfigurationFailure('iteration2_source_manifest_changed')
    return value


def event():
    p = plan()
    return {'kind': 'iteration2_execution_scope', 'authority': VERSION,
        'release_id': p['release_id'], 'plan_sha256': identity(p),
        'starting_checkpoint': p['starting_checkpoint'], 'scope_ids': p['scope_ids'],
        'stages': p['stages'], 'spending_owner': existing.AUTHORIZATION_ID,
        'additional_allowance': 0, 'no_second_allowance': True,
        'public_activation': False, 'recurring_paid_usage': False}


def operation(scope_id, stage):
    p = plan()
    if scope_id not in p['scope_ids'] or stage not in STAGES:
        raise ConfigurationFailure('iteration2_unapproved_scope_or_stage')
    return PREFIX + scope_id + ':' + stage


def _stage(purpose):
    if not isinstance(purpose, str) or not purpose.startswith(PREFIX):
        raise ConfigurationFailure('iteration2_unapproved_operation')
    scope_id, stage = purpose[len(PREFIX):].rsplit(':', 1)
    if operation(scope_id, stage) != purpose:
        raise ConfigurationFailure('iteration2_unapproved_operation')
    return scope_id, stage


def history(state, require_authority=True):
    pool.history(state)
    start = plan()['starting_checkpoint']
    if (len(state['requests']) < start['requests']
            or identity(state['requests'][:start['requests']]) != start['requests_sha256']
            or identity(state['events'][:start['events']]) != start['events_sha256']):
        raise ConfigurationFailure('iteration2_original_history_changed')
    installed = [e for e in state['events'] if e.get('authority') == VERSION]
    authorities = [e for e in installed if e.get('kind') == 'iteration2_execution_scope']
    if authorities != [event()] and (require_authority or installed):
        raise ConfigurationFailure('iteration2_exact_authority_required')
    seen = set()
    for item in installed:
        if item.get('kind') == 'iteration2_execution_scope':
            continue
        if (item.get('kind') != 'iteration2_exact_operation' or set(item) != {
                'kind', 'authority', 'purpose', 'provider', 'model', 'body_sha256',
                'input_sha256', 'contract_sha256', 'contract_version', 'output_tokens', 'plan_sha256'}):
            raise ConfigurationFailure('iteration2_operation_event_shape')
        _, stage = _stage(item['purpose'])
        provider, model, output = STAGES[stage]
        if (item['purpose'] in seen or (item['provider'], item['model'], item['output_tokens']) != (provider, model, output)
                or item['plan_sha256'] != identity(plan())
                or any(not isinstance(item[k], str) or len(item[k]) != 64
                       or any(c not in '0123456789abcdef' for c in item[k])
                       for k in ('body_sha256', 'input_sha256', 'contract_sha256'))):
            raise ConfigurationFailure('iteration2_operation_event_identity')
        seen.add(item['purpose'])
    unknown = [(index, r['id']) for index, r in enumerate(state['requests']) if r['status'] == 'reserved_unknown']
    if any(index >= start['requests'] or rid not in pool.HISTORICAL_UNKNOWN_IDS for index, rid in unknown):
        raise Deferred('iteration2_new_uncertainty_requires_recovery')


def check_counts(state_path):
    from tools.contextual_team_token_preflight import VERSION as count_version, SOURCE_SHA
    cp = json.loads((Path(state_path)/'checkpoint.json').read_bytes())
    saved = cp['phase2_token_preflight']; rows = saved['rows']; start = plan()['starting_checkpoint']
    if (cp.get('authorization_id') != existing.AUTHORIZATION_ID
            or saved.get('version') != count_version or saved.get('source_sha256') != SOURCE_SHA):
        raise ConfigurationFailure('iteration2_native_checkpoint_owner')
    if (len(rows) < start['native_counts']
            or identity(rows[:start['native_counts']]) != start['native_counts_sha256']):
        raise ConfigurationFailure('iteration2_original_native_counts_changed')
    return rows


def install_authority(state_path, api_call):
    state_path = Path(state_path); ledger = existing.ExperimentLedger(state_path/'ledger.json')
    start = plan()['starting_checkpoint']
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active):
        raise Deferred('iteration2_another_spending_owner_active')
    run = json.loads(api_call('actions/runs/'+str(start['run']['id'])))
    if any(run.get(k) != v for k, v in start['run'].items()):
        raise Deferred('iteration2_starting_owner_not_terminal')
    with ledger.locked():
        state = ledger.read(); history(state, require_authority=False); check_counts(state_path)
        if not any(e.get('authority') == VERSION for e in state['events']):
            cp_raw = (state_path/'checkpoint.json').read_bytes(); cp = json.loads(cp_raw)
            actual = {f.relative_to(state_path).as_posix(): existing.sha(f.read_bytes())
                for f in state_path.rglob('*.json') if f.name != 'checkpoint.json'}
            if (existing.sha(ledger.path.read_bytes()) != start['ledger_sha256']
                    or existing.sha(cp_raw) != start['checkpoint_sha256'] or actual != cp['files']):
                raise ConfigurationFailure('iteration2_exact_starting_checkpoint_required')
            state['events'].append(event()); atomic_json(ledger.path, state)
        history(state); pool.check_pool(state)
        existing.checkpoint(state_path)
    return ledger


def packet_event(purpose, body, contract, input_id):
    _, stage = _stage(purpose); provider, model, output = STAGES[stage]
    if body.get('model') != model or body.get('max_tokens', body.get('max_output_tokens', 0)) != output:
        raise ConfigurationFailure('iteration2_exact_model_or_capacity')
    if len(encoded(body)) > plan()['maximum_wire_bytes']:
        raise Deferred('iteration2_complete_wire_bound_no_truncation')
    return {'kind': 'iteration2_exact_operation', 'authority': VERSION, 'purpose': purpose,
        'provider': provider, 'model': model, 'body_sha256': identity(body),
        'input_sha256': input_id, 'contract_sha256': identity(contract),
        'contract_version': contract['version'], 'output_tokens': output, 'plan_sha256': identity(plan())}


def bind_operation(ledger, purpose, body, contract, input_id):
    """Before token counting: persist the exact packet, including on failures."""
    expected = packet_event(purpose, body, contract, input_id)
    with ledger.locked():
        state = ledger.read(); history(state)
        from tools.contextual_team_checkpoint_disposition import assert_operation_open
        assert_operation_open(state, purpose)
        saved = [e for e in state['events'] if e.get('authority') == VERSION and e.get('purpose') == purpose]
        if saved and saved != [expected]:
            raise Deferred('iteration2_operation_changed_no_rekey')
        if not saved:
            if any(r.get('purpose') == purpose for r in state['requests']):
                raise Deferred('iteration2_claimed_operation_without_exact_lock')
            state['events'].append(expected); atomic_json(ledger.path, state)
        existing.checkpoint(ledger.path.parent)
    return {'completion_authority': VERSION, 'completion_lock_sha256': identity(plan()),
        'completion_transport': contract['version'], 'pair_contract_sha256': identity(contract),
        'repair_of': None, 'packet_sha256': plan()['source_inputs_sha256'], 'execution_capacity': VERSION}


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    history(state); purpose = metadata.get('purpose'); _, stage = _stage(purpose)
    from tools.contextual_team_checkpoint_disposition import assert_operation_open
    assert_operation_open(state, purpose)
    expected = [e for e in state['events'] if e.get('authority') == VERSION and e.get('purpose') == purpose]
    if len(expected) != 1:
        raise ConfigurationFailure('iteration2_exact_packet_not_predeclared')
    e = expected[0]
    locked = {'completion_authority': VERSION, 'completion_lock_sha256': identity(plan()),
        'completion_transport': e['contract_version'], 'pair_contract_sha256': e['contract_sha256'],
        'body_sha256': e['body_sha256'], 'repair_of': None, 'packet_sha256': plan()['source_inputs_sha256'],
        'execution_capacity': VERSION}
    if any(metadata.get(k) != v for k, v in locked.items()) or provider != e['provider'] or output_tokens != e['output_tokens']:
        raise ConfigurationFailure('iteration2_reservation_packet_identity')
    if any(r.get('purpose') == purpose for r in state['requests']):
        raise Deferred('iteration2_operation_already_claimed_no_rekey')
    if type(input_tokens) is not int or input_tokens <= 0 or input_tokens > plan()['input_token_ceilings'][stage]:
        raise Deferred('iteration2_complete_input_bound_no_truncation')
    if provider == 'anthropic':
        native = metadata.get('native_input_tokens')
        if (type(native) is not int or native <= 0 or input_tokens != math.ceil(native * 1.2) + 1024
                or metadata.get('native_count_key') != metadata.get('count_body_sha256')
                or not isinstance(metadata.get('native_count_key'), str) or len(metadata['native_count_key']) != 64):
            raise ConfigurationFailure('iteration2_exact_native_count_required')
        expected_amount = input_tokens * 2 + output_tokens * 10
    elif provider == 'openai':
        expected_amount = (input_tokens + 4) // 5 + (output_tokens * 6 + 4) // 5
    else:
        expected_amount = (input_tokens * 3 + 24) // 25
    if amount != expected_amount:
        raise ConfigurationFailure('iteration2_exact_conservative_reservation')
    pool.check_pool(state, amount, 1)


def remaining(state, state_path):
    history(state); counts = check_counts(state_path); pool.check_pool(state)
    from tools.contextual_team_checkpoint_disposition import exposure, validate_counts
    validate_counts(state, counts); held = exposure(state)
    p = pool.plan(); start = p['starting_checkpoint']
    return {'microusd': p['additional']['microusd'] - sum(r['charged_microusd'] for r in state['requests'][start['requests']:]) - held['microusd'],
        'attempts': p['additional']['attempts'] - (len(state['requests']) - start['requests']) - held['attempts'],
        'native_counts': p['additional']['native_counts'] - (len(counts) - start['native_counts']) - held['native_counts']}


def prepare_record(state_path, job):
    ledger = existing.ExperimentLedger(Path(state_path)/'ledger.json'); state = ledger.read()
    from tools.contextual_team_checkpoint_disposition import assert_operation_open, exposure
    assert_operation_open(state, operation(job['scope_id'], 'interpret'))
    balance = remaining(state, state_path); p = pool.plan()
    bounds = plan()['input_token_ceilings']
    maximum = sum((bounds[stage] * 3 + 24) // 25 if provider == 'voyage' else
        (bounds[stage] + 4) // 5 + (output * 6 + 4) // 5 if provider == 'openai' else
        bounds[stage] * 2 + output * 10
        for stage, (provider, _, output) in STAGES.items() if stage != 'check')
    return {'authorization_id': existing.AUTHORIZATION_ID, 'run_id': os.environ['GITHUB_RUN_ID'],
        'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'job_id': job['job_id'], 'iteration2_release': plan()['release_id'],
        'iteration2_authority': VERSION, 'plan_sha256': identity(plan()),
        'input_sha256': plan()['source_inputs_sha256'], 'prior_ledger_sha256': existing.sha(ledger.path.read_bytes()),
        'maximum_logical_spend_usd': 60, 'original_additional_allowance': p['additional'],
        'remaining_completion_allowance': balance, 'protected': p['protected'],
        'aggregate_unknown_exposure': exposure(state),
        'maximum_new_microusd': maximum, 'no_second_allowance': True,
        'maximum_new_metered_attempts': 4, 'maximum_new_native_counts': 1,
        'provider_routes': ['openai', 'voyage', 'anthropic'], 'automatic_retries': 0,
        'public_activation': False, 'recurring_paid_usage': False}
