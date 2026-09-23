"""One exact EC timeout hold disposition; never money or inferred usage."""
import copy
import json
from pathlib import Path

from tools.offline_spend import ConfigurationFailure, Deferred, encoded, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'iteration3-ec-timeout-disposition-20260923-v1'
KIND = 'exact_existing_request_unknown_held'
OWNER = 'on-demand-team-offline-v2-20260909'
REQUEST_ID = '534aba746f3044978f83262b69c1d073'
CLOSED_PURPOSE = 'cb-fc-i3-344592:ab-0025:check'
PLAN_SHA256 = 'cb25680715e6deb37842070b18e502ec07f04a55c52d8d52d8d1c951dadf2785'


def plan():
    value = json.loads((ROOT/'config/contextual_team/iteration3-ec-disposition-v1.json').read_bytes())
    if identity(value) != PLAN_SHA256:
        raise ConfigurationFailure('ec_disposition_exact_plan_identity')
    return value


def event():
    p = plan(); source = p['source']
    return {'kind': KIND, 'authority': VERSION, 'plan_sha256': identity(p),
        'spending_owner': OWNER, 'source_run_id': source['run']['id'],
        'source_artifact': source['artifact'], 'source_ledger_sha256': source['ledger_sha256'],
        'source_checkpoint_sha256': source['checkpoint_sha256'],
        'request_id': source['request_id'], 'request_sha256': source['request_sha256'],
        'request_key': source['request_key'], 'purpose': source['purpose'],
        'provider': 'anthropic', 'held_microusd': p['held_microusd'],
        'hold_location': 'unchanged_original_reserved_unknown_request',
        'usage': 'unknown', 'replay': 'permanently_closed',
        'scientific_result_recovered': False, 'additional_allowance': 0,
        'additional_exposure': {'microusd': 0, 'attempts': 0, 'native_counts': 0},
        'no_second_allowance': True}


def validate_prefix(state):
    """Pin all original rows/events and non-list ledger fields without rewriting."""
    p = plan(); source = p['source']
    requests, events = state.get('requests', []), state.get('events', [])
    if (state.get('logical_id') != OWNER or len(requests) < source['requests']
            or len(events) < source['events']
            or identity(requests[:source['requests']]) != source['requests_sha256']
            or identity(events[:source['events']]) != source['events_sha256']):
        raise ConfigurationFailure('ec_disposition_original_history_changed')
    original = copy.deepcopy(state)
    original['requests'] = requests[:source['requests']]
    original['events'] = events[:source['events']]
    # The authentic source had no provider blocks. Later safety blocks may be
    # added by the ordinary ledger and must remain effective, not prevent saving.
    if not isinstance(state.get('blocked_providers'), dict):
        raise ConfigurationFailure('ec_disposition_provider_blocks_shape')
    original['blocked_providers'] = {}
    import hashlib
    if hashlib.sha256(encoded(original)+b'\n').hexdigest() != source['ledger_sha256']:
        raise ConfigurationFailure('ec_disposition_original_ledger_changed')
    rows = [r for r in requests if r.get('id') == source['request_id']]
    if (len(rows) != 1 or identity(rows[0]) != source['request_sha256']
            or rows[0].get('status') != 'reserved_unknown'
            or rows[0].get('usage') is not None
            or type(rows[0].get('charged_microusd')) is not int
            or rows[0]['charged_microusd'] != p['held_microusd']
            or rows[0].get('reserved_microusd') != p['held_microusd']):
        raise ConfigurationFailure('ec_disposition_full_original_hold_required')


def validate(state, require=False):
    events = state.get('events', [])
    installed = [e for e in events if e.get('authority') == VERSION or e.get('kind') == KIND]
    if not installed and not require:
        return False
    source = plan()['source']; expected = event()
    validate_prefix(state)
    if (identity(installed) != identity([expected]) or len(events) <= source['events']
            or identity(events[source['events']]) != identity(expected)):
        raise ConfigurationFailure('ec_disposition_singleton_event_conflict')
    if any(r.get('purpose') == CLOSED_PURPOSE or r.get('key') == source['request_key']
           for r in state['requests'][source['requests']:]):
        raise ConfigurationFailure('ec_disposition_original_request_replayed')
    if any(e.get('purpose') == CLOSED_PURPOSE for e in events[source['events']+1:]):
        raise ConfigurationFailure('ec_disposition_closed_purpose_rebound')
    return True


def allowed_unknown_ids(state):
    return frozenset((REQUEST_ID,)) if validate(state) else frozenset()


def assert_operation_open(state, purpose, key=None):
    validate(state)
    # This request is already irreversibly claimed in the authentic owner.
    # The separately authorized replacement must use its distinct named purpose.
    if purpose == CLOSED_PURPOSE or key == plan()['source']['request_key']:
        raise Deferred('ec_disposition_original_purpose_permanently_closed_no_replay')


def validate_counts(state, rows):
    if not validate(state):
        return
    source = plan()['source']
    if (len(rows) < source['native_counts']
            or identity(rows[:source['native_counts']]) != source['native_counts_sha256']
            or any(r.get('id') == CLOSED_PURPOSE for r in rows[source['native_counts']:])):
        raise ConfigurationFailure('ec_disposition_original_native_history_changed')
