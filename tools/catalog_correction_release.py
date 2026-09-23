"""The fixed catalog repair inside the ordinary immutable refresh lifecycle.

Only the existing trusted team executor dispatches provider requests. This
bridge reads authenticated artifacts, assembles safe public bytes, and submits
three distinct, checkpointed workflow selectors. It never calls a provider.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from tools import catalog_smoke_receipt as smoke
from tools import catalog_source_correction as source
from tools import catalog_correction_policy as policy
from tools import release_candidate as release
from tools.offline_spend import atomic_json, encoded, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'catalog-correction-release-v1'
DISPATCH_PREFIX = 'catalog-correction-dispatch-'
FINALIZE_PREFIX = 'catalog-correction-finalize-'


def require(ok, why):
    smoke.require(ok, 'release_'+why)


def refresh_environment():
    require(os.environ.get('GITHUB_REPOSITORY') == smoke.existing.REPOSITORY
        and os.environ.get('GITHUB_REF') == 'refs/heads/main'
        and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        and os.environ.get('GITHUB_WORKFLOW_REF') == smoke.existing.REPOSITORY+'/'+smoke.REFRESH+'@refs/heads/main',
        'protected_manual_refresh_required')
    return {'run_id': int(os.environ['GITHUB_RUN_ID']), 'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
        'head_sha': os.environ['GITHUB_SHA']}


def output(value):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as stream:
            for key, item in value.items():
                if isinstance(item, (str, int)):
                    require('\n' not in str(item) and '\r' not in str(item), 'single_line_output')
                    stream.write(f'{key}={item}\n')


def latest_owner(destination, *, api=smoke.existing.api):
    inventory = smoke.artifacts(api)
    from tools.team_recommender_checkpoint import latest_reservation
    reservations = [a for a in inventory if a.get('name', '').startswith(smoke.existing.PREFIX+'-reservation-')]
    require(bool(reservations), 'existing_owner_required')
    reservation = latest_reservation(reservations)
    run = smoke.trusted_run(reservation['workflow_run']['id'], smoke.existing.WORKFLOW, allow_failed=True, api=api)
    name = f"{smoke.existing.PREFIX}-state-{run['id']}-{run['run_attempt']}"
    require(reservation['name'] == name.replace('-state-', '-reservation-'), 'latest_owner_attempt')
    matches = [a for a in inventory if a.get('name') == name]
    require(len(matches) == 1, 'latest_owner_state_required')
    active = smoke.json_value(api('actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100'))['workflow_runs']
    require(not any(r.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested') for r in active), 'active_owner')
    raw, artifact = smoke.authenticated_zip(matches[0]['id'], name, run, matches[0].get('digest'), api=api)
    destination = Path(destination); require(not destination.exists(), 'new_owner_copy')
    smoke.existing.unpack_state(raw, destination); cp = smoke.validate_checkpoint(destination)
    require(str(cp['run_id']) == str(run['id']) and str(cp['attempt']) == str(run['run_attempt']) and cp['code_sha'] == run['head_sha'],
        'owner_checkpoint_identity')
    ledger = smoke.existing.ExperimentLedger(destination/'ledger.json').read(); policy.history(ledger); policy.counts(destination)
    return {'run': run, 'artifact': artifact, 'ledger_sha256': smoke.existing.sha((destination/'ledger.json').read_bytes()),
        'checkpoint_sha256': smoke.existing.sha((destination/'checkpoint.json').read_bytes())}


def prepared_inputs(work):
    path = Path(work)/'inputs'
    return source.verify_inputs(path) if path.exists() else source.prepare_inputs(path)


def import_export(work, *, api=smoke.existing.api):
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    prepared = prepared_inputs(work)
    owner = latest_owner(work/'state', api=api)
    from tools.team_recommender_checkpoint import latest_reservation
    exports = [a for a in smoke.artifacts(api) if re.fullmatch('catalog-correction-export-[1-9][0-9]*-[1-9][0-9]*', a.get('name', ''))]
    require(bool(exports), 'safe_vector_export_missing')
    selected = latest_reservation(exports); match = re.fullmatch('catalog-correction-export-([1-9][0-9]*)-([1-9][0-9]*)', selected['name'])
    run = smoke.trusted_run(int(match[1]), smoke.existing.WORKFLOW, attempt=int(match[2]), api=api)
    raw, artifact = smoke.authenticated_zip(selected['id'], selected['name'], run, selected.get('digest'), api=api)
    exported = work/'export'; require(not exported.exists(), 'new_safe_export_copy'); smoke.unpack_public(raw, exported)
    manifest = source.verify_export(exported, work/'state', prepared['root'])
    anchor = {'owner': owner, 'correction_export': {'owner_run': run['id'], 'artifact_id': artifact['id'],
        'artifact_digest': artifact['digest'], 'export_sha256': smoke.existing.sha((exported/'export.json').read_bytes())}}
    atomic_json(work/'import.json', anchor)
    return prepared, manifest, anchor


def materialize_sources(root, prepared, export_root, *, command=subprocess.run):
    """Recompute only deterministic public projections around the retained data."""
    root, export_root = Path(root), Path(export_root)
    original_root = prepared['candidate_root']; original = release.load(original_root, source.plan()['candidate_id'])
    for name in original['generation_files']:
        target = release.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original_root/'files'/name, target)
    for name in ('data/search-v2-release.json', 'workers/search-voyage-proxy/generated/corpus-allowlist.json'):
        shutil.copyfile(original_root/'files'/name, root/name)
    from scripts.sources.merge import save_catalog
    catalog = source.public_catalog(json.loads((Path(prepared['root'])/'corrected-catalog.json').read_bytes()))
    save_catalog(catalog, root/'data/opportunities.js')
    shutil.copyfile(export_root/'corrected-source-cache.json', root/'data/source_records.json')
    for name in source.VECTOR_FILES:
        shutil.copyfile(export_root/name, root/name)
    from scripts.build_changes import write_change_feed
    from scripts.build_feeds import build_feeds
    from scripts.sources.merge import load_catalog
    write_change_feed(load_catalog(original_root/'files/data/opportunities.js'), catalog, root/'feeds', as_of=date.fromisoformat(source.plan()['as_of']))
    build_feeds(catalog, root/'feeds', as_of=date.fromisoformat(source.plan()['as_of']))
    # Existing pure commands update only references/statistics/package metadata.
    command([sys.executable, '-m', 'scripts.update_catalog_docs'], cwd=root, check=True)
    command([sys.executable, '-m', 'tools.release_coverage'], cwd=root, check=True)
    previous = json.loads((original_root/'files/workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())['previous']
    require(isinstance(previous, dict), 'original_published_previous_required')
    publication = {'schema_version': 1, 'current_corpus_sha256': previous['corpus_sha256'],
        'model': previous['model'], 'dimension': previous['dimension'], 'model_space_fingerprint': previous['model_space_fingerprint']}
    with tempfile.TemporaryDirectory(prefix='catalog-previous-') as temp:
        path = Path(temp)/'published.json'; atomic_json(path, publication)
        command([shutil.which('node') or 'node', 'tools/build_search_release_package.mjs', '--write', '--published-release', str(path)], cwd=root, check=True)
    actual_previous = json.loads((root/'workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())['previous']
    require(encoded(actual_previous) == encoded(previous), 'published_previous_generation_unchanged')
    affected = source.VECTOR_FILES | {'data/opportunities.js', 'data/catalog-metadata.js', 'data/source_records.json',
        'evaluation/release_coverage.json', 'README.md', 'PROJECT.md'} | {n for n in original['generation_files'] if n.startswith('feeds/')}
    release.verify_files(root, {n: h for n, h in original['generation_files'].items() if n not in affected})
    return original


def create(work, bundle, *, root=ROOT, api=smoke.existing.api):
    refresh_environment(); work, bundle = Path(work), Path(bundle)
    # A workflow rerun must resume its exact persisted standard candidate;
    # restore_generation_checkpoint supplies this before reaching this helper.
    require(not bundle.exists(), 'immutable_candidate_destination')
    prepared, exported, anchor = import_export(work, api=api)
    materialize_sources(root, prepared, work/'export')
    receipt = {'version': source.VERSION, 'source_plan_sha256': smoke.existing.sha(source.CONFIG.read_bytes()),
        'spending_plan_sha256': policy.PLAN_SHA, 'export_sha256': anchor['correction_export']['export_sha256'],
        'owner_run': anchor['correction_export']['owner_run'], 'original_candidate_id': source.plan()['candidate_id']}
    manifest = release.create_source_correction(root, bundle, prepared['candidate_root'], receipt, work/'export')
    output({'candidate_id': manifest['candidate_id']}); return manifest


def candidate_anchor(bundle, *, api=smoke.existing.api):
    manifest = release.load(bundle)
    require(manifest.get('source_correction', {}).get('version') == source.VERSION
        and manifest['source_correction']['source_plan_sha256'] == smoke.existing.sha(source.CONFIG.read_bytes())
        and manifest['source_correction']['spending_plan_sha256'] == policy.PLAN_SHA, 'fixed_candidate_required')
    run_id = int(os.environ['CANDIDATE_RUN'])
    run = smoke.trusted_run(run_id, smoke.REFRESH, terminal=False, allow_failed=True, api=api)
    matches = [a for a in smoke.artifacts(api) if a.get('name') == 'candidate-'+manifest['candidate_id']
        and a.get('workflow_run', {}).get('id') == run_id]
    require(len(matches) == 1, 'exact_standard_candidate_artifact')
    raw, artifact = smoke.authenticated_zip(matches[0]['id'], matches[0]['name'], run, matches[0].get('digest'), api=api)
    with tempfile.TemporaryDirectory(prefix='catalog-candidate-proof-') as temp:
        smoke.unpack_public(raw, temp); restored = release.load(temp, manifest['candidate_id'])
        require(encoded(restored) == encoded(manifest), 'candidate_artifact_manifest')
    return manifest, {'candidate_id': manifest['candidate_id'], 'artifact_run': run_id,
        'artifact_id': artifact['id'], 'artifact_digest': artifact['digest'],
        'manifest_sha256': smoke.existing.sha((Path(bundle)/release.MANIFEST).read_bytes())}


def context(work, bundle, reports, *, api=smoke.existing.api, node_call=smoke.node):
    refresh = refresh_environment(); work, bundle, reports = Path(work), Path(bundle), Path(reports)
    prepared, exported, anchor = import_export(work, api=api)
    manifest, candidate = candidate_anchor(bundle, api=api)
    require(manifest['source_correction']['export_sha256'] == anchor['correction_export']['export_sha256'], 'same_vector_export')
    deployments = json.loads((reports/'deployments-after.json').read_bytes())
    rows = deployments.get('deployments', deployments) if isinstance(deployments, dict) else deployments
    # The existing classifier owns active single-version traffic validation.
    script = "import{activeDeployment}from'./tools/classify_worker_deployment.mjs';import{readFileSync}from'node:fs';console.log(JSON.stringify(activeDeployment(JSON.parse(readFileSync(0,'utf8')))));"
    active = json.loads(subprocess.check_output([shutil.which('node') or 'node', '--input-type=module', '-e', script],
        input=encoded(rows), cwd=ROOT, timeout=30))
    candidate_proof = {k: candidate[k] for k in ('candidate_id', 'artifact_id', 'artifact_digest', 'manifest_sha256')}
    candidate_proof['code_sha'] = refresh['head_sha']
    overrides = {name: (bundle/'files'/name).read_bytes().decode('utf8') for name in (
        'workers/search-voyage-proxy/generated/corpus-allowlist.json', 'workers/search-voyage-proxy/wrangler.jsonc')}
    proof = node_call('candidate-proof', {'candidate': candidate_proof, 'deployment': active['deployment']['id'],
        'version': active['versionId'], 'candidateInputs': overrides})
    allowlist = json.loads((bundle/'files/workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())
    value = {'version': smoke.CONTEXT_VERSION, 'source_plan_sha256': smoke.existing.sha(source.CONFIG.read_bytes()),
        'refresh': refresh, 'candidate': candidate, 'correction_export': anchor['correction_export'],
        'generations': {'current': allowlist['current'], 'previous': allowlist['previous']}, 'serving_proof': proof}
    source.validate_context_packet(value, bundle, work/'export', work/'state', prepared['root'])
    path = work/'context/context.json'; require(not path.exists(), 'immutable_context'); atomic_json(path, value)
    atomic_json(reports/'worker-after.json', {**proof, 'deploy_required': False, 'required_fingerprint': manifest['worker_fingerprint']})
    name = f"{smoke.CONTEXT_PREFIX}{candidate['candidate_id']}-{refresh['run_id']}-{refresh['run_attempt']}"
    output({'context_artifact': name, 'context_path': str(path)}); return value


def run_list(api=smoke.existing.api):
    rows = smoke.json_value(api('actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100'))['workflow_runs']
    require(isinstance(rows, list), 'trusted_run_inventory')
    return rows


def plan_smoke(name, work, bundle, reports, *, api=smoke.existing.api):
    refresh = refresh_environment(); require(name in smoke.NAMES, 'named_smoke')
    work, reports = Path(work), Path(reports); reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='catalog-smoke-plan-') as temp:
        owner = latest_owner(Path(temp)/'state', api=api)
        state = Path(temp)/'state'; prepared = prepared_inputs(work)
        verified = smoke.load_context(state, prepared['root'], api=api)
        manifest = release.load(bundle)
        require(verified['context']['candidate']['candidate_id'] == manifest['candidate_id'], 'dispatch_candidate')
        rows = smoke.existing.ExperimentLedger(state/'ledger.json').read()['requests']
        current = [r for r in rows if r.get('purpose') == policy.operation(name)['purpose']]
        finalize_only = False
        if current:
            from tools.catalog_correction_executor import CatalogRunner, input_body
            CatalogRunner(state, prepared['root']).cached(name, input_body(prepared['root'], name))
            finalize_only = name == smoke.NAMES[-1] and (not (state/smoke.receipt_path()).exists()
                or owner['run']['conclusion'] != 'success')
        if current and not finalize_only:
            result = {'status': 'cached', 'name': name, 'request_id': current[0]['id'], 'owner_run': owner['run']['id']}
        else:
            all_runs = run_list(api)
            require(not any(r.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested') for r in all_runs), 'exclusive_smoke_dispatch')
            prefix = FINALIZE_PREFIX if finalize_only else DISPATCH_PREFIX
            previous = [a for a in smoke.artifacts(api) if re.fullmatch(re.escape(prefix+name)+'-[1-9][0-9]*-[1-9][0-9]*', a.get('name', ''))]
            if previous:
                from tools.team_recommender_checkpoint import latest_reservation
                selected = latest_reservation(previous)
                attempt = int(selected['name'].rsplit('-', 1)[1])
                run = smoke.trusted_run(selected['workflow_run']['id'], smoke.REFRESH, terminal=False, allow_failed=True, attempt=attempt, api=api)
                raw, _ = smoke.authenticated_zip(selected['id'], selected['name'], run, selected.get('digest'), api=api)
                with tempfile.TemporaryDirectory(prefix='catalog-dispatch-origin-') as old:
                    smoke.unpack_public(raw, old); result = json.loads((Path(old)/'intent.json').read_bytes())
                require(result['candidate_id'] == manifest['candidate_id'] and result['name'] == name
                    and result['plan_sha256'] == policy.PLAN_SHA and result.get('finalize_only') is finalize_only, 'prior_dispatch_identity')
                result = {**result, 'status': 'resume_intent'}
            else:
                require(smoke.json_value(api('git/ref/heads/main'))['object']['sha'] == refresh['head_sha'], 'protected_head_advanced')
                result = {'version': VERSION, 'status': 'new_intent', 'name': name, 'plan_sha256': policy.PLAN_SHA,
                    'finalize_only': finalize_only,
                    'refresh': refresh, 'candidate_id': manifest['candidate_id'], 'owner_run': owner['run']['id'],
                    'owner_checkpoint_sha256': owner['checkpoint_sha256'], 'baseline_run_ids': sorted(r['id'] for r in all_runs),
                    'selector': {'catalog_correction': name}}
    atomic_json(work/name/'intent.json', result)
    output({'smoke_status': result['status'], 'intent_path': str(work/name/'intent.json'),
        'intent_artifact': f"{FINALIZE_PREFIX if finalize_only else DISPATCH_PREFIX}{name}-{refresh['run_id']}-{refresh['run_attempt']}"})
    return result


def dispatch(path, payload):
    subprocess.run(['gh', 'api', '--method', 'POST', 'repos/'+smoke.existing.REPOSITORY+'/'+path, '--input', '-'],
        input=encoded(payload), check=True, timeout=60, stdout=subprocess.DEVNULL)


def run_smoke(name, work, reports, *, api=smoke.existing.api, dispatch_call=dispatch, sleep=time.sleep, maximum_polls=15):
    refresh = refresh_environment(); require(name in smoke.NAMES, 'named_smoke')
    work, reports = Path(work), Path(reports); path = work/name/'intent.json'; intent = json.loads(path.read_bytes())
    require(intent['name'] == name, 'intent_name')
    if intent['status'] == 'cached':
        atomic_json(reports/(name+'.json'), intent); return intent
    require(intent['version'] == VERSION and intent['plan_sha256'] == policy.PLAN_SHA
        and intent['selector'] == {'catalog_correction': name}, 'fixed_dispatch_intent')
    invocation = work/name/'dispatch.json'
    if intent['status'] == 'new_intent' and not invocation.exists():
        require(intent['refresh'] == refresh, 'new_intent_attempt')
        artifact_name = f"{FINALIZE_PREFIX if intent['finalize_only'] else DISPATCH_PREFIX}{name}-{refresh['run_id']}-{refresh['run_attempt']}"
        matches = [a for a in smoke.artifacts(api) if a.get('name') == artifact_name]
        require(len(matches) == 1, 'durable_dispatch_intent_required')
        run = smoke.trusted_run(refresh['run_id'], smoke.REFRESH, terminal=False, api=api)
        raw, _ = smoke.authenticated_zip(matches[0]['id'], artifact_name, run, matches[0].get('digest'), api=api)
        with tempfile.TemporaryDirectory(prefix='catalog-dispatch-proof-') as temp:
            smoke.unpack_public(raw, temp); require((Path(temp)/'intent.json').read_bytes() == path.read_bytes(), 'durable_exact_intent')
        require(smoke.json_value(api('git/ref/heads/main'))['object']['sha'] == refresh['head_sha'], 'protected_head_advanced')
        with tempfile.TemporaryDirectory(prefix='catalog-dispatch-owner-') as temp:
            state = Path(temp)/'state'; owner = latest_owner(state, api=api)
            require(owner['run']['id'] == intent['owner_run'] and owner['checkpoint_sha256'] == intent['owner_checkpoint_sha256'],
                'dispatch_owner_changed')
            if intent['finalize_only']:
                require(name == smoke.NAMES[-1], 'finalize_only_last_smoke')
                from tools.catalog_correction_executor import CatalogRunner, input_body
                inputs = prepared_inputs(work)['root']
                CatalogRunner(state, inputs).cached(name, input_body(inputs, name))
        atomic_json(invocation, {'status': 'dispatch_started', 'intent_sha256': smoke.existing.sha(path.read_bytes())})
        dispatch_call('actions/workflows/team-recommender-offline.yml/dispatches', {'ref': 'main', 'inputs': {'contextual_check': json.dumps(intent['selector'], separators=(',', ':'))}})
    selected = None
    for count in range(maximum_polls):
        new = [r for r in run_list(api) if r['id'] not in intent['baseline_run_ids']]
        require(len(new) <= 1, 'ambiguous_dispatched_run')
        if new:
            selected = new[0]
            require(selected.get('head_sha') == intent['refresh']['head_sha'] and selected.get('event') == 'workflow_dispatch', 'dispatched_run_identity')
            atomic_json(reports/(name+'.json'), {'intent': intent, 'run_id': selected['id'], 'status': selected['status']})
            if selected['status'] == 'completed':
                require(selected.get('conclusion') == 'success', 'dispatched_run_failed_no_retry')
                with tempfile.TemporaryDirectory(prefix='catalog-smoke-result-') as temp:
                    latest = latest_owner(Path(temp)/'state', api=api)
                    require(latest['run']['id'] == selected['id'], 'dispatched_run_is_owner')
                    from tools.catalog_correction_executor import CatalogRunner, input_body
                    inputs = prepared_inputs(work)['root']
                    CatalogRunner(Path(temp)/'state', inputs).cached(name, input_body(inputs, name))
                return {'status': 'accepted', 'run_id': selected['id']}
        elif intent['status'] == 'resume_intent':
            raise ValueError('Prior dispatch intent has no discoverable run; diagnosis required, no redispatch')
        if count+1 < maximum_polls:
            sleep(60)
    raise ValueError('Trusted smoke run did not complete within the bounded wait; no redispatch')


def verify_worker(bundle, reports, *, work=None):
    bundle, reports = Path(bundle), Path(reports)
    work = Path(work) if work else reports.parent/'catalog-reuse'
    inputs = prepared_inputs(work)['root']; authenticated = smoke.authenticate_owner(inputs)
    manifest = release.load(bundle); proof = authenticated['serving_proof']; candidate = proof.get('candidate', {})
    require(candidate.get('candidate_id') == manifest['candidate_id']
        and candidate.get('manifest_sha256') == smoke.existing.sha((bundle/release.MANIFEST).read_bytes())
        and proof['fingerprint'] == manifest['worker_fingerprint'], 'live_exact_candidate')
    prior = json.loads((reports/'worker-after.json').read_bytes())
    require(prior.get('required_fingerprint') == manifest['worker_fingerprint'] and prior.get('deploy_required') is False,
        'publication_worker_checkpoint')
    smoke.node('same-proof', {'before': {k: v for k, v in prior.items() if k not in ('required_fingerprint', 'deploy_required')}, 'after': proof})
    result = {**proof, 'verified': True, 'required_fingerprint': manifest['worker_fingerprint'],
        'expected_version_id': prior['version_id'], 'verified_at': release.timestamp()}
    atomic_json(reports/'worker-live.json', result); return result


def historical_smoke(manifest, reuse, work, *, api=smoke.existing.api):
    """Authenticate a completed historical purchase, without claiming it is live now."""
    require(reuse.get('version') == 'search-worker-smoke-reuse-v1' and reuse.get('status') == 'passed_reused'
        and reuse.get('original_provider_requests') == 3 and all(type(reuse.get(k)) is int and reuse[k] == 0 for k in
        ('new_provider_calls', 'new_native_counts', 'new_metered_attempts', 'new_paid_usage_microusd')), 'historical_smoke_receipt')
    run = smoke.trusted_run(reuse['authoritative_run_id'], smoke.existing.WORKFLOW, api=api)
    name = f"{smoke.existing.PREFIX}-state-{run['id']}-{run['run_attempt']}"
    raw, _ = smoke.authenticated_zip(reuse['authoritative_state_artifact_id'], name, run,
        reuse['authoritative_state_artifact_digest'], api=api)
    state = Path(work)/'state'; smoke.existing.unpack_state(raw, state); cp = smoke.validate_checkpoint(state)
    require(str(cp['run_id']) == str(run['id']) and str(cp['attempt']) == str(run['run_attempt']) and cp['code_sha'] == run['head_sha']
        and smoke.existing.sha((state/'checkpoint.json').read_bytes()) == reuse['authoritative_checkpoint_sha256']
        and smoke.existing.sha((state/'ledger.json').read_bytes()) == reuse['authoritative_ledger_sha256'], 'historical_owner_checkpoint')
    raw = (state/smoke.receipt_path()).read_bytes(); receipt = smoke.json_value(raw); expected = receipt['inputs']
    require(smoke.existing.sha(raw) == reuse['receipt_sha256'] and receipt['owner']['run_id'] == reuse['original_run_id'], 'historical_exact_aggregate')
    prepared = prepared_inputs(work); inputs = Path(prepared['root']); source.accepted_vector_packet(state, inputs)
    p = source.plan(); prior = release.load(prepared['candidate_root'], p['candidate_id'])
    previous = json.loads((prepared['candidate_root']/'files/workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())['previous']
    require(expected['worker_input_fingerprint'] == manifest['worker_fingerprint']
        and expected['current'] == {'corpus_sha256': p['corpus_sha256'], 'model_space_fingerprint': manifest['release_identity']['model_space_fingerprint']}
        and expected['previous'] == {k: previous[k] for k in ('corpus_sha256', 'model_space_fingerprint')}
        and expected['shared_passage']['passage_id'] == p['smoke_passage_id']
        and expected['shared_passage']['text_sha256'] == p['smoke_passage_sha256'], 'historical_fixed_inputs')
    require(receipt['serving_after']['candidate']['candidate_id'] == manifest['candidate_id'], 'historical_candidate_proof')
    for name, op in zip(smoke.NAMES, expected['operations'], strict=True):
        require(op['provider_body_text'] == (inputs/(name+'-provider.json')).read_bytes().decode('utf8'), 'historical_exact_provider_body')
    smoke.node('validate', {'receipt_text': raw.decode('utf8'), 'expected': expected})
    operations = smoke.accepted_operations(state, inputs, expected, serving_proof=receipt['serving_after'])
    require(encoded(operations) == encoded(receipt['operations']), 'historical_three_owned_rows')


def protected_candidates(root):
    commits = release.git(root, 'log', 'HEAD', '--format=%H', '-100', '--', 'release/candidate-source.json').splitlines()
    for commit in commits:
        manifest = smoke.json_value(subprocess.check_output(['git', '-C', str(root), 'show', commit+':release/candidate.json']))
        require(manifest.get('candidate_id') == release.digest(release.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'})),
            'protected_manifest_hash')
        yield manifest


def authenticate_report_files(directory, kind, candidate, *, api=smoke.existing.api):
    """Bind the normal release report reader's bytes to its full GitHub ZIP."""
    directories = list(Path(directory).iterdir())
    require(len(directories) == 1 and directories[0].is_dir() and re.fullmatch('[1-9][0-9]*', directories[0].name), 'report_artifact_directory')
    local = directories[0]; meta = smoke.json_value(api('actions/artifacts/'+local.name))
    match = re.fullmatch(re.escape(kind+'-'+candidate)+'-([1-9][0-9]*)', meta.get('name', ''))
    require(match is not None, 'report_artifact_name')
    run = smoke.trusted_run(meta['workflow_run']['id'], smoke.REFRESH, allow_failed=kind == 'publication', attempt=int(match[1]), api=api)
    raw, _ = smoke.authenticated_zip(meta['id'], meta['name'], run, meta.get('digest'), api=api)
    with tempfile.TemporaryDirectory(prefix='catalog-published-report-') as temp:
        smoke.unpack_public(raw, temp)
        hashes = lambda root: {p.relative_to(root).as_posix(): smoke.existing.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
        require(hashes(Path(temp)) == hashes(local), 'authenticated_release_report_bytes')


def correction_completion(root, *, api=smoke.existing.api):
    """Find an authenticated completed publication retained in protected history.

    This is a past completion fact, not evidence of current serving identity.
    Later ordinary generations may replace the current pointer and Worker.
    """
    root = Path(root); seen = set()
    from tools.plan_release import latest_report, publication_ready
    for manifest in protected_candidates(root):
        fixed = manifest.get('source_correction', {})
        if fixed.get('version') != source.VERSION or fixed.get('source_plan_sha256') != smoke.existing.sha(source.CONFIG.read_bytes()):
            continue
        if manifest.get('derived_from_candidate') != source.plan()['candidate_id']:
            continue  # Ordinary descendants retain audit lineage, not the finite repair operation.
        candidate = manifest['candidate_id']
        if candidate in seen: continue
        seen.add(candidate)
        require(candidate == release.digest(release.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
            and fixed['spending_plan_sha256'] == policy.PLAN_SHA and fixed['original_candidate_id'] == source.plan()['candidate_id'], 'protected_fixed_manifest')
        with tempfile.TemporaryDirectory(prefix='catalog-completion-') as temp:
            temp = Path(temp)
            _, publication = latest_report(smoke.existing.REPOSITORY, candidate, 'publication', temp/'publication')
            _, live = latest_report(smoke.existing.REPOSITORY, candidate, 'live', temp/'live')
            if not publication_ready(manifest, publication) or not live or live.get('verified') is not True:
                continue
            require(live.get('candidate_id') == candidate and live.get('provider_smoke') == 'success', 'complete_live_smoke_receipt')
            authenticate_report_files(temp/'publication', 'publication', candidate, api=api)
            authenticate_report_files(temp/'live', 'live', candidate, api=api)
            receipts = list((temp/'live').glob('*/catalog-smoke-reuse.json'))
            require(len(receipts) == 1, 'published_owned_smoke_evidence')
            historical_smoke(manifest, smoke.json_value(receipts[0].read_bytes()), temp/'owned', api=api)
            return manifest
    return None


def correction_complete(root, *, api=smoke.existing.api):
    return correction_completion(root, api=api) is not None


def requires_owned_smoke(bundle, *, root=ROOT):
    manifest = release.load(bundle); fixed = manifest.get('source_correction')
    if fixed is None: return False
    require(fixed.get('version') == source.VERSION and fixed.get('source_plan_sha256') == smoke.existing.sha(source.CONFIG.read_bytes())
        and fixed.get('spending_plan_sha256') == policy.PLAN_SHA, 'known_source_correction')
    completed = correction_completion(root)
    if completed is None or manifest['candidate_id'] == completed['candidate_id']:
        return True
    require(encoded(fixed) == encoded(completed['source_correction']), 'same_completed_correction_lineage')
    history = {m['candidate_id']: m for m in protected_candidates(root)}
    seen = set(); parent = manifest.get('derived_from_candidate')
    while parent and parent not in seen:
        if parent == completed['candidate_id']: return False
        seen.add(parent)
        ancestor = history.get(parent)
        require(ancestor is not None and encoded(ancestor.get('source_correction')) == encoded(fixed), 'protected_correction_descendant')
        parent = ancestor.get('derived_from_candidate')
    require(False, 'unproven_correction_descendant')


def mode(bundle):
    result = {'fixed_correction': str(requires_owned_smoke(bundle)).lower()}; output(result); return result


def plan():
    requested = os.environ.get('REQUESTED_STAGE', '')
    if requested == 'catalog-correction':
        refresh_environment()
        require(not any(os.environ.get(k) for k in ('CANDIDATE_ID', 'CANDIDATE_RUN'))
            and os.environ.get('QUALIFICATION_PILOT') != 'true', 'fixed_correction_selector')
        value = {'stage': 'catalog-correction', 'release_sha': release.git(ROOT, 'rev-parse', 'HEAD'),
            'openai': 'false', 'anthropic': 'false', 'reason': 'Exact retained source repair and seven accepted owner vectors'}
    elif requested in ('validate', 'publish', 'verify') or correction_complete(ROOT):
        from tools.plan_release import main
        return main()
    else:
        require(requested in ('', 'auto') or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch', 'ordinary_generation_waits_for_fixed_correction')
        value = {'stage': 'noop', 'release_sha': release.git(ROOT, 'rev-parse', 'HEAD'), 'openai': 'false', 'anthropic': 'false',
            'reason': 'The finite source correction has not completed authenticated publication; ordinary generation remains held'}
    atomic_json(Path(os.environ['RUNNER_TEMP'])/'release-plan.json', value); output(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'create', 'context', 'plan-smoke', 'run-smoke', 'reuse-smoke', 'verify-worker', 'mode'))
    parser.add_argument('--work', type=Path); parser.add_argument('--bundle', type=Path); parser.add_argument('--reports', type=Path)
    parser.add_argument('--name', choices=smoke.NAMES)
    args = parser.parse_args()
    if args.action == 'plan': return plan()
    if args.action == 'mode': return mode(args.bundle)
    if args.action == 'create': result = create(args.work, args.bundle)
    elif args.action == 'context': result = context(args.work, args.bundle, args.reports)
    elif args.action == 'plan-smoke': result = plan_smoke(args.name, args.work, args.bundle, args.reports)
    elif args.action == 'run-smoke': result = run_smoke(args.name, args.work, args.reports)
    elif args.action == 'verify-worker': result = verify_worker(args.bundle, args.reports, work=args.work)
    else:
        inputs = prepared_inputs(args.work)['root']; result = smoke.node('reuse', smoke.authenticate_owner(inputs))
        require(result['current_corpus_sha256'] == release.load(args.bundle)['release_identity']['current_corpus_sha256'], 'reused_release_corpus')
        atomic_json(args.reports/'catalog-smoke-reuse.json', result)
    print(json.dumps({k: v for k, v in result.items() if k in ('status', 'candidate_id', 'verified', 'run_id')}))


if __name__ == '__main__': main()
