"""Fresh, zero-provider coverage of the fixed Awards UI-only descendant.

The original aggregate and serving proof continue to identify their original
candidate.  A separate receipt proves why those exact paid inputs also cover
this narrowly bounded runtime package.
"""
from pathlib import Path

from tools import catalog_smoke_receipt as smoke
from tools import release_candidate as release
from tools.offline_spend import atomic_json, encoded, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'catalog-awards-runtime-smoke-coverage-v1'
SCRIPT = 'assets/institutional-intelligence-snapshots.js'
PAGE = 'funded_awards.html'
DELTAS = {SCRIPT, PAGE}
ZERO_FIELDS = ('new_provider_calls', 'new_native_counts', 'new_metered_attempts', 'new_paid_usage_microusd')


def require(ok, why):
    smoke.require(ok, 'runtime_smoke_' + why)


def _bridge():
    # The ordinary bridge imports this module only at its routing boundary.
    from tools import catalog_correction_release
    return catalog_correction_release


def _blob(root, revision, name):
    return _bridge()._protected_blob(root, revision, name)


def _worker_inputs(root, manifest):
    policy = smoke.json_value(_blob(root, 'HEAD', release.POLICY))
    names = release.paths(root, policy['worker'])
    hashes = {name: release.digest(_blob(root, 'HEAD', name)) for name in names}
    require(all(manifest['files'].get(name) == value for name, value in hashes.items()), 'protected_worker_bytes')
    hashes['@toolchain'] = release.digest(release.encoded(policy['worker_toolchain']))
    require(release.digest(release.encoded(hashes)) == manifest['worker_fingerprint'], 'complete_worker_inputs')
    return hashes


def classify(bundle, *, root=ROOT):
    """Pure classification; an unsupported fixed descendant never falls back."""
    root, bundle = Path(root), Path(bundle)
    manifest = release.load(bundle)
    if manifest.get('source_correction') is None:
        return None
    completed = _bridge().completion_record(root)
    if completed is None:
        from tools import catalog_projection_recovery as projection
        require(manifest.get('derived_from_candidate') != projection.plan()['candidate_id'], 'protected_completion_required')
        return None
    record, anchor = completed
    if manifest['candidate_id'] == anchor['candidate_id']:
        return None
    if all(manifest.get('files', {}).get(name) == anchor['files'].get(name) for name in DELTAS):
        # Unrelated, already supported team/runtime descendants retain their
        # ordinary protected-lineage route. This helper owns only this UI delta.
        return None
    if manifest.get('derived_from_candidate') != anchor['candidate_id']:
        history = {value['candidate_id']: value for value in _bridge().protected_candidates(root,
            anchor_sha=record['publication']['commit'])}
        parent = history.get(manifest.get('derived_from_candidate'))
        require(parent is not None and encoded(parent.get('source_correction')) == encoded(anchor['source_correction'])
            and encoded(parent.get('original_generation')) == encoded(anchor['original_generation'])
            and all(parent['files'].get(name) == manifest['files'].get(name) for name in DELTAS),
            'immediate_protected_parent')
        # A later protected successor which merely retains the already-published
        # UI uses the established descendant guard; it is not this correction.
        return None
    require('projection_recovery' not in manifest and 'team_generation' not in manifest, 'runtime_only_constructor')
    assembly = manifest.get('assembly_sha')
    require(assembly in release.git(root, 'rev-list', '--first-parent', 'HEAD').splitlines(), 'protected_assembly_head')
    variable = {'candidate_id', 'derived_from_candidate', 'assembly_sha', 'projection_recovery',
        'files', 'runtime_baseline', 'documentation_baseline', 'dependency_groups'}
    require(encoded({k: v for k, v in manifest.items() if k not in variable})
        == encoded({k: v for k, v in anchor.items() if k not in variable}), 'immutable_generation_and_science')
    require(set(manifest['files']) == set(anchor['files']), 'complete_payload_inventory')
    changed = {name for name in anchor['files'] if anchor['files'][name] != manifest['files'][name]}
    require(changed == DELTAS, 'exact_awards_ui_delta')
    for name in DELTAS:
        require(release.digest(_blob(root, assembly, name)) == manifest['files'][name], 'reviewed_ui_bytes')
    original_page = _blob(root, record['publication']['commit'], PAGE)
    require(release.digest(original_page) == anchor['files'][PAGE], 'original_page_bytes')
    old = ('./' + SCRIPT + '?v=' + anchor['files'][SCRIPT]).encode()
    new = ('./' + SCRIPT + '?v=' + manifest['files'][SCRIPT]).encode()
    require(original_page.count(old) == 1 and (bundle/'files'/PAGE).read_bytes()
        == original_page.replace(old, new), 'single_content_addressed_reference')
    # These are constructor provenance, not permission to alter extra payloads.
    for key in ('runtime_baseline', 'documentation_baseline'):
        require(set(manifest[key]) == set(anchor[key]), 'baseline_inventory')
        require(all(value == release.digest(_blob(root, assembly, name))
            for name, value in manifest[key].items()), 'protected_baseline')
    before, after = anchor.get('dependency_groups', {}), manifest.get('dependency_groups', {})
    require(set(before) == set(after), 'dependency_group_inventory')
    for group in before:
        require(isinstance(after[group], dict) and set(after[group]) == {'files', 'fingerprint'}
            and after[group]['fingerprint'] == release.digest(release.encoded(after[group]['files'])), 'dependency_group_identity')
        if group not in ('validation', 'runtime'):
            require(encoded(before[group]) == encoded(after[group]), 'source_semantic_team_dependencies')
    worker_inputs = _worker_inputs(root, manifest)
    return {'version': VERSION, 'completion_record_sha256': identity(record),
        'original_candidate_id': anchor['candidate_id'],
        'original_manifest_sha256': record['candidate']['manifest_sha256'],
        'target_candidate_id': manifest['candidate_id'],
        'target_manifest_sha256': release.digest((bundle/release.MANIFEST).read_bytes()),
        'assembly_sha': manifest['assembly_sha'], 'worker_fingerprint': manifest['worker_fingerprint'],
        'worker_inputs': worker_inputs, 'source_correction_sha256': identity(manifest['source_correction']),
        'original_generation_sha256': identity(manifest['original_generation']),
        'generation_files_sha256': identity(manifest['generation_files']),
        'semantic_identity': manifest['semantic_identity'], 'release_identity': manifest['release_identity'],
        'changes': {name: {'before': anchor['files'][name], 'after': manifest['files'][name]} for name in sorted(changed)}}


def _original_evidence(authenticated, record, plan):
    owned, candidate = record['owned_smoke'], record['candidate']
    raw = authenticated['receipt_text'].encode('utf8')
    receipt = smoke.json_value(raw)
    require(release.digest(raw) == owned['aggregate_sha256'], 'original_aggregate_bytes')
    anchor = authenticated['anchor']
    origin = anchor.get('aggregate_origin', anchor)
    require(origin['run']['id'] == owned['owner_run_id'] and origin['run']['run_attempt'] == owned['owner_run_attempt']
        and origin['run']['head_sha'] == owned['owner_head_sha']
        and origin['artifact']['id'] == owned['state_artifact_id']
        and origin['artifact']['digest'] == 'sha256:' + owned['state_artifact_sha256']
        and origin['checkpoint_sha256'] == owned['checkpoint_sha256']
        and origin['ledger_sha256'] == owned['ledger_sha256'], 'original_owned_state')
    operations = []
    require(len(receipt['operations']) == len(receipt['inputs']['operations']) == 3, 'three_complete_original_inputs')
    for row, requested in zip(receipt['operations'], receipt['inputs']['operations'], strict=True):
        body_raw = requested['provider_body_text'].encode('utf8')
        require(row['purpose'] == requested['purpose'] and release.digest(body_raw) == row['provider_body_sha256'],
            'original_raw_provider_body')
        operations.append({'purpose': row['purpose'], 'request_id': row['request_id'],
            'body_sha256': identity(smoke.json_value(body_raw)), 'response_sha256': row['response_sha256']})
    require(encoded(operations) == encoded(owned['operations']), 'three_original_paid_operations')
    proof = authenticated['serving_proof']
    expected_candidate = {'candidate_id': candidate['candidate_id'], 'artifact_id': candidate['artifact_id'],
        'artifact_digest': 'sha256:' + candidate['artifact_sha256'],
        'manifest_sha256': candidate['manifest_sha256'], 'code_sha': candidate['artifact_head_sha']}
    require(encoded(proof.get('candidate')) == encoded(expected_candidate), 'unchanged_original_candidate_proof')
    require(proof['fingerprint'] == plan['worker_fingerprint']
        and encoded(proof['reconciliation']['input_hashes']) == encoded(plan['worker_inputs']), 'fresh_full_worker_inputs')
    expected = authenticated['expected']; release_id = plan['release_identity']
    require(expected['worker_input_fingerprint'] == plan['worker_fingerprint']
        and expected['current']['corpus_sha256'] == release_id['current_corpus_sha256']
        and expected['previous']['corpus_sha256'] == release_id['previous_corpus_sha256']
        and expected['current']['model_space_fingerprint'] == release_id['model_space_fingerprint'], 'same_provider_corpora')
    return receipt, proof


def reuse(bundle, reports, *, root=ROOT, inputs=None, api=smoke.existing.api, node_call=smoke.node):
    """Authenticate original purchases and fresh serving bytes; never dispatch."""
    require(inputs is not None, 'verified_retained_inputs_required')
    plan = classify(bundle, root=root)
    require(plan is not None, 'covered_runtime_candidate_required')
    record, _ = _bridge().completion_record(root)
    _, target = _bridge().candidate_anchor(bundle, api=api)
    require(target['candidate_id'] == plan['target_candidate_id']
        and target['manifest_sha256'] == plan['target_manifest_sha256'], 'target_artifact')
    authenticated = smoke.authenticate_owner(inputs, api=api, node_call=node_call)
    receipt, proof = _original_evidence(authenticated, record, plan)
    # The established validator binds all actual rows/caches/usage and supplies
    # a fresh module/configuration/version proof. It keeps the old candidate ID.
    reused = node_call('reuse', authenticated)
    require(reused.get('version') == 'search-worker-smoke-reuse-v1' and reused.get('status') == 'passed_reused'
        and all(type(reused.get(k)) is int and reused[k] == 0 for k in ZERO_FIELDS)
        and reused.get('receipt_sha256') == record['owned_smoke']['aggregate_sha256']
        and reused.get('original_run_id') == record['owned_smoke']['owner_run_id']
        and reused.get('authoritative_run_id') == authenticated['anchor']['run']['id']
        and reused.get('serving_version_id') == proof['version_id'], 'zero_provider_reuse')
    require(encoded(classify(bundle, root=root)) == encoded(plan), 'target_changed_during_authentication')
    reports = Path(reports)
    checkpoint = {**proof, 'required_fingerprint': plan['worker_fingerprint'], 'deploy_required': False}
    prior_path = reports/'worker-after.json'
    if prior_path.exists():
        prior = smoke.json_value(prior_path.read_bytes())
        require(prior.get('required_fingerprint') == plan['worker_fingerprint'] and prior.get('deploy_required') is False,
            'prior_worker_checkpoint')
        node_call('same-proof', {'before': {k: v for k, v in prior.items()
            if k not in ('required_fingerprint', 'deploy_required')}, 'after': proof})
    coverage = {**plan, 'status': 'passed_reused', 'target_artifact': target,
        'original_aggregate_sha256': record['owned_smoke']['aggregate_sha256'],
        'authoritative_owner': authenticated['anchor'], 'original_operations': record['owned_smoke']['operations'],
        'original_proof_sha256': identity(receipt['serving_after']),
        'fresh_worker_proof_sha256': identity(proof), 'reuse_receipt_sha256': identity(reused),
        'reuse_fresh_proof_sha256': reused['serving_proof_sha256'],
        'verified_at': reused['verified_at'], **{key: 0 for key in ZERO_FIELDS}}
    coverage_path = reports/'runtime-smoke-coverage.json'
    if coverage_path.exists():
        prior = smoke.json_value(coverage_path.read_bytes())
        require(all(encoded(prior.get(k)) == encoded(plan[k]) for k in plan), 'conflicting_target_coverage')
    live = {**proof, 'verified': True, 'required_fingerprint': plan['worker_fingerprint'],
        'expected_version_id': proof['version_id'], 'verified_at': reused['verified_at']}
    # All network authentication precedes reports. Repeating after interruption
    # revalidates the same evidence and remains strictly read-only remotely.
    atomic_json(reports/'catalog-smoke-reuse.json', reused)
    if not prior_path.exists():
        atomic_json(prior_path, checkpoint)
    atomic_json(reports/'worker-live.json', live)
    atomic_json(coverage_path, coverage)
    return {'reuse_receipt': reused, 'worker_live': live, 'coverage_receipt': coverage}


def validate_retention(bundle, reports, *, root=ROOT, node_call=smoke.node):
    """Pure late-failure retention checks; this does not assert fresh live state."""
    plan = classify(bundle, root=root)
    require(plan is not None, 'retention_runtime_candidate')
    record, _ = _bridge().completion_record(root)
    reports = Path(reports)
    coverage = smoke.json_value((reports/'runtime-smoke-coverage.json').read_bytes())
    reused = smoke.json_value((reports/'catalog-smoke-reuse.json').read_bytes())
    after = smoke.json_value((reports/'worker-after.json').read_bytes())
    live = smoke.json_value((reports/'worker-live.json').read_bytes())
    require(all(encoded(coverage.get(key)) == encoded(value) for key, value in plan.items()), 'retention_exact_target')
    artifact = coverage['target_artifact']
    require(artifact['candidate_id'] == plan['target_candidate_id']
        and artifact['manifest_sha256'] == plan['target_manifest_sha256'], 'retention_target_artifact')
    require(coverage.get('status') == 'passed_reused'
        and coverage['original_aggregate_sha256'] == reused['receipt_sha256'] == record['owned_smoke']['aggregate_sha256']
        and encoded(coverage['original_operations']) == encoded(record['owned_smoke']['operations'])
        and coverage['reuse_receipt_sha256'] == identity(reused)
        and coverage['reuse_fresh_proof_sha256'] == reused['serving_proof_sha256']
        and all(type(value.get(key)) is int and value[key] == 0 for value in (coverage, reused) for key in ZERO_FIELDS),
        'retention_original_reuse')
    require(after.get('required_fingerprint') == plan['worker_fingerprint'] and after.get('deploy_required') is False
        and live.get('required_fingerprint') == plan['worker_fingerprint'] and live.get('verified') is True,
        'retention_worker_reports')
    original_proof = {k: v for k, v in after.items() if k not in ('required_fingerprint', 'deploy_required')}
    latest_proof = {k: v for k, v in live.items() if k not in ('required_fingerprint', 'verified', 'expected_version_id', 'verified_at')}
    candidate = record['candidate']
    expected_candidate = {'candidate_id': candidate['candidate_id'], 'artifact_id': candidate['artifact_id'],
        'artifact_digest': 'sha256:' + candidate['artifact_sha256'], 'manifest_sha256': candidate['manifest_sha256'],
        'code_sha': candidate['artifact_head_sha']}
    require(encoded(original_proof.get('candidate')) == encoded(expected_candidate)
        and coverage['fresh_worker_proof_sha256'] == identity(latest_proof), 'retention_original_proof_identity')
    node_call('same-proof', {'before': original_proof, 'after': latest_proof})
    return coverage
