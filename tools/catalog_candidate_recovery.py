"""Repack the one authenticated catalog artifact that omitted its site marker.

The original ZIP remains evidence. Only its manifested .nojekyll bytes are
restored from the original protected commit. The manifest and candidate ID do
not change; the refresh workflow persists a new complete artifact before gates.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess

from tools import catalog_smoke_receipt as smoke
from tools import catalog_source_correction as source
from tools import catalog_correction_policy as policy
from tools import release_candidate as release
from tools.offline_spend import atomic_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/catalog_candidate_recovery_20260923.json'
VERSION = 'catalog-candidate-marker-recovery-20260923-v1'
FIELDS = {'version', 'failed_run_id', 'failed_run_attempt', 'failed_run_head',
    'artifact_id', 'artifact_sha256', 'candidate_id', 'manifest_sha256',
    'source_plan_sha256', 'spending_plan_sha256', 'export_sha256',
    'marker_path', 'marker_bytes', 'marker_sha256'}


def require(ok, why):
    smoke.require(ok, 'candidate_recovery_' + why)


def plan():
    value = smoke.json_value(CONFIG.read_bytes())
    require(isinstance(value, dict) and set(value) == FIELDS
        and value['version'] == VERSION, 'strict_plan')
    require(all(type(value[k]) is int and value[k] > 0
        for k in ('failed_run_id', 'failed_run_attempt', 'artifact_id', 'marker_bytes'))
        and value['failed_run_attempt'] == 1 and value['marker_bytes'] == 1
        and value['marker_path'] == '.nojekyll', 'fixed_marker_scope')
    require(re.fullmatch('[a-f0-9]{40}', value['failed_run_head'])
        and all(re.fullmatch('[a-f0-9]{64}', value[k]) for k in FIELDS
            if k.endswith('_sha256') or k == 'candidate_id'), 'complete_identities')
    require(value['source_plan_sha256'] == release.digest(source.CONFIG.read_bytes())
        and value['spending_plan_sha256'] == policy.PLAN_SHA, 'unchanged_fixed_plans')
    return value


def protected_marker(root, spec):
    ancestor = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
        spec['failed_run_head'], 'HEAD'], capture_output=True, timeout=30)
    require(ancestor.returncode == 0, 'original_head_not_ancestor')
    content = subprocess.check_output(['git', '-C', str(root), 'show',
        spec['failed_run_head'] + ':' + spec['marker_path']], timeout=30)
    require(len(content) == spec['marker_bytes']
        and release.digest(content) == spec['marker_sha256'], 'protected_marker_bytes')
    return content


def recover(bundle, reports, *, root=ROOT, api=smoke.existing.api):
    """GET-only source recovery; does not assemble, generate, publish, or spend."""
    spec = plan()
    bundle, reports = Path(bundle), Path(reports)
    require(not bundle.exists() and not (reports/'recovery.json').exists(), 'new_destination')
    run = smoke.trusted_run(spec['failed_run_id'], smoke.REFRESH,
        attempt=spec['failed_run_attempt'], allow_failed=True, api=api)
    require(run['head_sha'] == spec['failed_run_head'] and run['conclusion'] == 'failure'
        and run['event'] == 'workflow_dispatch', 'exact_failed_run')
    archive, artifact = smoke.authenticated_zip(spec['artifact_id'],
        'candidate-' + spec['candidate_id'], run, 'sha256:' + spec['artifact_sha256'], api=api)
    smoke.unpack_public(archive, bundle)
    manifest_raw = (bundle/release.MANIFEST).read_bytes()
    require(release.digest(manifest_raw) == spec['manifest_sha256'], 'exact_manifest_bytes')
    manifest = smoke.json_value(manifest_raw)
    require(manifest.get('candidate_id') == spec['candidate_id']
        and release.digest(release.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
            == spec['candidate_id'], 'exact_candidate_identity')
    correction = manifest.get('source_correction', {})
    require(correction.get('source_plan_sha256') == spec['source_plan_sha256']
        and correction.get('spending_plan_sha256') == spec['spending_plan_sha256']
        and correction.get('export_sha256') == spec['export_sha256'], 'same_source_and_vectors')
    hashes = manifest['files']
    require(hashes.get(spec['marker_path']) == spec['marker_sha256'], 'manifest_marker_hash')
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    expected = {release.MANIFEST} | {'files/' + name for name in hashes if name != spec['marker_path']}
    require(actual == expected, 'only_declared_marker_missing')
    release.verify_files(bundle/'files', {name: value for name, value in hashes.items()
        if name != spec['marker_path']})
    marker = protected_marker(root, spec)
    # The hash proof is checked here as well so an injected reader cannot relax it.
    require(len(marker) == spec['marker_bytes'] and release.digest(marker) == hashes[spec['marker_path']],
        'restored_marker_hash')
    release.checked_path(bundle/'files', spec['marker_path']).write_bytes(marker)
    restored = release.load(bundle, spec['candidate_id'])
    require((bundle/release.MANIFEST).read_bytes() == manifest_raw, 'manifest_unchanged')
    receipt = {'version': VERSION, 'recovery_plan_sha256': release.digest(release.encoded(spec)),
        'recovered_at': datetime.now(timezone.utc).isoformat(),
        'original_artifact': {'id': artifact['id'], 'name': artifact['name'],
            'sha256': spec['artifact_sha256'], 'run_id': run['id'],
            'run_attempt': spec['failed_run_attempt'], 'head_sha': run['head_sha']},
        'candidate_id': restored['candidate_id'], 'manifest_sha256': spec['manifest_sha256'],
        'restored_files': {spec['marker_path']: {'bytes': len(marker),
            'sha256': release.digest(marker), 'protected_commit': spec['failed_run_head']}},
        'preserved_present_files': len(hashes) - 1, 'verified_complete_files': len(hashes),
        'manifest_and_all_payload_hashes_unchanged': True,
        'source_plan_sha256': spec['source_plan_sha256'], 'spending_plan_sha256': spec['spending_plan_sha256'],
        'export_sha256': spec['export_sha256'], 'provider_requests': 0, 'native_counts': 0,
        'source_collection_requests': 0, 'assembly_runs': 0, 'ledger_writes': 0,
        'requires_new_complete_candidate_artifact_and_validation': True}
    atomic_json(reports/'recovery.json', receipt)
    return restored
