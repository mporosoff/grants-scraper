"""One capacity-only amendment in the existing completion ledger; no inference."""
import copy
import json
import os
from pathlib import Path

from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-iteration3-capacity-20260922-v1'
KIND = 'completion_request_capacity_amended'
SELECTOR = {'iteration3_capacity': 'install'}


def plan():
    from tools.contextual_team_completion_policy import plan as original_plan
    value = json.loads((ROOT/'config/contextual_team/iteration3-capacity-amendment-v1.json').read_bytes())
    original = original_plan()
    if (value.get('version') != VERSION or value.get('authorization_id') != original['authorization_id']
            or value.get('original_completion_authority_sha256') != identity(original)
            or value.get('original_starting_checkpoint') != original['starting_checkpoint']
            or value.get('previous_lifetime') != original['lifetime']
            or value.get('previous_additional') != original['additional']
            or value.get('protected') != original['protected']
            or value.get('lifetime') != {'microusd': 60000000, 'attempts': 1490, 'native_counts': 590}
            or value.get('additional') != {'microusd': 50000000, 'attempts': 800, 'native_counts': 400}
            or value.get('increment') != {'microusd': 0, 'attempts': 200, 'native_counts': 100}
            or value.get('no_second_owner') is not True or value.get('no_reset') is not True
            or value.get('public_activation') is not False or value.get('recurring_paid_usage') is not False):
        raise ConfigurationFailure('iteration3_capacity_authority_identity')
    return value


def event():
    p = plan()
    return {'kind': KIND, 'authority': VERSION, 'plan_sha256': identity(p),
        'spending_owner': p['authorization_id'], 'source': p['source'],
        'original_starting_checkpoint': p['original_starting_checkpoint'],
        'previous_lifetime': p['previous_lifetime'], 'previous_additional': p['previous_additional'],
        'lifetime': p['lifetime'], 'additional': p['additional'], 'increment': p['increment'],
        'protected': p['protected'], 'no_reset': True, 'no_second_owner': True,
        'public_activation': False, 'recurring_paid_usage': False}


def validate(state, require=False):
    events = state.get('events', [])
    installed = [row for row in events if row.get('authority') == VERSION or row.get('kind') == KIND]
    if not installed and not require:
        return False
    p = plan(); source = p['source']
    if (identity(installed) != identity([event()]) or state.get('logical_id') != p['authorization_id']
            or len(events) <= source['events'] or identity(events[source['events']]) != identity(event())
            or identity(events[:source['events']]) != source['events_sha256']
            or len(state['requests']) < source['requests']
            or identity(state['requests'][:source['requests']]) != source['requests_sha256']):
        raise ConfigurationFailure('iteration3_capacity_history_or_event_conflict')
    return True


def effective_plan(state, original):
    value = copy.deepcopy(original)
    if validate(state):
        p = plan()
        value.update(lifetime=p['lifetime'], additional=p['additional'])
    return value


def validate_counts(state, rows):
    if validate(state):
        source = plan()['source']
        if (len(rows) < source['native_counts']
                or identity(rows[:source['native_counts']]) != source['native_counts_sha256']):
            raise ConfigurationFailure('iteration3_capacity_native_history_changed')


def _authenticate(api_call):
    p = plan(); source = p['source']
    run = json.loads(api_call('actions/runs/'+str(source['run']['id'])))
    if any(run.get(k) != v for k, v in source['run'].items()):
        raise Deferred('iteration3_capacity_source_owner_not_terminal')
    artifact = json.loads(api_call('actions/artifacts/'+str(source['artifact']['id'])))
    if (any(artifact.get(k) != v for k, v in source['artifact'].items())
            or artifact.get('expired') is not False
            or artifact.get('workflow_run', {}).get('id') != source['run']['id']
            or artifact.get('workflow_run', {}).get('head_sha') != source['run']['head_sha']):
        raise Deferred('iteration3_capacity_source_artifact_identity')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))
    if (active.get('total_count', len(active['workflow_runs'])) > 100
            or any(str(row['id']) != os.environ['GITHUB_RUN_ID'] for row in active['workflow_runs'])):
        raise Deferred('iteration3_capacity_another_owner_active')


def install(state_path, api_call, crash=lambda point: None):
    """Bind exact historical bytes; append the event and caps in one atomic write."""
    from tools import team_recommender_executor as existing
    from tools import contextual_team_completion_policy as pool
    state_path = Path(state_path); p = plan(); source = p['source']
    _authenticate(api_call)
    ledger = existing.ExperimentLedger(state_path/'ledger.json')
    with ledger.locked():
        state = ledger.read(); pool.history(state)
        checkpoint_raw = (state_path/'checkpoint.json').read_bytes()
        checkpoint = json.loads(checkpoint_raw)
        rows = checkpoint['phase2_token_preflight']['rows']
        actual = {f.relative_to(state_path).as_posix(): existing.sha(f.read_bytes())
            for f in state_path.rglob('*.json') if f.name != 'checkpoint.json'}
        if not validate(state):
            if (existing.sha(ledger.path.read_bytes()) != source['ledger_sha256']
                    or existing.sha(checkpoint_raw) != source['checkpoint_sha256']
                    or len(state['requests']) != source['requests'] or len(state['events']) != source['events']
                    or len(rows) != source['native_counts'] or identity(rows) != source['native_counts_sha256']
                    or actual != checkpoint['files'] or len(actual) != source['checkpoint_files']
                    or identity(actual) != source['checkpoint_files_sha256']):
                raise ConfigurationFailure('iteration3_capacity_exact_starting_checkpoint_required')
            state['events'].append(event())
            state.update(limit_microusd=p['lifetime']['microusd'], max_requests=p['lifetime']['attempts'])
            pool.history(state); validate_counts(state, rows)
            try:
                crash('before_atomic_write')
                atomic_json(ledger.path, state)
                crash('after_atomic_write')
            finally:
                # Only materialize a new checkpoint after the event is durable.
                if validate(json.loads(ledger.path.read_bytes())):
                    existing.checkpoint(state_path)
        else:
            validate_counts(state, rows)
            # A process kill between the ledger swap and checkpoint swap may
            # leave precisely the original checkpoint. No other mismatch is
            # repaired by rehashing files into a fresh checkpoint.
            interrupted = (existing.sha(checkpoint_raw) == source['checkpoint_sha256']
                and len(state['requests']) == source['requests']
                and len(state['events']) == source['events'] + 1
                and actual == (checkpoint['files'] | {'ledger.json': actual['ledger.json']}))
            if actual != checkpoint['files'] and not interrupted:
                raise ConfigurationFailure('iteration3_capacity_checkpoint_files_changed')
            existing.checkpoint(state_path)
        pool.history(ledger.read())
    return ledger


def reservation_record():
    from tools import team_recommender_executor as existing
    return {'authorization_id': existing.AUTHORIZATION_ID, 'operation': VERSION,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha': os.environ['GITHUB_SHA'], 'plan_sha256': identity(plan()),
        'prior_ledger_sha256': plan()['source']['ledger_sha256'],
        'maximum_new_microusd': 0, 'maximum_new_metered_attempts': 0, 'maximum_new_native_counts': 0}


def run(args):
    from tools import team_recommender_executor as existing
    from tools.contextual_team_iteration2_policy import remaining
    existing.trusted_environment()
    if (json.loads(os.environ['CONTEXTUAL_CHECK']) != SELECTOR
            or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'))):
        raise ConfigurationFailure('iteration3_capacity_exact_selector')
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy())
        install(args.state, existing.api)
        atomic_json(args.reservation, reservation_record())
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('text_provider=none\n')
        return
    if json.loads(args.reservation.read_bytes()) != reservation_record():
        raise ConfigurationFailure('iteration3_capacity_prepared_identity_changed')
    ledger = existing.ExperimentLedger(args.state/'ledger.json'); state = ledger.read()
    validate(state, require=True)
    balance = remaining(state, args.state)
    atomic_json(args.result, {'version': VERSION, 'status': 'capacity_amendment_installed',
        'plan_sha256': identity(plan()), 'event_sha256': identity(event()),
        'remaining_completion': balance, 'lifetime': plan()['lifetime'], 'additional': plan()['additional'],
        'new_microusd': 0, 'new_metered_attempts': 0, 'new_native_count_calls': 0,
        'historical_results_changed': False, 'unknown_holds_released': False,
        'public_activation': False, 'recurring_paid_usage': False})
    existing.checkpoint(args.state)
