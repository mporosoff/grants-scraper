"""One authenticated lost-checkpoint disposition; no provider or science recovery.

Only the exact protected selector may cross the pinned missing Math checkpoint.
Later missing reservations remain fatal unless they are authenticated zero-cost
instances of this same disposition, with a complete, bound restoration anchor.
"""
import io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from tools import contextual_team_checkpoint_disposition as disposition
from tools import team_recommender_executor as existing
from tools.team_recommender_checkpoint import created, latest_reservation
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity

VERSION = disposition.VERSION
SELECTOR = {'iteration2_checkpoint_disposition': '341997'}


def selected():
    raw = os.environ.get('CONTEXTUAL_CHECK', '')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ConfigurationFailure('checkpoint_disposition_duplicate_selector_key')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique) if raw else None
    except ValueError:
        return False
    if isinstance(value, dict) and 'iteration2_checkpoint_disposition' in value:
        if value != SELECTOR or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')):
            raise ConfigurationFailure('checkpoint_disposition_exact_selector')
        return True
    return False


def recovery_key():
    return identity(disposition.event())


def receipt_path(state):
    return Path(state)/'receipts'/(recovery_key()[:32]+'.json')


def _artifact_identity(artifact):
    return {k: artifact[k] for k in ('id', 'name', 'digest')}


def _run(api_call, run_id, expected=None, *, attempt=None):
    run = json.loads(api_call('actions/runs/'+str(run_id)))
    attempt = expected.get('run_attempt') if expected else attempt
    if attempt is not None and (run.get('run_attempt') != attempt or run.get('status') != 'completed'):
        run = json.loads(api_call('actions/runs/'+str(run_id)+'/attempts/'+str(attempt)))
    if (run.get('id') != int(run_id) or run.get('path') != existing.WORKFLOW
            or run.get('head_branch') != 'main'
            or run.get('event') not in {'workflow_dispatch', 'repository_dispatch'}
            or run.get('status') != 'completed' or not run.get('conclusion')
            or type(run.get('run_attempt')) is not int
            or not re.fullmatch('[a-f0-9]{40}', run.get('head_sha', ''))
            or (attempt is not None and run.get('run_attempt') != attempt)
            or (expected and any(run.get(k) != v for k, v in expected.items()))):
        raise Deferred('checkpoint_disposition_untrusted_terminal_run')
    return run


def _exclusive(api_call):
    existing.trusted_environment()
    run = json.loads(api_call('actions/runs/'+os.environ['GITHUB_RUN_ID']))
    expected = {'id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'head_sha': os.environ['GITHUB_SHA'], 'path': existing.WORKFLOW, 'head_branch': 'main',
        'event': 'workflow_dispatch', 'status': 'in_progress', 'conclusion': None}
    if identity({k: run.get(k) for k in expected}) != identity(expected):
        raise Deferred('checkpoint_disposition_current_owner_identity')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))
    if (active.get('total_count', len(active['workflow_runs'])) >= 100
            or any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active['workflow_runs'])):
        raise Deferred('checkpoint_disposition_another_owner_active')


def _download(api_call, expected, run):
    artifact = json.loads(api_call('actions/artifacts/'+str(expected['id'])))
    if (any(artifact.get(k) != v for k, v in expected.items()) or artifact.get('expired') is not False
            or artifact.get('workflow_run', {}).get('id') != run['id']
            or artifact.get('workflow_run', {}).get('head_sha') != run['head_sha']
            or not re.fullmatch('sha256:[a-f0-9]{64}', artifact.get('digest', ''))):
        raise Deferred('checkpoint_disposition_artifact_identity')
    raw = api_call('actions/artifacts/'+str(expected['id'])+'/zip')
    if not isinstance(raw, bytes) or len(raw) > existing.STATE_LIMIT or 'sha256:'+existing.sha(raw) != artifact['digest']:
        raise Deferred('checkpoint_disposition_archive_digest')
    return raw


def _reservation(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        if len(rows) != 1 or rows[0].filename != 'team-reservation.json' or rows[0].file_size > 32768:
            raise Deferred('checkpoint_disposition_reservation_archive')
        data = archive.read(rows[0])
    return data, json.loads(data)


def _receipt(prior_checkpoint):
    p = disposition.plan()
    return {'version': VERSION, 'event': disposition.event(), 'plan_sha256': identity(p),
        'prior_checkpoint': prior_checkpoint, 'failed_reservation': p['failed']['reservation'],
        'actual_usage': 'unknown', 'scientific_result_recovered': False, 'paid_requests_replayed': 0}


def validate_local(state, *, prior_checkpoint=None, require=True, ledger_value=None):
    """Check immutable source files and all prefixes, including on ordinary restores."""
    state = Path(state); p = disposition.plan(); prior = p['prior']
    ledger = existing.ExperimentLedger(state/'ledger.json').read() if ledger_value is None else ledger_value
    path = receipt_path(state)
    if prior_checkpoint is None:
        if not path.exists():
            if require:
                raise Deferred('checkpoint_disposition_receipt_required')
            return False
        prior_checkpoint = json.loads(path.read_bytes())['prior_checkpoint']
    if existing.sha(encoded(prior_checkpoint)+b'\n') != prior['checkpoint_sha256']:
        raise Deferred('checkpoint_disposition_original_checkpoint_identity')
    if prior_checkpoint['files'].get('ledger.json') != prior['ledger_sha256']:
        raise Deferred('checkpoint_disposition_original_ledger_identity')
    expected = _receipt(prior_checkpoint)
    if path.exists() and path.read_bytes() != encoded(expected)+b'\n':
        raise Deferred('checkpoint_disposition_receipt_conflict')
    for name, digest in prior_checkpoint['files'].items():
        if name == 'ledger.json':
            continue
        # Names come from the pinned, unpack-validated checkpoint, not a caller.
        if not re.fullmatch(r'(cache/[a-f0-9]{64}|receipts/[a-f0-9]{32}|diagnostics/[a-f0-9]{32})\.json', name):
            raise Deferred('checkpoint_disposition_original_member')
        file = state.joinpath(*name.split('/'))
        if not file.exists() or existing.sha(file.read_bytes()) != digest:
            raise Deferred('checkpoint_disposition_original_file_changed')
    installed = disposition.validate(ledger)
    checkpoint = json.loads((state/'checkpoint.json').read_bytes())
    original_count = prior_checkpoint.get('phase2_token_preflight', {})
    current_count = checkpoint.get('phase2_token_preflight', {})
    if (identity({k: v for k, v in original_count.items() if k != 'rows'}) !=
            identity({k: v for k, v in current_count.items() if k != 'rows'})
            or identity(current_count.get('rows', [])[:prior['native_counts']]) != identity(original_count.get('rows', []))
            or identity(original_count.get('rows', [])) != prior['native_counts_sha256']):
        raise Deferred('checkpoint_disposition_native_history_conflict')
    if installed:
        disposition.validate_counts(ledger, current_count.get('rows', []))
    elif existing.sha((state/'ledger.json').read_bytes()) != prior['ledger_sha256']:
        raise Deferred('checkpoint_disposition_uninstalled_history_conflict')
    if require and (not installed or not path.exists()):
        raise Deferred('checkpoint_disposition_complete_lineage_required')
    return {'ledger': ledger, 'prior_checkpoint': prior_checkpoint, 'receipt': expected, 'installed': installed}


def install(state, prior_checkpoint, crash=lambda point: None):
    state = Path(state); ledger = existing.ExperimentLedger(state/'ledger.json')
    with ledger.locked():
        built = validate_local(state, prior_checkpoint=prior_checkpoint, require=False, ledger_value=ledger.read())
        try:
            path = receipt_path(state)
            if not path.exists():
                atomic_json(path, built['receipt'])
            crash('after_receipt')
            if not built['installed']:
                built['ledger']['events'].append(disposition.event())
                atomic_json(ledger.path, built['ledger'])
            crash('after_event'); crash('before_checkpoint')
        finally:
            existing.checkpoint(state)
        crash('after_checkpoint')
        validate_local(state, ledger_value=ledger.read())
    return ledger


def reservation_record(run, anchor, ledger_sha256):
    p = disposition.plan()
    return {'version': VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': str(run['id']), 'attempt': str(run['run_attempt']), 'code_sha': run['head_sha'],
        'plan_sha256': identity(p), 'recovery_key': recovery_key(), 'scope_id': p['closed_scope_id'],
        'failed_job_id': p['failed']['job_id'], 'failed_reservation_sha256': p['failed']['reservation_sha256'],
        'restore_anchor': _artifact_identity(anchor), 'ledger_sha256': ledger_sha256,
        'maximum_new_microusd': 0, 'maximum_new_metered_attempts': 0, 'maximum_new_native_counts': 0}


def maybe_restore(destination, artifacts, api_call):
    """Return None for every ordinary route; no generic historical fallback."""
    if not selected():
        return None
    _exclusive(api_call)
    p = disposition.plan(); prior, failed = p['prior'], p['failed']
    reservations = [a for a in artifacts if '-reservation-' in a['name']]
    latest = latest_reservation(reservations)
    matches = [a for a in reservations if a['id'] == failed['artifact']['id']]
    if len(matches) != 1 or _artifact_identity(matches[0]) != failed['artifact']:
        raise Deferred('checkpoint_disposition_failed_reservation_missing')
    failed_artifact = matches[0]
    if failed_artifact.get('created_at') != failed['artifact_created_at']:
        raise Deferred('checkpoint_disposition_failed_reservation_time')
    failed_run = _run(api_call, failed['run']['id'], failed['run'])
    raw, value = _reservation(_download(api_call, failed['artifact'], failed_run))
    if existing.sha(raw) != failed['reservation_sha256'] or value != failed['reservation']:
        raise Deferred('checkpoint_disposition_failed_reservation_content')
    if any(a['name'] == failed_artifact['name'].replace('-reservation-', '-state-') for a in artifacts):
        raise Deferred('checkpoint_disposition_late_original_state_requires_reconciliation')
    prior_run = _run(api_call, prior['run']['id'], prior['run'])
    prior_raw = _download(api_call, prior['artifact'], prior_run)
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.checkpoint-disposition-', dir=destination.parent) as temporary:
        base = Path(temporary)/'base'; existing.unpack_state(prior_raw, base)
        if (existing.sha((base/'checkpoint.json').read_bytes()) != prior['checkpoint_sha256']
                or existing.sha((base/'ledger.json').read_bytes()) != prior['ledger_sha256']):
            raise Deferred('checkpoint_disposition_prior_snapshot_identity')
        original_checkpoint = json.loads((base/'checkpoint.json').read_bytes())
        validate_local(base, prior_checkpoint=original_checkpoint, require=False)
        anchor = prior['artifact']; anchor_state = base
        later = sorted((a for a in reservations if created(a) > created(failed_artifact)), key=created)
        # Any ambiguous ordering remains fatal, even if the last entry is unique.
        times = [created(a) for a in reservations if created(a) >= created(failed_artifact)]
        if len(set(times)) != len(times) or created(latest) < created(failed_artifact):
            raise Deferred('checkpoint_disposition_history_order')
        for number, artifact in enumerate(later):
            match = re.fullmatch(re.escape(existing.PREFIX)+r'-reservation-([1-9][0-9]*)-([1-9][0-9]*)', artifact['name'])
            if not match:
                raise Deferred('checkpoint_disposition_reservation_owner')
            run = _run(api_call, artifact['workflow_run']['id'], attempt=int(match[2]))
            if artifact['name'] != existing.PREFIX+'-reservation-'+str(run['id'])+'-'+str(run['run_attempt']):
                raise Deferred('checkpoint_disposition_reservation_owner')
            states = [a for a in artifacts if a['name'] == artifact['name'].replace('-reservation-', '-state-')]
            if states:
                if len(states) != 1:
                    raise Deferred('checkpoint_disposition_state_ambiguous')
                target = Path(temporary)/('state-'+str(number))
                existing.unpack_state(_download(api_call, _artifact_identity(states[0]), run), target)
                cp = json.loads((target/'checkpoint.json').read_bytes())
                if any(str(cp.get(k)) != str(v) for k, v in
                       {'run_id': run['id'], 'attempt': run['run_attempt'], 'code_sha': run['head_sha']}.items()):
                    raise Deferred('checkpoint_disposition_state_owner')
                validate_local(target, prior_checkpoint=original_checkpoint, require=True)
                anchor, anchor_state = states[0], target
            else:
                record_raw, record = _reservation(_download(api_call, _artifact_identity(artifact), run))
                ledger = json.loads((anchor_state/'ledger.json').read_bytes())
                if not disposition.validate(ledger):
                    ledger['events'].append(disposition.event())
                expected = reservation_record(run, anchor, existing.sha(encoded(ledger)+b'\n'))
                if run['event'] != 'workflow_dispatch' or record != expected or record_raw != encoded(expected)+b'\n':
                    raise Deferred('checkpoint_disposition_unknown_new_reservation')
        with existing.ExperimentLedger._thread_guard:
            if (destination/'ledger.json').exists():
                # Never overwrite an existing local history, even during retry.
                validate_local(destination, prior_checkpoint=original_checkpoint, require=False)
                local = json.loads((destination/'ledger.json').read_bytes())
                remote = json.loads((anchor_state/'ledger.json').read_bytes())
                if not disposition.validate(remote):
                    remote['events'].append(disposition.event())
                if not disposition.validate(local):
                    local['events'].append(disposition.event())
                if local != remote:
                    raise Deferred('checkpoint_disposition_local_history_conflict')
            else:
                if destination.exists() and any(destination.iterdir()):
                    raise Deferred('checkpoint_disposition_destination_not_empty')
                for file in anchor_state.rglob('*.json'):
                    target = destination/file.relative_to(anchor_state)
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(file.read_bytes())
            ledger = install(destination, original_checkpoint)
        ledger.checkpoint_disposition_anchor = _artifact_identity(anchor)
        return ledger


def validate_restored(destination, latest):
    """Once the failed reservation is crossed, every future owner carries its hold."""
    p = disposition.plan()
    if created(latest) >= created({'created_at': p['failed']['artifact_created_at']}):
        if latest.get('workflow_run', {}).get('id') == p['failed']['run']['id']:
            raise Deferred('checkpoint_disposition_late_original_state_requires_reconciliation')
        validate_local(destination)
    elif disposition.validate(existing.ExperimentLedger(Path(destination)/'ledger.json').read()):
        validate_local(destination)


def run(args):
    existing.trusted_environment()
    if not selected():
        raise ConfigurationFailure('checkpoint_disposition_exact_selector')
    if args.action == 'prepare':
        ledger = existing.restore(args.state, existing.policy())
        current = {'id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                   'head_sha': os.environ['GITHUB_SHA']}
        record = reservation_record(current, ledger.checkpoint_disposition_anchor, existing.sha(ledger.path.read_bytes()))
        prepared = args.state/'receipts'/(identity([VERSION, 'prepare', current])[:32]+'.json')
        if prepared.exists() and prepared.read_bytes() != encoded(record)+b'\n':
            raise Deferred('checkpoint_disposition_preparation_conflict')
        atomic_json(prepared, record)
        existing.checkpoint(args.state)
        atomic_json(args.reservation, record)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('text_provider=none\n')
        return
    _exclusive(existing.api)
    built = validate_local(args.state)
    record = json.loads(args.reservation.read_bytes())
    current = {'id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
               'head_sha': os.environ['GITHUB_SHA']}
    prepared = args.state/'receipts'/(identity([VERSION, 'prepare', current])[:32]+'.json')
    if (not prepared.exists() or prepared.read_bytes() != encoded(record)+b'\n'
            or identity(record) != identity(reservation_record(current, record['restore_anchor'], existing.sha((args.state/'ledger.json').read_bytes())))):
        raise Deferred('checkpoint_disposition_prepared_identity_changed')
    atomic_json(args.result, {'version': VERSION, 'scope_id': disposition.plan()['closed_scope_id'],
        'status': 'unknown_exposure_held_scope_permanently_closed', 'recovery_key': recovery_key(),
        'exposure': disposition.exposure(built['ledger']), 'actual_usage': 'unknown',
        'scientific_result_recovered': False, 'paid_requests_replayed': 0,
        'new_microusd': 0, 'new_metered_attempts': 0, 'new_native_count_calls': 0,
        'validation_run_id': os.environ['GITHUB_RUN_ID'], 'validation_code_sha': os.environ['GITHUB_SHA']})
    existing.checkpoint(args.state)
