"""One reviewed service-slot disposition; no provider, replay, or new ledger.

The default command only authenticates evidence and prepares a local receipt.
Only --execute can submit the one atomic INSERT to the existing D1 database.
Its trigger archives the exact original row and releases only the named slot.
"""
import argparse
import base64
from contextlib import closing
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import tomllib
import urllib.request
import zipfile

from tools import contextual_team_checkpoint_disposition as accounting
from tools import contextual_team_checkpoint_recovery as recovery
from tools import contextual_team_completion_policy as completion
from tools import contextual_team_iteration2_policy as iteration2
from tools import team_recommender_executor as existing
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity
from tools.team_recommender_checkpoint import latest_reservation

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'iteration2-service-slot-disposition-v1'
TABLE = 'contextual_service_dispositions'
CONFIG = ROOT/'config/contextual_team/iteration2-service-disposition-v1.json'
MIGRATION = ROOT/'workers/researcher-intake/migrations/0007_contextual_service_dispositions.sql'
WORKER_CONFIG = 'workers/researcher-intake/wrangler.jsonc'
CALLBACK_SOURCE = 'workers/researcher-intake/src/contextual.js'
DEPLOY_WORKFLOW = '.github/workflows/deploy-researcher-intake.yml'


def require(value, reason):
    if not value:
        raise ConfigurationFailure('service_disposition_' + reason)


def plan():
    p = json.loads(CONFIG.read_bytes()); a = accounting.plan(); row = p['original_row']
    require(p['version'] == VERSION and p['authorization_id'] == accounting.OWNER
        and p['repository'] == existing.REPOSITORY and identity(row) == p['original_row_identity']
        and row['job_id'] == a['failed']['job_id'] and row['scope_id'] == a['closed_scope_id']
        and row['release_id'] == a['failed']['release_id'] and row['person_id'] == ''
        and row['run_id'] == str(a['failed']['run']['id'])
        and row['code_sha'] == a['failed']['run']['head_sha']
        and row['state'] == 'in_progress' and row['active_slot'] == 1 and row['result_json'] is None
        and p['accounting_authority'] == accounting.VERSION
        and p['accounting_plan_sha256'] == identity(a)
        and p['accounting_event_identity'] == identity(accounting.event()) and p['hold'] == a['hold']
        and p['new_allowance'] == 0 and p['public_activation'] is False
        and p['recurring_paid_usage'] is False and p['closed_scope_replay'] is False,
        'exact_plan_required')
    require(re.fullmatch('[a-f0-9]{64}', p['callback_guard_source_sha256']), 'guard_pin_required')
    return p


def released_row(p=None):
    row = dict((p or plan())['original_row'])
    row.update(state='recovery_required', active_slot=None)
    return row


def quote(value):
    require(isinstance(value, str) and '\x00' not in value, 'sql_string')
    return "'" + value.replace("'", "''") + "'"


def disposition_sql(evidence):
    """One INSERT is the entire write transaction, including its CAS trigger."""
    p = plan()
    require(evidence.get('version') == VERSION and evidence.get('plan_sha256') == identity(p)
        and evidence.get('original_row_identity') == p['original_row_identity'], 'evidence_plan')
    values = [VERSION, p['original_row']['job_id'], encoded(p['original_row']).decode(),
              encoded(evidence).decode(), identity(evidence)]
    return ('INSERT INTO ' + TABLE + ' (version,job_id,original_row_json,evidence_json,evidence_sha256) VALUES ('
            + ','.join(quote(v) for v in values) + ') ON CONFLICT(job_id) DO NOTHING;\n')


def check_snapshot(snapshot, evidence):
    """Validate either exact pre-state or exact immutable completed state."""
    p = plan(); rows, controls, active, tombstones = snapshot
    require(len(rows) == 1 and len(controls) == 1, 'service_inventory')
    require(controls[0]['cached_enabled'] == 1 and controls[0]['new_paid_enabled'] == 0,
            'new_paid_must_be_off')
    if not tombstones:
        require(rows[0] == p['original_row'] and active == [{'job_id': rows[0]['job_id']}],
                'original_row_or_active_owner_changed')
        return False
    require(len(tombstones) == 1, 'duplicate_tombstone')
    saved = tombstones[0]
    expected = {'version': VERSION, 'job_id': p['original_row']['job_id'],
        'original_row_json': encoded(p['original_row']).decode(),
        'evidence_json': encoded(evidence).decode(), 'evidence_sha256': identity(evidence)}
    require({k: saved.get(k) for k in expected} == expected
        and rows[0] == released_row(p) and not active, 'tombstone_or_released_row_conflict')
    return True


def trusted_run(api, run_id, *, expected=None, path=existing.WORKFLOW, head=None):
    run = json.loads(api('actions/runs/' + str(run_id)))
    events = ('push', 'workflow_dispatch') if path == DEPLOY_WORKFLOW else ('workflow_dispatch', 'repository_dispatch')
    require(run.get('id') == int(run_id) and run.get('path') == path
        and run.get('head_branch') == 'main' and run.get('event') in events
        and run.get('status') == 'completed' and run.get('conclusion') in ('success', 'failure')
        and type(run.get('run_attempt')) is int and run['run_attempt'] > 0
        and (head is None or run.get('head_sha') == head)
        and (expected is None or all(run.get(k) == v for k, v in expected.items())), 'terminal_run_identity')
    return {k: run[k] for k in ('id', 'run_attempt', 'path', 'head_branch', 'head_sha', 'event', 'status', 'conclusion')}


def download(api, expected, run):
    artifact = json.loads(api('actions/artifacts/' + str(expected['id'])))
    require(all(artifact.get(k) == v for k, v in expected.items()) and artifact.get('expired') is False
        and artifact.get('workflow_run', {}).get('id') == run['id']
        and artifact['workflow_run'].get('head_sha') == run['head_sha']
        and re.fullmatch('sha256:[a-f0-9]{64}', artifact.get('digest', '')), 'artifact_identity')
    raw = api('actions/artifacts/' + str(artifact['id']) + '/zip')
    require(isinstance(raw, bytes) and len(raw) <= existing.STATE_LIMIT
        and 'sha256:' + existing.sha(raw) == artifact['digest'], 'artifact_digest')
    return raw


def artifact_identity(value):
    return {k: value[k] for k in ('id', 'name', 'digest')}


def owner_inventory(api):
    # No active or queued spending owner may race this one-time service change.
    for status in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
        page = json.loads(api('actions/workflows/team-recommender-offline.yml/runs?status=' + status + '&per_page=100'))
        require(page.get('total_count') == 0 and page.get('workflow_runs') == [], 'another_executor_' + status)
    artifacts = []
    for page_number in range(1, 101):
        rows = json.loads(api(f'actions/artifacts?per_page=100&page={page_number}'))['artifacts']
        artifacts.extend(r for r in rows if r['name'].startswith(existing.PREFIX + '-'))
        if len(rows) < 100:
            break
    else:
        raise ConfigurationFailure('service_disposition_artifact_history_bound')
    reservations = [a for a in artifacts if '-reservation-' in a['name']]
    require(reservations, 'missing_owner')
    latest = latest_reservation(reservations)
    matching = [a for a in artifacts if a['name'] == latest['name'].replace('-reservation-', '-state-')]
    require(len(matching) == 1 and not matching[0]['expired'], 'latest_complete_checkpoint_required')
    return latest, matching[0]


def validate_descendant(baseline, current):
    """Authenticated snapshots, with every baseline file and history retained."""
    p = plan()
    old_cp = json.loads((baseline/'checkpoint.json').read_bytes())
    new_cp = json.loads((current/'checkpoint.json').read_bytes())
    require(existing.sha((baseline/'ledger.json').read_bytes()) == p['baseline_ledger_sha256']
        and existing.sha((baseline/'checkpoint.json').read_bytes()) == p['baseline_checkpoint_sha256'], 'baseline_hash')
    old = existing.ExperimentLedger(baseline/'ledger.json').read()
    new = existing.ExperimentLedger(current/'ledger.json').read()
    for key in ('requests', 'events'):
        require(new[key][:len(old[key])] == old[key], 'owner_history_prefix')
    old_counts = old_cp['phase2_token_preflight']['rows']
    new_counts = iteration2.check_counts(current)
    require(new_counts[:len(old_counts)] == old_counts
        and all(r.get('status') == 'complete' for r in new_counts[len(old_counts):]), 'count_history_or_uncertainty')
    require(all(r.get('status') in ('valid', 'failed') and r.get('usage') is not None
        for r in new['requests'][len(old['requests']):]), 'new_unknown_request')
    for name, digest in old_cp['files'].items():
        if name != 'ledger.json':
            require(new_cp['files'].get(name) == digest, 'baseline_file_changed')
    completion.history(new); iteration2.history(new)
    recovery.validate_local(current)
    accounting.validate(new, require=True); accounting.validate_counts(new, new_counts)
    require(existing.sha(recovery.receipt_path(current).read_bytes()) == p['accounting_receipt_sha256'],
            'accounting_receipt_changed')
    return {'ledger_sha256': existing.sha((current/'ledger.json').read_bytes()),
        'checkpoint_sha256': existing.sha((current/'checkpoint.json').read_bytes()),
        'requests': len(new['requests']), 'events': len(new['events']), 'native_counts': len(new_counts),
        'permanent_hold': accounting.exposure(new), 'baseline_files_preserved': True}


def accounting_evidence(api, temporary):
    p = plan()
    trusted_run(api, accounting.plan()['failed']['run']['id'], expected=accounting.plan()['failed']['run'])
    closed = trusted_run(api, p['accounting_run']['id'], expected=p['accounting_run'])
    download(api, p['accounting_state_artifact'], closed)  # Verify original successful disposition evidence too.
    baseline_run = trusted_run(api, p['baseline_run']['id'], expected=p['baseline_run'])
    baseline = temporary/'baseline'
    existing.unpack_state(download(api, p['baseline_state_artifact'], baseline_run), baseline)
    reservation, state = owner_inventory(api)
    run = trusted_run(api, state['workflow_run']['id'])
    require(reservation['workflow_run']['id'] == run['id'] and reservation['workflow_run']['head_sha'] == run['head_sha'],
            'latest_reservation_owner')
    _, reserved = recovery._reservation(download(api, artifact_identity(reservation), run))
    require(reserved.get('authorization_id') == accounting.OWNER and str(reserved.get('run_id')) == str(run['id'])
        and str(reserved.get('attempt')) == str(run['run_attempt']) and reserved.get('code_sha') == run['head_sha'],
        'latest_reservation_record')
    current = temporary/'current'
    existing.unpack_state(download(api, artifact_identity(state), run), current)
    cp = json.loads((current/'checkpoint.json').read_bytes())
    require(str(cp['run_id']) == str(run['id']) and str(cp['attempt']) == str(run['run_attempt'])
        and cp['code_sha'] == run['head_sha'], 'latest_checkpoint_owner')
    return {'run': run, 'state_artifact': artifact_identity(state),
        'reservation_artifact': artifact_identity(reservation), **validate_descendant(baseline, current)}


def active_deployment(value):
    rows = value.get('deployments', [])
    require(rows and all(isinstance(r.get('created_on'), str) and r.get('id') for r in rows), 'deployment_inventory')
    rows = sorted(rows, key=lambda r: r['created_on'])
    require(len(rows) < 2 or rows[-1]['created_on'] != rows[-2]['created_on'], 'ambiguous_deployment')
    versions = rows[-1].get('versions', [])
    require(versions and all(type(v.get('percentage')) in (int, float) and 0 <= v['percentage'] <= 100 for v in versions),
            'deployment_weights')
    serving = [v for v in versions if v['percentage'] > 0]
    require(len(serving) == 1 and serving[0]['percentage'] == 100, 'mixed_worker_versions')
    return rows[-1]['id'], serving[0]['version_id']


def live_serving(cf, proof, configuration):
    worker = plan()['worker']; prefix = 'workers/scripts/' + worker
    before = active_deployment(cf(prefix + '/deployments'))
    require(before == (proof['deployment_id'], proof['version_id']), 'serving_deployment_changed')
    version = cf(prefix + '/versions/' + before[1])
    resources = version['resources']; runtime = dict(resources['script_runtime']); runtime.setdefault('exports', {})
    bindings = []
    for original in resources['bindings']:
        binding = dict(original)
        require(binding.get('type') != 'secret_text' or set(binding) == {'type', 'name'}, 'secret_metadata')
        if binding.get('type') == 'd1' and 'database_id' in binding:
            require(binding['database_id'] == binding['id'], 'd1_alias_conflict'); del binding['database_id']
        bindings.append(binding)
    # The authenticated JS receipt sorts names with localeCompare (not Python's
    # code-point order). Preserve its proven ordering; still compare every
    # binding field, including unknown/missing bindings, without lossy sorting.
    require(identity(configuration) == proof['configuration_sha256']
        and len({b['name'] for b in bindings}) == len(bindings)
        and len({b['name'] for b in configuration['bindings']}) == len(configuration['bindings'])
        and runtime == configuration['runtime']
        and {b['name']: b for b in bindings} == {b['name']: b for b in configuration['bindings']},
        'live_configuration_changed')
    content = cf('workers/workers/' + worker + '/versions/' + before[1] + '?include=modules')
    require(content.get('id') == before[1] and isinstance(content.get('modules'), list), 'live_module_inventory')
    hashes = {}
    for module in content['modules']:
        name = module.get('name', '')
        require(name and '/' not in name and '\\' not in name and name not in hashes
            and module.get('content_type') == 'application/javascript+module', 'live_module_shape')
        raw = base64.b64decode(module['content_base64'], validate=True)
        hashes[name] = existing.sha(raw)
    require(hashes == proof['module_hashes'] and hashes, 'live_module_mismatch')
    subdomain = cf(prefix + '/subdomain'); schedules = cf(prefix + '/schedules')
    routes = cf('workers/services/' + worker + '/environments/production/routes?show_zonename=true')
    domains = cf('workers/domains/records?page=0&per_page=5&service=' + worker + '&environment=production')
    routing = {'workers_dev': subdomain['enabled'], 'previews_enabled': subdomain['previews_enabled'],
        'crons': sorted(s['cron'] for s in schedules['schedules']), 'routes': routes, 'domains': domains}
    require(routing == proof['routing'] and active_deployment(cf(prefix + '/deployments')) == before,
            'live_routing_or_deployment_changed')


def serving_evidence(api, cf, deployment_run, head):
    run = trusted_run(api, deployment_run, path=DEPLOY_WORKFLOW, head=head)
    require(run['conclusion'] == 'success' and run['event'] in ('push', 'workflow_dispatch'), 'successful_deployment_required')
    artifacts = json.loads(api('actions/runs/' + str(deployment_run) + '/artifacts?per_page=100'))
    require(artifacts['total_count'] < 100, 'deployment_artifact_bound')
    candidates = [a for a in artifacts['artifacts'] if a['name'] == 'contextual-intake-deployment-' + str(deployment_run)]
    require(len(candidates) == 1, 'deployment_receipt_required')
    artifact = artifact_identity(candidates[0]); raw = download(api, artifact, run)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        require(len(files) == 2 and {f.filename for f in files} == {'intake-before.json', 'intake-before-verified.json'}
            and sum(f.file_size for f in files) < 131072, 'deployment_receipt_archive')
        proof = json.loads(archive.read('intake-before-verified.json'))
        configuration = json.loads(archive.read('intake-before.json'))['configuration']
    require(proof['protected_sha'] == head and proof.get('public_recommender_activation') is False
        and proof['method'] == 'authenticated-active-modules-runtime-bindings-routes-and-triggers-vs-protected-inputs'
        and proof['declared_configuration_sha256'] == identity(json.loads((ROOT/WORKER_CONFIG).read_bytes())),
        'protected_deployment_proof')
    live_serving(cf, proof, configuration)
    return {'run': run, 'artifact': artifact, 'proof': proof, 'configuration': configuration}


def protected_checkout(api, git=None):
    git = git or (lambda args: subprocess.check_output(['git', *args], cwd=ROOT, timeout=30).decode().strip())
    head = json.loads(api('git/ref/heads/main'))['object']['sha']
    branch = json.loads(api('branches/main'))
    require(branch.get('protected') is True and branch.get('commit', {}).get('sha') == head, 'main_protection_required')
    require(re.fullmatch('[a-f0-9]{40}', head) and git(['rev-parse', 'HEAD']) == head
        and git(['status', '--porcelain', '--untracked-files=no']) == '', 'clean_protected_main_required')
    require(existing.sha((ROOT/CALLBACK_SOURCE).read_bytes()) == plan()['callback_guard_source_sha256'],
            'deployed_callback_guard_source_required')
    return head


def prepare(api, cf, deployment_run, temporary, *, git=None):
    p = plan(); head = protected_checkout(api, git)
    serving = serving_evidence(api, cf, deployment_run, head)
    owner = accounting_evidence(api, temporary)
    return {'version': VERSION, 'plan_sha256': identity(p), 'protected_sha': head,
        'original_row_identity': p['original_row_identity'], 'accounting_event_identity': p['accounting_event_identity'],
        'accounting_receipt_sha256': p['accounting_receipt_sha256'], 'owner': owner, 'serving': serving,
        'new_provider_requests': 0, 'new_native_counts': 0, 'new_allowance': 0,
        'scientific_result_recovered': False, 'public_activation': False, 'recurring_paid_usage': False}


def snapshot_sql():
    p = plan(); job = quote(p['original_row']['job_id']); release = quote(p['original_row']['release_id'])
    return (f'SELECT * FROM contextual_validation_jobs WHERE job_id={job};\n'
        f'SELECT * FROM contextual_trial_controls WHERE release_id={release};\n'
        'SELECT job_id FROM contextual_validation_jobs WHERE active_slot IS NOT NULL ORDER BY job_id;\n'
        f'SELECT * FROM {TABLE} WHERE job_id={job};\n')


def schema_sql():
    return "SELECT name,sql FROM sqlite_master WHERE name LIKE 'contextual_service_disposition%' ORDER BY name;"


def expected_schema():
    with closing(sqlite3.connect(':memory:')) as db, db:
        db.row_factory = sqlite3.Row
        for name in ('0005_contextual_validation_jobs.sql', '0006_contextual_trial_controls.sql', MIGRATION.name):
            db.executescript((MIGRATION.parent/name).read_text())
        return [dict(row) for row in db.execute(schema_sql())]


class Wrangler:
    def __init__(self, cli):
        self.cli = Path(cli).resolve()
        require(self.cli.is_file() and self.cli.name in ('wrangler.js', 'cli.js'), 'existing_wrangler_cli_required')
        self.node = shutil.which('node')
        require(self.node, 'node_required')

    def query(self, sql):
        require(len(sql.encode()) <= 20000, 'sql_command_bound')
        # --file uses Wrangler's bulk database-import path, which cannot return
        # SELECT rows. A direct argument (no shell) uses the bounded query API.
        command = [self.node, str(self.cli), 'd1', 'execute', plan()['database_name'], '--remote',
                   '--config', str(ROOT/WORKER_CONFIG), '--command', sql, '--json']
        try:
            raw = subprocess.check_output(command, cwd=ROOT, timeout=60, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            raise ConfigurationFailure('service_disposition_d1_command_failed') from error
        rows = json.loads(raw)
        require(isinstance(rows, list) and rows and all(r.get('success') is True for r in rows), 'd1_response')
        return [r['results'] for r in rows]

    def snapshot(self):
        require(self.query(schema_sql()) == [expected_schema()], 'deployed_disposition_schema_required')
        result = self.query(snapshot_sql())
        require(len(result) == 4, 'd1_snapshot_shape')
        return result


def cloudflare_api(path):
    token = os.environ.get('CLOUDFLARE_API_TOKEN')
    if not token:
        # Reuse only the existing Wrangler login. The preceding read-only D1
        # query lets Wrangler perform its normal refresh, without exposing it.
        candidates = [Path(os.environ.get('APPDATA', ''))/'xdg.config/.wrangler/config/default.toml',
                      Path.home()/'.config/.wrangler/config/default.toml']
        config = next((p for p in candidates if p.is_file()), None)
        require(config is not None, 'existing_cloudflare_credentials_required')
        token = tomllib.loads(config.read_text()).get('oauth_token')
    require(token, 'existing_cloudflare_credentials_required')
    url = 'https://api.cloudflare.com/client/v4/accounts/' + plan()['account_id'] + '/' + path
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
        'User-Agent': 'FundingFinder-Exact-Service-Disposition/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, 'cloudflare_response_bound')
    value = json.loads(raw)
    require(value.get('success') is True and value.get('result') is not None, 'cloudflare_read_failed')
    return value['result']


def execute_prepared(evidence, store, *, execute=False, revalidate=lambda: None):
    before = store.snapshot()
    already = check_snapshot(before, evidence)
    if not execute or already:
        return {'status': 'already_disposed' if already else 'prepared_only', 'before': before,
                'remote_mutation_submitted': False}
    revalidate()
    # The database trigger validates the complete pre-state again in the same
    # atomic statement, including paidOFF, after all external proof checks.
    store.query(disposition_sql(evidence))
    after = store.snapshot()
    require(check_snapshot(after, evidence), 'postwrite_verification')
    return {'status': 'disposed', 'before': before, 'after': after, 'remote_mutation_submitted': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment-run', required=True, type=int)
    parser.add_argument('--wrangler-cli', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    store = Wrangler(args.wrangler_cli)
    # Read-only query first refreshes an existing Wrangler sign-in if needed.
    store.snapshot()
    with tempfile.TemporaryDirectory(prefix='contextual-slot-proof-') as temporary:
        evidence = prepare(existing.api, cloudflare_api, args.deployment_run, Path(temporary))
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_json(args.output/'prepared-evidence.json', evidence)
        (args.output/'exact-disposition.sql').write_text(disposition_sql(evidence), encoding='utf-8', newline='\n')

        def revalidate():
            require(protected_checkout(existing.api) == evidence['protected_sha'], 'head_changed')
            reservation, state = owner_inventory(existing.api)
            require(artifact_identity(state) == evidence['owner']['state_artifact']
                and artifact_identity(reservation) == evidence['owner']['reservation_artifact'], 'owner_changed')
            live_serving(cloudflare_api, evidence['serving']['proof'], evidence['serving']['configuration'])

        result = execute_prepared(evidence, store, execute=args.execute, revalidate=revalidate)
        atomic_json(args.output/'receipt.json', {'version': VERSION, 'evidence_sha256': identity(evidence), **result})
        print(json.dumps({'status': result['status'], 'receipt': str(args.output/'receipt.json'),
                          'provider_calls': 0, 'native_count_calls': 0}))


if __name__ == '__main__':
    main()
