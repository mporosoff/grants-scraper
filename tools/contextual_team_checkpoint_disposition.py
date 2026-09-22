"""Exact aggregate exposure for one lost checkpoint, never fabricated usage.

The trusted recovery lifecycle authenticates source artifacts and installs this
event. This module only validates its immutable identity and applies the hold.
"""
import json
from pathlib import Path
import re

from tools.offline_spend import ConfigurationFailure, Deferred, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'iteration2-missing-checkpoint-disposition-20260922-v1'
KIND = 'exact_lost_checkpoint_exposure_held'
OWNER = 'on-demand-team-offline-v2-20260909'
ZERO = {'microusd': 0, 'attempts': 0, 'native_counts': 0}


def plan():
    value = json.loads((ROOT/'config/contextual_team/iteration2-checkpoint-disposition-v1.json').read_bytes())
    prior, failed, hold = value['prior'], value['failed'], value['hold']
    reservation = failed['reservation']
    if (value.get('version') != VERSION or value.get('authorization_id') != OWNER
            or hold != {'microusd': 713400, 'attempts': 4, 'native_counts': 1}
            or any(type(v) is not int for v in hold.values())
            or value.get('closed_scope_id') != '341997' or failed['scope_id'] != '341997'
            or failed['run']['id'] != 35655451108 or prior['run']['id'] != 35654812312
            or value.get('no_second_allowance') is not True
            or value.get('public_activation') is not False or value.get('recurring_paid_usage') is not False
            or identity(reservation) != failed['reservation_identity']
            or failed['job_id'] != identity([failed['release_id'], failed['scope_id'], ''])
            or reservation['job_id'] != failed['job_id']
            or reservation['prior_ledger_sha256'] != prior['ledger_sha256']
            or reservation['authorization_id'] != OWNER
            or reservation['iteration2_release'] != failed['release_id']
            or reservation['code_sha'] != failed['run']['head_sha']
            or reservation['run_id'] != str(failed['run']['id'])
            or reservation['attempt'] != str(failed['run']['run_attempt'])
            or (reservation['maximum_new_microusd'], reservation['maximum_new_metered_attempts'],
                reservation['maximum_new_native_counts']) != (hold['microusd'], hold['attempts'], hold['native_counts'])):
        raise ConfigurationFailure('checkpoint_disposition_exact_plan_identity')
    return value


def event():
    p = plan()
    return {'kind': KIND, 'authority': VERSION, 'plan_sha256': identity(p),
        'spending_owner': OWNER, 'prior_ledger_sha256': p['prior']['ledger_sha256'],
        'prior_checkpoint_sha256': p['prior']['checkpoint_sha256'],
        'failed_run_id': p['failed']['run']['id'], 'failed_artifact': p['failed']['artifact'],
        'failed_reservation_sha256': p['failed']['reservation_sha256'],
        'job_id': p['failed']['job_id'], 'scope_id': p['closed_scope_id'],
        'exposure': p['hold'], 'usage': 'unknown', 'provider_allocation': 'unknown',
        'replay': 'permanently_closed', 'actual_requests_reconstructed': False,
        'actual_native_counts_reconstructed': False, 'scientific_result_recovered': False,
        'additional_allowance': 0, 'no_second_allowance': True}


def _closed(purpose):
    # This disposition has one fixed scope, independent of contract/release.
    return isinstance(purpose, str) and re.match(r'^cb-fc-i[0-9]+-341997:', purpose) is not None


def validate(state, require=False):
    """Validate a singleton event and its complete original ledger prefixes."""
    events = state.get('events', [])
    installed = [e for e in events if e.get('authority') == VERSION or e.get('kind') == KIND]
    if not installed and not require:
        return False
    p = plan(); prior = p['prior']; expected = event()
    if (identity(installed) != identity([expected]) or state.get('logical_id') != OWNER
            or len(events) <= prior['events'] or identity(events[prior['events']]) != identity(expected)
            or identity(events[:prior['events']]) != prior['events_sha256']
            or len(state['requests']) < prior['requests']
            or identity(state['requests'][:prior['requests']]) != prior['requests_sha256']):
        raise ConfigurationFailure('checkpoint_disposition_history_or_event_conflict')
    if (any(_closed(r.get('purpose')) for r in state['requests'][prior['requests']:])
            or any(_closed(e.get('purpose')) for e in events[prior['events'] + 1:])):
        raise ConfigurationFailure('checkpoint_disposition_closed_scope_claimed')
    return True


def exposure(state):
    return dict(plan()['hold']) if validate(state) else dict(ZERO)


def assert_operation_open(state, purpose):
    if validate(state) and _closed(purpose):
        raise Deferred('checkpoint_disposition_scope_permanently_closed_no_replay')


def validate_counts(state, rows):
    if not validate(state):
        return
    prior = plan()['prior']
    if (len(rows) < prior['native_counts']
            or identity(rows[:prior['native_counts']]) != prior['native_counts_sha256']
            or any(_closed(r.get('id')) for r in rows[prior['native_counts']:])):
        raise ConfigurationFailure('checkpoint_disposition_native_history_or_closed_scope')
