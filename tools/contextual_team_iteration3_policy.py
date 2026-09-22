"""Nine exact corrective operations under the existing completion allowance.

This grants scope, never money, retries, new embeddings, or public activation.
The original failed requests and all earlier accounting remain immutable.
"""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from tools import contextual_team_completion_policy as pool
from tools import contextual_team_iteration3_capacity as capacity
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-iteration3-correction-20260922-v1'
PREFIX = 'cb-fc-i3-'
STAGES = {'assess': ('openai', 'gpt-5.6-luna', 24000),
          'verify': ('anthropic', 'claude-sonnet-5', 24000),
          'integrity': ('anthropic', 'claude-sonnet-5', 12000),
          'check': ('anthropic', 'claude-sonnet-5', 12000)}
BUILD_STAGES = {'332894': ('integrity',), '345241:tdac-baa-004': ('integrity',),
                '363268': ('assess', 'verify', 'integrity')}
SCOPE_IDS = ('363268', '332894', '345241:tdac-baa-004', '344592:ab-0025')
REPAIRS = {PREFIX+'363268:assess': 'cb-fc-i2-363268:assess',
           PREFIX+'344592:ab-0025:check': 'cb-fc-i2-344592:ab-0025:check'}


def expected_operations():
    return [{'scope_id': scope, 'stage': stage, 'purpose': PREFIX+scope+':'+stage,
             'provider': STAGES[stage][0], 'model': STAGES[stage][1], 'output_tokens': STAGES[stage][2]}
            for scope in SCOPE_IDS for stage in (*BUILD_STAGES.get(scope, ()), 'check')]


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def plan():
    p = json.loads((ROOT/'config/contextual_team/iteration3-authority-v1.json').read_bytes())
    if (p.get('version') != VERSION or p.get('authorization_id') != existing.AUTHORIZATION_ID
            or p.get('release_id') != identity({k: v for k, v in p.items() if k != 'release_id'})
            or any(p.get(k) is not False for k in ('public_activation', 'recurring_paid_usage', 'paid_builds_enabled'))
            or p.get('no_second_allowance') is not True):
        raise ConfigurationFailure('iteration3_authority_identity')
    if (p.get('scope_ids') != list(SCOPE_IDS) or p.get('build_scope_ids') != list(BUILD_STAGES)
            or p.get('first_scope_id') != '332894'
            or identity(p.get('operations')) != identity(expected_operations())
            or identity(p.get('stages')) != identity({k: {'provider': v[0], 'model': v[1], 'output_tokens': v[2]} for k, v in STAGES.items()})
            or identity(p.get('input_token_ceilings')) != identity({stage: 180000 for stage in STAGES})
            or type(p.get('max_requests')) is not int or p['max_requests'] != 9
            or type(p.get('max_native_counts')) is not int or p['max_native_counts'] != 8
            or p.get('maximum_wire_bytes') != 524288 or p.get('maximum_graph_bytes') != 393216
            or set(p.get('repairs', {})) != set(REPAIRS)):
        raise ConfigurationFailure('iteration3_fixed_corrective_inventory')
    start = p['starting_checkpoint']
    if (identity([start.get(k) for k in ('requests', 'native_counts', 'events')]) != identity([718, 200, 56])
            or any(not _sha(start.get(k)) for k in ('requests_sha256', 'native_counts_sha256', 'events_sha256',
                    'ledger_sha256', 'checkpoint_sha256', 'checkpoint_files_sha256'))):
        raise ConfigurationFailure('iteration3_fixed_starting_checkpoint')
    for filename, key in (('iteration3-source-inputs-v1.json', 'source_inputs_sha256'),
                          ('iteration3-source-receipts-v1.json', 'source_receipts_sha256')):
        if existing.sha((ROOT/'config/contextual_team'/filename).read_bytes()) != p.get(key):
            raise ConfigurationFailure('iteration3_source_or_receipt_manifest_changed')
    for repair in p['repairs'].values():
        if (set(repair) != {'request_id', 'request_sha256', 'body_sha256', 'receipt_sha256', 'diagnostic_sha256'}
                or not isinstance(repair['request_id'], str) or not repair['request_id']
                or any(not _sha(v) for k, v in repair.items() if k != 'request_id')):
            raise ConfigurationFailure('iteration3_original_failure_lock')
    return p


def event():
    p = plan()
    return {'kind': 'iteration3_execution_scope', 'authority': VERSION,
        'release_id': p['release_id'], 'plan_sha256': identity(p),
        'starting_checkpoint': p['starting_checkpoint'], 'operations': p['operations'],
        'spending_owner': existing.AUTHORIZATION_ID, 'additional_allowance': 0,
        'no_second_allowance': True, 'public_activation': False, 'recurring_paid_usage': False}


def operation(scope_id, stage):
    purpose = PREFIX + str(scope_id) + ':' + str(stage)
    if not any(row['purpose'] == purpose for row in plan()['operations']):
        raise ConfigurationFailure('iteration3_unapproved_scope_or_stage')
    return purpose


def _stage(purpose):
    if not isinstance(purpose, str) or not purpose.startswith(PREFIX) or ':' not in purpose[len(PREFIX):]:
        raise ConfigurationFailure('iteration3_unapproved_operation')
    scope, stage = purpose[len(PREFIX):].rsplit(':', 1)
    operation(scope, stage)
    return scope, stage


def _repair(purpose):
    return plan()['repairs'].get(purpose, {}).get('request_id')


def _operation_events(state):
    return [row for row in state['events'] if row.get('authority') == VERSION and row.get('kind') == 'iteration3_exact_operation']


def history(state, require_authority=True):
    pool.history(state); capacity.validate(state, require=True)
    p = plan(); start = p['starting_checkpoint']; requests = state['requests']; events = state['events']
    if (len(requests) < start['requests'] or len(events) < start['events']
            or identity(requests[:start['requests']]) != start['requests_sha256']
            or identity(events[:start['events']]) != start['events_sha256']):
        raise ConfigurationFailure('iteration3_original_history_changed')
    installed = [e for e in events if e.get('authority') == VERSION]
    authorities = [e for e in installed if e.get('kind') == 'iteration3_execution_scope']
    if ((require_authority or installed) and identity(authorities) != identity([event()])):
        raise ConfigurationFailure('iteration3_exact_authority_required')
    if authorities and identity(events[start['events']]) != identity(event()):
        raise ConfigurationFailure('iteration3_authority_position_changed')
    seen = {}
    for row in installed:
        if row.get('kind') == 'iteration3_execution_scope':
            continue
        if (row.get('kind') != 'iteration3_exact_operation' or set(row) != {
                'kind', 'authority', 'purpose', 'provider', 'model', 'body_sha256', 'input_sha256',
                'contract_sha256', 'contract_version', 'output_tokens', 'plan_sha256', 'count_body_sha256', 'repair_of'}):
            raise ConfigurationFailure('iteration3_operation_event_shape')
        _, stage = _stage(row['purpose']); provider, model, output = STAGES[stage]
        if (row['purpose'] in seen or row['provider'] != provider or row['model'] != model
                or type(row['output_tokens']) is not int or row['output_tokens'] != output
                or row['plan_sha256'] != identity(p) or row['repair_of'] != _repair(row['purpose'])
                or any(not _sha(row[k]) for k in ('body_sha256', 'input_sha256', 'contract_sha256'))
                or not isinstance(row['contract_version'], str) or not row['contract_version']
                or (not _sha(row['count_body_sha256']) if provider == 'anthropic' else row['count_body_sha256'] is not None)):
            raise ConfigurationFailure('iteration3_operation_event_identity')
        repair = p['repairs'].get(row['purpose'])
        if repair and row['body_sha256'] == repair['body_sha256']:
            raise Deferred('iteration3_unchanged_failed_body_no_replay')
        seen[row['purpose']] = row
    for purpose, repair in p['repairs'].items():
        original = [r for r in requests[:start['requests']] if r['id'] == repair['request_id']]
        if (len(original) != 1 or identity(original[0]) != repair['request_sha256']
                or original[0].get('purpose') != REPAIRS[purpose] or original[0].get('status') != 'failed'
                or original[0].get('body_sha256') != repair['body_sha256']
                or type(original[0].get('charged_microusd')) is not int or original[0]['charged_microusd'] <= 0):
            raise ConfigurationFailure('iteration3_original_failed_request_changed')
    claimed = set()
    for index, row in enumerate(requests):
        if row.get('status') == 'reserved_unknown' and (index >= start['requests'] or row['id'] not in pool.HISTORICAL_UNKNOWN_IDS):
            raise Deferred('iteration3_new_uncertainty_requires_recovery')
        if index < start['requests']:
            continue
        purpose = row.get('purpose'); locked = seen.get(purpose)
        if not locked or purpose in claimed:
            raise ConfigurationFailure('iteration3_request_without_unique_operation')
        checks = {'provider': locked['provider'], 'model': locked['model'], 'body_sha256': locked['body_sha256'],
            'completion_authority': VERSION, 'completion_lock_sha256': identity(p),
            'completion_transport': locked['contract_version'], 'pair_contract_sha256': locked['contract_sha256'],
            'repair_of': locked['repair_of'], 'packet_sha256': p['source_inputs_sha256'], 'execution_capacity': VERSION}
        if any(row.get(k) != v for k, v in checks.items()):
            raise ConfigurationFailure('iteration3_request_lock_changed')
        claimed.add(purpose)


def check_counts(state_path):
    from tools.contextual_team_token_preflight import VERSION as count_version, SOURCE_SHA
    state_path = Path(state_path); cp = json.loads((state_path/'checkpoint.json').read_bytes())
    state = json.loads((state_path/'ledger.json').read_bytes())
    history(state, require_authority=False)
    saved = cp['phase2_token_preflight']; rows = saved['rows']; p = plan(); start = p['starting_checkpoint']
    if (cp.get('authorization_id') != existing.AUTHORIZATION_ID or saved.get('version') != count_version
            or saved.get('source_sha256') != SOURCE_SHA or len(rows) < start['native_counts']
            or identity(rows[:start['native_counts']]) != start['native_counts_sha256']):
        raise ConfigurationFailure('iteration3_original_native_counts_changed')
    capacity.validate_counts(state, rows)
    from tools.contextual_team_checkpoint_disposition import validate_counts
    validate_counts(state, rows)
    locked = {e['purpose']: e for e in _operation_events(state)}; seen = set()
    for row in rows[start['native_counts']:]:
        if row.get('status') != 'complete':
            raise Deferred('iteration3_native_uncertainty_no_continuation')
        e = locked.get(row.get('id'))
        if (not e or e['provider'] != 'anthropic' or row['id'] in seen or row.get('key') != e['count_body_sha256']
                or type(row.get('input_tokens')) is not int or not 0 < row['input_tokens'] <= 200000
                or row.get('metered_inference') is not False or type(row.get('charged_microusd')) is not int
                or row['charged_microusd'] != 0):
            raise ConfigurationFailure('iteration3_native_count_operation_identity')
        seen.add(row['id'])
    if len(rows) - start['native_counts'] > p['max_native_counts']:
        raise Deferred('iteration3_finite_native_count_inventory')
    return rows


def check_native_request(state_path, item, *, claim=False):
    """Guard the native endpoint itself, including direct cached-count calls."""
    from tools.contextual_team_token_preflight import count_projection
    state = json.loads((Path(state_path)/'ledger.json').read_bytes())
    history(state); rows = check_counts(state_path)
    purpose = item.get('id'); scope, _ = _stage(purpose)
    key = identity(count_projection(item['body']))
    bound = [e for e in _operation_events(state) if e['purpose'] == purpose]
    if len(bound) != 1 or bound[0]['provider'] != 'anthropic' or bound[0]['count_body_sha256'] != key:
        raise ConfigurationFailure('iteration3_native_exact_bound_operation_required')
    if claim:
        if any(r.get('purpose') == purpose for r in state['requests']):
            raise Deferred('iteration3_paid_operation_claimed_no_new_count')
        if any(r.get('key') == key for r in rows):
            raise Deferred('iteration3_native_count_already_claimed_no_repeat')
        source_currentness(scope)
        finite_envelope(state, rows)


def _evidence(state_path):
    for repair in plan()['repairs'].values():
        for folder, key in (('receipts', 'receipt_sha256'), ('diagnostics', 'diagnostic_sha256')):
            if existing.sha((Path(state_path)/folder/(repair['request_id']+'.json')).read_bytes()) != repair[key]:
                raise ConfigurationFailure('iteration3_original_failed_evidence_changed')


def source_currentness(scope_id, now=None):
    """Fresh, exact named-source correspondence, separate from saved science."""
    from tools.contextual_team_executor import scope_inputs
    p = plan(); operation(scope_id, 'check')
    directory = ROOT/'config/contextual_team'
    receipts = json.loads((directory/'iteration3-source-receipts-v1.json').read_bytes())
    original_raw = (directory/'iteration2-source-inputs-v1.json').read_bytes()
    source = json.loads((directory/'iteration3-source-inputs-v1.json').read_bytes())
    if (existing.sha(original_raw) != receipts.get('original_source_inputs_sha256')
            or source.get('original_source_inputs_sha256') != receipts['original_source_inputs_sha256']
            or receipts.get('new_scientific_generation') is not False or receipts.get('public_activation') is not False):
        raise ConfigurationFailure('iteration3_currentness_original_source_changed')
    matches = [r for r in receipts['scope_receipts'] if r.get('scope_id') == scope_id]
    originals = [s for s in json.loads(original_raw)['scopes'] if s['id'] == scope_id]
    if len(matches) != 1 or len(originals) != 1:
        raise ConfigurationFailure('iteration3_exact_source_receipt_required')
    receipt = matches[0]; original = originals[0]
    if (receipt.get('source_id') != original['source_id'] or original['source_id'] != identity(scope_inputs(original))
            or receipt.get('original_scientific_input_preserved') is not True
            or receipt.get('catalog_api_identity_matches') is not True or receipt.get('official_status') != 'posted'):
        raise ConfigurationFailure('iteration3_source_correspondence_identity')
    if scope_id in p['build_scope_ids']:
        scopes = [s for s in source['scopes'] if s['id'] == scope_id]
        if (len(scopes) != 1 or identity(scope_inputs(scopes[0])) != original['source_id']
                or identity(scopes[0].get('iteration3_currentness_receipt')) != identity(receipt)
                or scopes[0].get('currentness', {}).get('not_after') != receipt.get('source_currentness_expires_at')):
            raise ConfigurationFailure('iteration3_scope_currentness_receipt_changed')
    try:
        clock = datetime.now(timezone.utc) if now is None else now
        observed = datetime.fromisoformat(receipt['observed_at'].replace('Z', '+00:00'))
        expiry = datetime.fromisoformat(receipt['source_currentness_expires_at'].replace('Z', '+00:00'))
        correspondence = datetime.fromisoformat(receipt.get('correspondence_observed_at', receipt['observed_at']).replace('Z', '+00:00'))
        if any(value.tzinfo is None for value in (clock, observed, expiry, correspondence)):
            raise ValueError('timezone required')
        current = observed <= clock and correspondence <= clock < expiry
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ConfigurationFailure('iteration3_source_currentness_clock') from exc
    if not current:
        raise Deferred('iteration3_source_receipt_expired_or_not_yet_observed')
    return receipt


def install_authority(state_path, api_call, crash=lambda point: None):
    state_path = Path(state_path); p = plan(); start = p['starting_checkpoint']
    run = json.loads(api_call('actions/runs/'+str(start['run']['id'])))
    if any(run.get(k) != v for k, v in start['run'].items()):
        raise Deferred('iteration3_starting_owner_not_terminal')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))
    if (active.get('total_count', len(active['workflow_runs'])) > 100
            or any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active['workflow_runs'])):
        raise Deferred('iteration3_another_spending_owner_active')
    ledger = existing.ExperimentLedger(state_path/'ledger.json')
    with ledger.locked():
        state = ledger.read(); history(state, require_authority=False); check_counts(state_path); _evidence(state_path)
        cp_raw = (state_path/'checkpoint.json').read_bytes(); cp = json.loads(cp_raw)
        actual = {f.relative_to(state_path).as_posix(): existing.sha(f.read_bytes())
            for f in state_path.rglob('*.json') if f.name != 'checkpoint.json'}
        if not any(e.get('authority') == VERSION for e in state['events']):
            if (existing.sha(ledger.path.read_bytes()) != start['ledger_sha256']
                    or existing.sha(cp_raw) != start['checkpoint_sha256'] or actual != cp['files']
                    or len(actual) != start['checkpoint_files'] or identity(actual) != start['checkpoint_files_sha256']):
                raise ConfigurationFailure('iteration3_exact_starting_checkpoint_required')
            state['events'].append(event()); history(state); pool.check_pool(state)
            crash('before_atomic_write'); atomic_json(ledger.path, state)
            crash('after_atomic_write')
        else:
            interrupted = (existing.sha(cp_raw) == start['checkpoint_sha256']
                and len(state['requests']) == start['requests'] and len(state['events']) == start['events'] + 1
                and actual == (cp['files'] | {'ledger.json': actual['ledger.json']}))
            if actual != cp['files'] and not interrupted:
                raise ConfigurationFailure('iteration3_checkpoint_files_changed')
        existing.checkpoint(state_path)
    return ledger


def packet_event(purpose, body, contract, input_id):
    from tools.contextual_team_token_preflight import count_projection
    _, stage = _stage(purpose); provider, model, output = STAGES[stage]
    if (body.get('model') != model or type(body.get('max_tokens', body.get('max_output_tokens'))) is not int
            or body.get('max_tokens', body.get('max_output_tokens')) != output
            or (body.get('thinking') != {'type': 'disabled'} if provider == 'anthropic' else body.get('reasoning') != {'effort': 'low'})):
        raise ConfigurationFailure('iteration3_exact_model_or_capacity')
    if not _sha(input_id) or not isinstance(contract.get('version'), str) or not contract['version']:
        raise ConfigurationFailure('iteration3_exact_contract_or_input')
    if len(encoded(body)) > plan()['maximum_wire_bytes']:
        raise Deferred('iteration3_complete_wire_bound_no_truncation')
    repair = plan()['repairs'].get(purpose)
    if repair and identity(body) == repair['body_sha256']:
        raise Deferred('iteration3_unchanged_failed_body_no_replay')
    return {'kind': 'iteration3_exact_operation', 'authority': VERSION, 'purpose': purpose,
        'provider': provider, 'model': model, 'body_sha256': identity(body), 'input_sha256': input_id,
        'contract_sha256': identity(contract), 'contract_version': contract['version'], 'output_tokens': output,
        'plan_sha256': identity(plan()), 'count_body_sha256': identity(count_projection(body)) if provider == 'anthropic' else None,
        'repair_of': _repair(purpose)}


def _metadata(e):
    return {'completion_authority': VERSION, 'completion_lock_sha256': identity(plan()),
        'completion_transport': e['contract_version'], 'pair_contract_sha256': e['contract_sha256'],
        'repair_of': e['repair_of'], 'packet_sha256': plan()['source_inputs_sha256'], 'execution_capacity': VERSION}


def bind_operation(ledger, purpose, body, contract, input_id):
    expected = packet_event(purpose, body, contract, input_id)
    with ledger.locked():
        state = ledger.read(); history(state); check_counts(ledger.path.parent); _evidence(ledger.path.parent)
        from tools.contextual_team_checkpoint_disposition import assert_operation_open
        assert_operation_open(state, purpose)
        if not any(r.get('purpose') == purpose for r in state['requests']):
            source_currentness(_stage(purpose)[0])
            finite_envelope(state, check_counts(ledger.path.parent))
        saved = [e for e in _operation_events(state) if e['purpose'] == purpose]
        if saved and identity(saved) != identity([expected]):
            raise Deferred('iteration3_operation_changed_no_rekey')
        if not saved:
            state['events'].append(expected); atomic_json(ledger.path, state)
        existing.checkpoint(ledger.path.parent)
    return _metadata(expected)


def _amount(provider, inputs, outputs):
    return inputs * 2 + outputs * 10 if provider == 'anthropic' else (inputs + 4) // 5 + (outputs * 6 + 4) // 5


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    history(state); purpose = metadata.get('purpose'); _, stage = _stage(purpose)
    from tools.contextual_team_checkpoint_disposition import assert_operation_open
    assert_operation_open(state, purpose)
    saved = [e for e in _operation_events(state) if e['purpose'] == purpose]
    if len(saved) != 1:
        raise ConfigurationFailure('iteration3_exact_packet_not_predeclared')
    e = saved[0]; locked = _metadata(e) | {'body_sha256': e['body_sha256']}
    if (any(metadata.get(k) != v for k, v in locked.items()) or provider != e['provider']
            or type(output_tokens) is not int or output_tokens != e['output_tokens']):
        raise ConfigurationFailure('iteration3_reservation_packet_identity')
    if any(r.get('purpose') == purpose for r in state['requests']):
        raise Deferred('iteration3_operation_already_claimed_no_rekey')
    source_currentness(_stage(purpose)[0])
    if type(input_tokens) is not int or not 0 < input_tokens <= plan()['input_token_ceilings'][stage]:
        raise Deferred('iteration3_complete_input_bound_no_truncation')
    if provider == 'anthropic':
        native = metadata.get('native_input_tokens')
        if (type(native) is not int or native <= 0 or input_tokens != math.ceil(native * 1.2) + 1024
                or metadata.get('native_count_key') != e['count_body_sha256']
                or metadata.get('count_body_sha256') != e['count_body_sha256']):
            raise ConfigurationFailure('iteration3_exact_native_count_required')
    if type(amount) is not int or amount != _amount(provider, input_tokens, output_tokens):
        raise ConfigurationFailure('iteration3_exact_conservative_reservation')
    pool.check_pool(state, amount, 1)


def remaining(state, state_path):
    history(state); counts = check_counts(state_path); pool.check_pool(state)
    from tools.contextual_team_checkpoint_disposition import exposure
    held = exposure(state); p = pool.effective_plan(state); start = p['starting_checkpoint']
    result = {'microusd': p['additional']['microusd'] - sum(r['charged_microusd'] for r in state['requests'][start['requests']:]) - held['microusd'],
        'attempts': p['additional']['attempts'] - (len(state['requests']) - start['requests']) - held['attempts'],
        'native_counts': p['additional']['native_counts'] - (len(counts) - start['native_counts']) - held['native_counts']}
    if len(counts) + held['native_counts'] > p['lifetime']['native_counts'] or result['native_counts'] < 0:
        raise Deferred('iteration3_native_capacity_exhausted')
    return result


def workflow_stages(job):
    scope = job['scope_id']; mode = job.get('operation', 'build')
    if mode == 'check':
        operation(scope, 'check'); return ('check',)
    if mode != 'build' or scope not in BUILD_STAGES:
        raise ConfigurationFailure('iteration3_unapproved_workflow')
    return BUILD_STAGES[scope]


def finite_envelope(state, counts):
    """Complete remaining finite inventory, never sampled independent checks."""
    p = plan(); effective = pool.effective_plan(state)
    from tools.contextual_team_checkpoint_disposition import exposure
    held = exposure(state)
    claimed = {r.get('purpose') for r in state['requests']}
    counted = {r.get('id') for r in counts}
    remaining_ops = [o for o in p['operations'] if o['purpose'] not in claimed]
    amount = sum(_amount(o['provider'], p['input_token_ceilings'][o['stage']], o['output_tokens']) for o in remaining_ops)
    native = sum(o['provider'] == 'anthropic' and o['purpose'] not in counted for o in remaining_ops)
    pool.check_pool(state, amount, len(remaining_ops))
    if (len(counts) + held['native_counts'] + native > effective['lifetime']['native_counts']
            or len(counts) - effective['starting_checkpoint']['native_counts'] + held['native_counts'] + native > effective['additional']['native_counts']
            or len(counts) - p['starting_checkpoint']['native_counts'] + native > p['max_native_counts']):
        raise Deferred('iteration3_complete_inventory_native_capacity')
    return {'microusd': amount, 'attempts': len(remaining_ops), 'native_counts': native,
        'purposes': [o['purpose'] for o in remaining_ops]}


def prepare_record(state_path, job):
    ledger = existing.ExperimentLedger(Path(state_path)/'ledger.json'); state = ledger.read()
    stages = workflow_stages(job); balance = remaining(state, state_path); _evidence(state_path)
    from tools.contextual_team_checkpoint_disposition import assert_operation_open, exposure
    for stage in stages:
        assert_operation_open(state, operation(job['scope_id'], stage))
    if any(not any(r.get('purpose') == operation(job['scope_id'], stage) for r in state['requests']) for stage in stages):
        source_currentness(job['scope_id'])
    p = pool.effective_plan(state); held = exposure(state); counts = check_counts(state_path)
    inventory = finite_envelope(state, counts)
    maximum = sum(_amount(STAGES[stage][0], plan()['input_token_ceilings'][stage], STAGES[stage][2]) for stage in stages)
    native = sum(STAGES[stage][0] == 'anthropic' for stage in stages)
    # Reserve the complete workflow envelope, including stages whose eventual
    # success may permit downstream work. A small first request cannot start a
    # workflow whose complete retained evidence will not fit the remaining pool.
    pool.check_pool(state, maximum, len(stages))
    if (balance['native_counts'] < native or len(counts) + held['native_counts'] + native > p['lifetime']['native_counts']):
        raise Deferred('iteration3_complete_workflow_native_capacity')
    return {'authorization_id': existing.AUTHORIZATION_ID, 'run_id': os.environ['GITHUB_RUN_ID'],
        'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'job_id': job['job_id'], 'scope_id': job['scope_id'], 'operation': job.get('operation', 'build'),
        'iteration3_release': plan()['release_id'], 'iteration3_authority': VERSION, 'plan_sha256': identity(plan()),
        'purposes': [operation(job['scope_id'], stage) for stage in stages],
        'input_sha256': plan()['source_inputs_sha256'], 'prior_ledger_sha256': existing.sha(ledger.path.read_bytes()),
        'maximum_logical_spend_usd': 60, 'original_additional_allowance': p['additional'],
        'remaining_completion_allowance': balance, 'protected': p['protected'], 'aggregate_unknown_exposure': held,
        'remaining_finite_inventory_envelope': inventory,
        'maximum_new_microusd': maximum, 'maximum_new_metered_attempts': len(stages), 'maximum_new_native_counts': native,
        'no_second_allowance': True, 'provider_routes': sorted({STAGES[stage][0] for stage in stages}),
        'automatic_retries': 0, 'public_activation': False, 'recurring_paid_usage': False}
