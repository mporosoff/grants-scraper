"""One exact recovery of public state downloaded before Actions artifact loss.

The protected seed preserves the actual ledger and cached verdict bytes. Its
historical ZIP hashes describe the original uploads; they do not authenticate
a reconstructed ZIP or fabricate a candidate, measured usage, or a new budget.
"""
import json
import os
from pathlib import Path
import re
import tempfile

from tools import release_candidate as release
from tools.offline_spend import atomic_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/generation_recovery/release-338/manifest.json'
VERSION = 'release-338-downloaded-spend-recovery-1'
REPOSITORY = 'mporosoff/grants-scraper'
RUN = '38757294301'
ATTEMPT = '3'
EVENT_SHA = 'c90cab07610580488024109532b6bbf12cb3d79c'
ORIGINAL_JOB = 116499469833
NO_SPEND_JOB = 116992356899
WORKFLOW = '.github/workflows/refresh-opportunities.yml'
LEDGER_SHA = '0b822bd3bd8b143fdb823db59337c8380807ad82303554458d256e8bce1ce05d'
PLAN_SHA = 'acff35b56500797d2fe16167fa616149f21c9b022ad93c8b6dce2a63495ad06d'
ARTIFACTS = {
    'state': {'id': 11983474765, 'name': 'generation-spend-state-' + RUN + '-1',
              'zip_sha256': 'ac04f38b952f7c4f1701c1f533f66528f2ec0a69433b029e174b3ed99be1b64a'},
    'reservation': {'id': 11984261557, 'name': 'generation-spend-reservation-' + RUN + '-1',
                    'zip_sha256': 'fbbb8d22dc7c6644334fbed2ee89c2a8413f53549f841f4f26c6c450570a4f44'},
}
RESTORE_STEP = 'Restore the logical spend checkpoint'
RESERVE_STEP = 'Reserve the complete logical allowance before provider dispatch'
PROVIDER_STEPS = ('Extract citation-backed facts from official notices',
                  'Generate bounded new and changed proposed teams',
                  'Build compatible production document vectors')


def require(ok, reason):
    if not ok:
        raise ValueError('Named generation spend recovery rejected: ' + reason)


def json_value(raw):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite recovery JSON')))


def payloads():
    raw_manifest = CONFIG.read_bytes()
    require(release.digest(raw_manifest) == PLAN_SHA, 'protected manifest hash')
    plan = json_value(raw_manifest)
    require(plan['version'] == VERSION and plan['repository'] == REPOSITORY
            and plan['run_id'] == RUN and plan['allowed_attempt'] == ATTEMPT
            and plan['historical_artifacts'] == ARTIFACTS
            and plan['ledger_sha256'] == LEDGER_SHA
            and plan['archive_reauthenticated'] is False
            and plan['provenance'] == 'downloaded-before-artifact-loss', 'exact protected selector')
    files = plan['files']
    require(len(files) == 44 and files.get('ledger.json') == LEDGER_SHA
            and all(name == 'ledger.json' or re.fullmatch('cov4-cache/[a-f0-9]{64}\\.json', name)
                    for name in files), 'public file allowlist')
    packets = {}
    for name, digest in files.items():
        require(re.fullmatch('[a-f0-9]{64}', digest) is not None, 'member digest')
        raw = release.checked_path(CONFIG.parent / 'state', name).read_bytes()
        require(release.digest(raw) == digest, 'member bytes: ' + name)
        packets[name] = raw
    ledger = json_value(packets['ledger.json'])
    requests = ledger['requests']
    require(ledger['version'] == 1 and ledger['logical_id'] == 'offline-' + RUN
            and ledger['limit_microusd'] == 2_000_000 and ledger['max_requests'] == 300
            and len(requests) == 44 and sum(row['charged_microusd'] for row in requests) == 279679
            and sum(row['status'] == 'valid' for row in requests) == 43
            and sum(row['status'] == 'reserved_unknown' for row in requests) == 1, 'unchanged original accounting')
    require(all(row['provider'] == 'anthropic' and row['model'] == 'claude-sonnet-5'
                and row['stage'] == 'cov4' for row in requests), 'original request family')
    unknown = next(row for row in requests if row['status'] == 'reserved_unknown')
    require(unknown['usage'] is None and unknown['charged_microusd'] == unknown['reserved_microusd'],
            'uncertain request retains its complete charge')
    completed = {row['key']: row for row in requests if row['status'] == 'valid'}
    require(set(files) - {'ledger.json'} == {'cov4-cache/' + key + '.json' for key in completed},
            'exact completed verdict population')
    for name, raw in packets.items():
        if name == 'ledger.json':
            continue
        cached = json_value(raw)
        key = name.removeprefix('cov4-cache/').removesuffix('.json')
        require(set(cached) == {'key', 'returned_model', 'transport_version', 'value'}
                and cached['key'] == key and cached['returned_model'] == completed[key]['returned_model']
                and cached['transport_version'] == completed[key]['transport_version']
                and set(cached['value']) == {'fundable', 'owned', 'reason'}
                and cached['value']['fundable'] == cached['value']['owned'] == 'yes'
                and isinstance(cached['value']['reason'], str) and len(cached['value']['reason']) <= 500,
                'public completed verdict: ' + key)
    return plan, packets


def trusted_attempt(api, attempt):
    value = json_value(api(f'actions/runs/{RUN}/attempts/{attempt}'))
    require(value.get('id') == int(RUN) and value.get('run_attempt') == attempt
            and value.get('path') == WORKFLOW and value.get('head_branch') == 'main'
            and value.get('head_sha') == EVENT_SHA and value.get('event') == 'schedule'
            and value.get('status') == 'completed' and value.get('conclusion') == 'failure',
            'historical protected attempt ' + str(attempt))
    return value


def upload_proof(log, artifact):
    lines = log.splitlines()
    marker = f'Artifact {artifact["name"]}.zip successfully finalized. Artifact ID {artifact["id"]}'
    matches = [number for number, line in enumerate(lines) if marker in line]
    require(len(matches) == 1, 'historical upload identity')
    nearby = '\n'.join(lines[max(0, matches[0] - 5):matches[0]])
    require('SHA256 digest of uploaded artifact zip is ' + artifact['zip_sha256'] in nearby,
            'historical upload digest context')


def authenticate_history(api):
    trusted_attempt(api, 1)
    trusted_attempt(api, 2)
    original = json_value(api(f'actions/jobs/{ORIGINAL_JOB}'))
    require(original.get('id') == ORIGINAL_JOB and original.get('run_id') == int(RUN)
            and original.get('run_attempt') == 1 and original.get('name') == 'generate'
            and original.get('head_sha') == EVENT_SHA and original.get('status') == 'completed'
            and original.get('conclusion') == 'failure', 'original generate job')
    log = api(f'actions/jobs/{ORIGINAL_JOB}/logs').decode('utf-8-sig')
    for artifact in ARTIFACTS.values():
        upload_proof(log, artifact)
    batch = json_value(api(f'actions/runs/{RUN}/attempts/2/jobs?per_page=100&page=1'))
    jobs = batch['jobs']
    expected = {'plan', 'generate', 'assemble', 'catalog-correction', 'program-area-revalidation',
                'catalog-source-recovery', 'catalog-access-correction', 'catalog-identity-correction',
                'catalog-url-correction', 'candidate', 'validate', 'publish', 'pages', 'verify-live', 'closeout'}
    require(len(jobs) == batch.get('total_count') == len(expected)
            and {job.get('name') for job in jobs} == expected, 'complete no-spend attempt jobs')
    for job in jobs:
        if job['name'] not in ('plan', 'generate', 'closeout'):
            require(job.get('conclusion') == 'skipped', 'another lifecycle job started')
    generate = next(job for job in jobs if job['name'] == 'generate')
    require(generate.get('id') == NO_SPEND_JOB and generate.get('status') == 'completed'
            and generate.get('conclusion') == 'failure', 'no-spend generate identity')
    steps = generate['steps']
    names = [step.get('name') for step in steps]
    require(len(names) == len(set(names)), 'ambiguous no-spend job steps')
    by_name = {step['name']: step for step in steps}
    require(by_name[RESTORE_STEP]['conclusion'] == 'failure'
            and by_name[RESERVE_STEP]['conclusion'] == 'skipped'
            and by_name[RESTORE_STEP]['number'] < by_name[RESERVE_STEP]['number']
            and all(by_name[name]['conclusion'] == 'skipped' for name in PROVIDER_STEPS),
            'later attempt reserved or dispatched work')


def restore(repository, run, attempt, destination, mode, meta, artifacts, *, api, qualification_pilot=False):
    """Recover only attempt three; a later missing checkpoint cannot roll back."""
    if str(run) != RUN or str(attempt) != ATTEMPT:
        return False
    require(repository == REPOSITORY and mode == 'maintenance' and not qualification_pilot,
            'original repository, mode and allowance only')
    require(meta.get('id') == int(RUN) and meta.get('run_attempt') == int(ATTEMPT)
            and meta.get('head_sha') == EVENT_SHA and meta.get('path') == WORKFLOW
            and meta.get('head_branch') == 'main' and meta.get('event') == 'schedule'
            and meta.get('status') == 'in_progress', 'current exact protected attempt')
    require(all(re.fullmatch('release-plan-[1-3]', item.get('name', '')) for item in artifacts),
            'unexpected retained generation evidence')
    plan, packets = payloads()  # Validate every protected byte before writing.
    authenticate_history(api)
    destination = Path(destination)
    require(destination.name == 'offline-' + RUN and not destination.is_symlink()
            and (not destination.exists() or not any(destination.iterdir())), 'empty original state destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.generation-recovery-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'state'
        staging.mkdir()
        for name, raw in packets.items():
            target = release.checked_path(staging, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        atomic_json(staging / 'recovery-provenance.json', {
            'version': VERSION, 'manifest_sha256': PLAN_SHA, 'source_run': RUN, 'source_attempt': '1',
            'recovery_attempt': ATTEMPT, 'provenance': plan['provenance'],
            'archive_reauthenticated': False, 'ledger_sha256': LEDGER_SHA,
            'additional_allowance_microusd': 0, 'candidate_or_validation_evidence': False})
        os.replace(staging, destination)
    print('Recovered exact downloaded ledger and 43 public verdicts for original attempt 3; original allowance and uncertain charge retained')
    return True
