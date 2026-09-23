"""Trusted exact EC timeout disposition with zero provider or count execution."""
import json
import os
from pathlib import Path
import re
import tempfile

from tools import contextual_team_ec_disposition as disposition
from tools import contextual_team_checkpoint_recovery as trusted
from tools import team_recommender_executor as existing
from tools.team_recommender_checkpoint import created, latest_reservation
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity

VERSION = disposition.VERSION
SELECTOR = {'iteration3_ec_disposition': '344592:ab-0025'}


def selected():
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ConfigurationFailure('ec_disposition_duplicate_selector_key')
            value[key] = item
        return value
    raw = os.environ.get('CONTEXTUAL_CHECK', '')
    try:
        value = json.loads(raw, object_pairs_hook=unique) if raw else None
    except ValueError:
        return False
    if isinstance(value, dict) and 'iteration3_ec_disposition' in value:
        if identity(value) != identity(SELECTOR) or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')):
            raise ConfigurationFailure('ec_disposition_exact_selector')
        return True
    return False


def recovery_key():
    return identity(disposition.event())


def receipt_path(state):
    return Path(state)/'receipts'/(recovery_key()[:32]+'.json')


def _receipt(source_checkpoint):
    return {'version': VERSION, 'event': disposition.event(), 'plan_sha256': identity(disposition.plan()),
        'source_checkpoint': source_checkpoint, 'actual_usage': 'unknown',
        'scientific_result_recovered': False, 'paid_requests_replayed': 0,
        'hold_already_in_original_request': True, 'additional_allowance': 0}


def validate_local(state, *, source_checkpoint=None, require=True, ledger_value=None):
    """Validate complete source lineage, permitting only append-only later owners."""
    state = Path(state); p = disposition.plan(); source = p['source']
    ledger = existing.ExperimentLedger(state/'ledger.json').read() if ledger_value is None else ledger_value
    path = receipt_path(state)
    if source_checkpoint is None:
        if not path.exists():
            if require:
                raise Deferred('ec_disposition_receipt_required')
            return False
        source_checkpoint = json.loads(path.read_bytes())['source_checkpoint']
    if (existing.sha(encoded(source_checkpoint)+b'\n') != source['checkpoint_sha256']
            or source_checkpoint.get('authorization_id') != existing.AUTHORIZATION_ID
            or source_checkpoint['files'].get('ledger.json') != source['ledger_sha256']
            or len(source_checkpoint['files']) != source['checkpoint_files']
            or identity(source_checkpoint['files']) != source['checkpoint_files_sha256']):
        raise ConfigurationFailure('ec_disposition_source_checkpoint_identity')
    disposition.validate_prefix(ledger)
    expected = _receipt(source_checkpoint)
    if path.exists() and path.read_bytes() != encoded(expected)+b'\n':
        raise ConfigurationFailure('ec_disposition_receipt_conflict')
    for name, digest in source_checkpoint['files'].items():
        if name == 'ledger.json':
            continue
        if not re.fullmatch(r'(cache/[a-f0-9]{64}|receipts/[a-f0-9]{32}|diagnostics/[a-f0-9]{32})\.json', name):
            raise ConfigurationFailure('ec_disposition_original_member')
        file = state.joinpath(*name.split('/'))
        if not file.exists() or existing.sha(file.read_bytes()) != digest:
            raise ConfigurationFailure('ec_disposition_original_file_changed')
    if (existing.sha((state/'receipts'/(source['request_id']+'.json')).read_bytes()) != source['receipt_sha256']
            or (state/'diagnostics'/(source['request_id']+'.json')).exists()
            or (state/'cache'/(source['request_key']+'.json')).exists()):
        raise ConfigurationFailure('ec_disposition_original_timeout_evidence_changed')
    installed = disposition.validate(ledger)
    current = json.loads((state/'checkpoint.json').read_bytes())
    old_count = source_checkpoint['phase2_token_preflight']; counts = current.get('phase2_token_preflight', {})
    if (identity({k:v for k,v in old_count.items() if k != 'rows'}) !=
            identity({k:v for k,v in counts.items() if k != 'rows'})
            or len(counts.get('rows', [])) < source['native_counts']
            or identity(counts['rows'][:source['native_counts']]) != source['native_counts_sha256']
            or identity(old_count['rows']) != source['native_counts_sha256']):
        raise ConfigurationFailure('ec_disposition_original_count_history_changed')
    if installed:
        disposition.validate_counts(ledger, counts['rows'])
    else:
        if existing.sha((state/'ledger.json').read_bytes()) != source['ledger_sha256']:
            raise ConfigurationFailure('ec_disposition_uninstalled_ledger_changed')
        names = {f.relative_to(state).as_posix() for f in state.rglob('*.json') if f.name != 'checkpoint.json'}
        allowed = set(source_checkpoint['files'])
        if path.exists():
            allowed.add(path.relative_to(state).as_posix())
        if names != allowed:
            raise ConfigurationFailure('ec_disposition_uninstalled_extra_files')
    if require and (not installed or not path.exists()):
        raise Deferred('ec_disposition_complete_lineage_required')
    return {'ledger': ledger, 'source_checkpoint': source_checkpoint, 'receipt': expected, 'installed': installed}


def install(state, source_checkpoint, crash=lambda point: None):
    """Atomic idempotent local install, called only after trusted authentication."""
    state = Path(state); ledger = existing.ExperimentLedger(state/'ledger.json')
    with ledger.locked():
        built = validate_local(state, source_checkpoint=source_checkpoint, require=False, ledger_value=ledger.read())
        try:
            path = receipt_path(state)
            if not path.exists():
                crash('before_receipt')
                atomic_json(path, built['receipt'])
            crash('after_receipt')
            if not built['installed']:
                built['ledger']['events'].append(disposition.event())
                crash('before_event')
                atomic_json(ledger.path, built['ledger'])
            crash('after_event'); crash('before_checkpoint')
        finally:
            existing.checkpoint(state)
        crash('after_checkpoint')
        validate_local(state, ledger_value=ledger.read())
    return ledger


def _source_snapshot(destination, api_call):
    """Read an authenticated original archive; never adopt it as a second owner."""
    source = disposition.plan()['source']
    run = trusted._run(api_call, source['run']['id'], source['run'])
    raw = trusted._download(api_call, source['artifact'], run)
    with tempfile.TemporaryDirectory(prefix='.ec-source-', dir=Path(destination).parent) as temporary:
        base = Path(temporary)/'state'
        existing.unpack_state(raw, base)
        cp_raw = (base/'checkpoint.json').read_bytes()
        if existing.sha(cp_raw) != source['checkpoint_sha256']:
            raise ConfigurationFailure('ec_disposition_source_archive_checkpoint')
        cp = json.loads(cp_raw)
        validate_local(base, source_checkpoint=cp, require=False)
    return cp, raw


def reservation_record(run, anchor, ledger_sha256):
    source = disposition.plan()['source']
    return {'version': VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': str(run['id']), 'attempt': str(run['run_attempt']), 'code_sha': run['head_sha'],
        'plan_sha256': identity(disposition.plan()), 'recovery_key': recovery_key(),
        'scope_id': SELECTOR['iteration3_ec_disposition'], 'request_id': source['request_id'],
        'source_ledger_sha256': source['ledger_sha256'], 'source_checkpoint_sha256': source['checkpoint_sha256'],
        'restore_anchor': trusted._artifact_identity(anchor), 'ledger_sha256': ledger_sha256,
        'maximum_new_microusd': 0, 'maximum_new_metered_attempts': 0, 'maximum_new_native_counts': 0}


def _normalized_ledger(state):
    value = json.loads((Path(state)/'ledger.json').read_bytes())
    if not disposition.validate(value):
        value['events'].append(disposition.event())
    return value


def maybe_restore(destination, artifacts, api_call):
    """Only exact zero-provider EC orphans may cross a missing latest checkpoint."""
    if not selected():
        return None
    trusted._exclusive(api_call)
    destination = Path(destination); source = disposition.plan()['source']
    reservations = [a for a in artifacts if '-reservation-' in a['name']]
    latest = latest_reservation(reservations)
    original = [a for a in reservations if a.get('id') == source['reservation_artifact']['id']]
    if len(original) != 1:
        raise Deferred('ec_disposition_original_reservation_missing')
    original = original[0]
    if identity({k:original.get(k) for k in source['reservation_artifact']}) != identity(source['reservation_artifact']):
        raise Deferred('ec_disposition_original_reservation_identity')
    source_run = trusted._run(api_call, source['run']['id'], source['run'])
    reservation_raw = trusted._download(api_call, trusted._artifact_identity(original), source_run)
    _, original_record = trusted._reservation(reservation_raw)
    if (original_record.get('scope_id') != SELECTOR['iteration3_ec_disposition']
            or original_record.get('operation') != 'check'
            or str(original_record.get('run_id')) != str(source_run['id'])
            or str(original_record.get('attempt')) != str(source_run['run_attempt'])
            or original_record.get('code_sha') != source_run['head_sha']):
        raise Deferred('ec_disposition_original_reservation_content')
    source_checkpoint, source_zip = _source_snapshot(destination, api_call)
    later = sorted((a for a in reservations if created(a) > created(original)), key=created)
    times = [created(a) for a in reservations if created(a) >= created(original)]
    if len(set(times)) != len(times) or created(latest) < created(original):
        raise Deferred('ec_disposition_history_order')
    with tempfile.TemporaryDirectory(prefix='.ec-restore-', dir=destination.parent) as temporary:
        base = Path(temporary)/'base'; existing.unpack_state(source_zip, base)
        anchor, anchor_state = source['artifact'], base
        for number, artifact in enumerate(later):
            match = re.fullmatch(re.escape(existing.PREFIX)+r'-reservation-([1-9][0-9]*)-([1-9][0-9]*)', artifact['name'])
            if not match:
                raise Deferred('ec_disposition_reservation_owner')
            run = trusted._run(api_call, artifact['workflow_run']['id'], attempt=int(match[2]))
            if artifact['name'] != existing.PREFIX+'-reservation-'+str(run['id'])+'-'+str(run['run_attempt']):
                raise Deferred('ec_disposition_reservation_owner')
            states = [a for a in artifacts if a['name'] == artifact['name'].replace('-reservation-', '-state-')]
            if states:
                if len(states) != 1:
                    raise Deferred('ec_disposition_state_ambiguous')
                target = Path(temporary)/('state-'+str(number))
                existing.unpack_state(trusted._download(api_call, trusted._artifact_identity(states[0]), run), target)
                cp = json.loads((target/'checkpoint.json').read_bytes())
                if identity({k:cp.get(k) for k in ('run_id','attempt','code_sha')}) != identity({
                        'run_id':str(run['id']),'attempt':str(run['run_attempt']),'code_sha':run['head_sha']}):
                    raise Deferred('ec_disposition_state_owner')
                validate_local(target, source_checkpoint=source_checkpoint)
                anchor, anchor_state = states[0], target
            else:
                record_raw, record = trusted._reservation(trusted._download(api_call, trusted._artifact_identity(artifact), run))
                expected = reservation_record(run, anchor, existing.sha(encoded(_normalized_ledger(anchor_state))+b'\n'))
                if run['event'] != 'workflow_dispatch' or record_raw != encoded(expected)+b'\n':
                    raise Deferred('ec_disposition_unknown_new_reservation')
        with existing.ExperimentLedger._thread_guard:
            if (destination/'ledger.json').exists():
                validate_local(destination, source_checkpoint=source_checkpoint, require=False)
                if identity(_normalized_ledger(destination)) != identity(_normalized_ledger(anchor_state)):
                    raise Deferred('ec_disposition_local_history_conflict')
            else:
                if destination.exists() and any(destination.iterdir()):
                    raise Deferred('ec_disposition_destination_not_empty')
                for file in anchor_state.rglob('*.json'):
                    target = destination/file.relative_to(anchor_state)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(file.read_bytes())
            ledger = install(destination, source_checkpoint)
        ledger.ec_disposition_anchor = trusted._artifact_identity(anchor)
        return ledger


def validate_restored(destination, latest):
    """A later ordinary owner cannot shed this event, receipt, or original hold."""
    source = disposition.plan()['source']; destination = Path(destination)
    state = json.loads((destination/'ledger.json').read_bytes())
    if (created(latest) > created(source['reservation_artifact'])
            or receipt_path(destination).exists() or disposition.validate(state)):
        validate_local(destination)


def prepare_plan(state, api_call):
    trusted._exclusive(api_call)
    cp, _ = _source_snapshot(state, api_call)
    install(state, cp)
    return validate_local(state)


def run(args):
    existing.trusted_environment()
    if not selected():
        raise ConfigurationFailure('ec_disposition_exact_selector')
    current = {'id':int(os.environ['GITHUB_RUN_ID']), 'run_attempt':int(os.environ['GITHUB_RUN_ATTEMPT']),
               'head_sha':os.environ['GITHUB_SHA']}
    prepared = args.state/'receipts'/(identity([VERSION, 'prepare', current])[:32]+'.json')
    if args.action == 'prepare':
        ledger = existing.restore(args.state, existing.policy(), api_call=existing.api)
        record = reservation_record(current, ledger.ec_disposition_anchor, existing.sha(ledger.path.read_bytes()))
        if prepared.exists() and prepared.read_bytes() != encoded(record)+b'\n':
            raise ConfigurationFailure('ec_disposition_preparation_conflict')
        atomic_json(prepared, record); existing.checkpoint(args.state)
        atomic_json(args.reservation, record)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('text_provider=none\n')
        return
    trusted._exclusive(existing.api)
    built = validate_local(args.state)
    record = json.loads(args.reservation.read_bytes())
    expected = reservation_record(current, record['restore_anchor'], existing.sha((args.state/'ledger.json').read_bytes()))
    if (not prepared.exists() or prepared.read_bytes() != encoded(expected)+b'\n'
            or args.reservation.read_bytes() != encoded(expected)+b'\n'):
        raise ConfigurationFailure('ec_disposition_prepared_identity_changed')
    atomic_json(args.result, {'version':VERSION, 'status':'original_unknown_hold_permanently_retained',
        'scope_id':SELECTOR['iteration3_ec_disposition'], 'request_id':disposition.REQUEST_ID,
        'recovery_key':recovery_key(), 'held_microusd':disposition.plan()['held_microusd'],
        'hold_location':'unchanged_original_reserved_unknown_request',
        'actual_usage':'unknown', 'scientific_result_recovered':False, 'paid_requests_replayed':0,
        'new_microusd':0, 'new_metered_attempts':0, 'new_native_count_calls':0,
        'validation_run_id':os.environ['GITHUB_RUN_ID'], 'validation_code_sha':os.environ['GITHUB_SHA']})
    existing.checkpoint(args.state)
