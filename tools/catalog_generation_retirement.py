"""Close one authenticated zero-spend duplicate; never reset or transfer budgets."""
import io
import json
from pathlib import Path
import zipfile

from tools import release_candidate as c
from tools.fetch_release_artifact import run_artifacts
from tools.offline_ai import identity

POLICY = 'config/catalog_generation_retirement.json'
RETIRED_RUN = '36488051427'
REPLACEMENT_RUN = '36480049073'
PAID_STEPS = (
    'Extract citation-backed facts from official notices',
    'Generate bounded new and changed proposed teams',
    'Build compatible production document vectors',
)


class RetirementHold(ValueError):
    run = RETIRED_RUN


def require(condition, message):
    if not condition:
        raise RetirementHold('Retired generation evidence: ' + message)


def disposition(root):
    plan = c.read_json(Path(root) / POLICY)
    require(plan.get('schema_version') == 1 and plan.get('kind') == 'cancelled_unspent_generation_superseded'
            and plan.get('repository') == 'mporosoff/grants-scraper'
            and plan.get('replacement_run') == REPLACEMENT_RUN
            and str(plan['run']['id']) == RETIRED_RUN, 'unsupported disposition')
    return plan


def assert_run_open(run, root=c.ROOT):
    if str(run) == RETIRED_RUN:
        disposition(root)
        raise RetirementHold('Generation run is permanently retired without spend; resume replacement ' + REPLACEMENT_RUN)


def _archive(api, artifact, member):
    raw = api(f"actions/artifacts/{artifact['id']}/zip")
    require(len(raw) == artifact['size_in_bytes'] and len(raw) <= 16384
            and 'sha256:' + c.digest(raw) == artifact['digest'], 'archive identity changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 1 and entries[0].filename == member and entries[0].file_size <= 8192,
                'unexpected archive members')
        return json.loads(archive.read(member))


def allows_skip(root, repository, run, artifacts, published, api):
    """Only the named protected replacement can supersede this exact first attempt."""
    if str(run['id']) != RETIRED_RUN:
        return False
    plan = disposition(root)
    require(repository == plan['repository'], 'repository mismatch')
    expected = plan['run']
    require(expected['run_attempt'] == 1 and expected['status'] == 'completed'
            and expected['conclusion'] == 'cancelled' and expected['event'] == 'push'
            and expected['path'] == '.github/workflows/refresh-opportunities.yml'
            and expected['head_branch'] == 'main', 'unsupported terminal owner')
    current = json.loads(api(f'actions/runs/{RETIRED_RUN}'))
    for observed in (run, current):
        require({key: observed.get(key) for key in expected} == expected, 'run was replayed or changed')
    # Re-read the complete inventory: additions must never be hidden by a stale
    # first page, and loss/expiry of these exact proofs requires inspection.
    inventory = run_artifacts(RETIRED_RUN, api)
    expected_artifacts = {a['id']: a for a in plan['artifacts']}
    require(len(expected_artifacts) == len(plan['artifacts']) == 3, 'ambiguous disposition artifacts')
    for observed in (artifacts, inventory):
        require(len(observed) == 3 and {a['id'] for a in observed} == set(expected_artifacts),
                'artifact inventory changed')
        for artifact in observed:
            pinned = expected_artifacts[artifact['id']]
            require(artifact.get('expired') is False and
                    {key: artifact.get(key) for key in pinned} == pinned, 'artifact provenance changed or expired')
    by_name = {a['name']: a for a in inventory}
    require(set(by_name) == {f'generation-spend-reservation-{RETIRED_RUN}-1',
                            f'generation-spend-state-{RETIRED_RUN}-1', 'release-plan-1'}, 'artifact names changed')
    ledger = _archive(api, by_name[f'generation-spend-state-{RETIRED_RUN}-1'], 'ledger.json')
    require(ledger == {'blocked_providers': {}, 'events': [], 'limit_microusd': 2000000,
                       'logical_id': 'offline-' + RETIRED_RUN, 'max_requests': 300, 'requests': [], 'version': 1},
            'accounting is not the exact unspent owner')
    reservation = _archive(api, by_name[f'generation-spend-reservation-{RETIRED_RUN}-1'], 'spend-reservation.json')
    require(reservation == {'run_id': RETIRED_RUN, 'attempt': '1', 'mode': 'maintenance',
                            'maximum_logical_spend_usd': 2, 'prior_ledger_hash': identity(ledger)},
            'reservation does not bind the unspent ledger')
    release_plan = _archive(api, by_name['release-plan-1'], 'release-plan.json')
    require(release_plan.get('release_sha') == expected['head_sha'] and release_plan.get('stage') == 'generate'
            and release_plan.get('team_mode') == 'maintenance' and release_plan.get('team_generation_ready') is False,
            'generation plan changed')
    response = json.loads(api(f'actions/runs/{RETIRED_RUN}/attempts/1/jobs?per_page=100&page=1'))
    jobs = response['jobs']
    require(response.get('total_count') == len(jobs) == len(plan['jobs']) == 10, 'job inventory is incomplete or changed')
    require(sorted(({k: job.get(k) for k in ('id', 'name', 'conclusion')} for job in jobs), key=lambda j: j['id'])
            == sorted(plan['jobs'], key=lambda j: j['id']), 'job identities changed')
    require(all(job.get('run_attempt') == 1 and job.get('head_sha') == expected['head_sha']
                and job.get('status') == 'completed' for job in jobs), 'job attempt or completion changed')
    generation = next(job for job in jobs if job['name'] == 'generate')
    for name in PAID_STEPS:
        matches = [step for step in generation['steps'] if step.get('name') == name]
        require(len(matches) == 1 and matches[0].get('status') == 'completed'
                and matches[0].get('conclusion') == 'skipped', 'paid stage was not skipped: ' + name)
    # The protected pointer history keeps this true after later publications;
    # the current candidate alone would incorrectly reopen the old hold.
    return any(str(owner) == REPLACEMENT_RUN for owner, _ in published)
