"""Exact, provider-free access correction of the retained October 8 catalog.

This derivation has no generation allowance. It authenticates the original
candidate and receipt ZIPs, replays source-backed access corrections, and
requires every scientific passage and vector to remain identical. Publication still requires new exact-byte gates.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from tools import release_candidate as c
from tools import catalog_smoke_receipt as auth

VERSION = 'catalog-access-correction-20261012-v1'
PARENT = 'ac68ff0aef1e4aff66c06971c1500673a46bd0c7a40f2cc0cd71c9559ea402a8'
RUN = 37845073222
ATTEMPT = 1
EVENT_SHA = 'a6b82f6a872ea6aeb3e3b2678574d6ea6415f5f3'
GENERATION_SHA = '3c2002b8794f90a9e67b733230df12bf83cd64e9'
MANIFEST_SHA = '4112e0b47acba26977340d31c56244e5514ae1e36c5a160e187d7ec014fc752a'
RECEIPT_SHA = 'c697d7cd0ec84ba861984030cbb2f5e490e8e5da9b7bff04e75ced5cdd51df7c'
ARTIFACTS = {
    'candidate': (11579731383, 'candidate-' + PARENT,
        '750a446a3692f98093e56ec98fa751b26067fc3afa0d018c5e77d975a587f42e'),
    'receipt': (11578958147, 'source-recovery-37845073222-1',
        'bd5d33f191cedc05574105a2863eb72706ec317246d9db866d1c0dcca75f1778'),
}
STAGE = 'catalog-access-correction'
PACKAGE_OUTPUT = 'data/search-v2-release.json'
SOURCE_REPAIR_FILES = {'scripts/submission_schedule.py'}


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_access_correction_' + reason)


def reject_quarantined(manifest):
    from tools.catalog_schedule_correction import reject_quarantined as reject_schedule_parent
    reject_schedule_parent(manifest)
    require(manifest.get('candidate_id') != PARENT,
        'rejected_candidate_requires_exact_access_correction')


def plan(root, environment):
    from tools import catalog_schedule_correction as schedule
    if environment.get('CANDIDATE_ID') == schedule.PARENT:
        return schedule.plan(root, environment)
    expected = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
        'CANDIDATE_ID': PARENT, 'CANDIDATE_RUN': str(RUN), 'REQUESTED_STAGE': STAGE}
    require(all(environment.get(k) == v for k, v in expected.items()), 'exact_protected_manual_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
        and environment.get('QUALIFICATION_PILOT') != 'true', 'no_other_generation_or_recovery')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'),
        'candidate_id': PARENT, 'candidate_run': str(RUN), 'openai': 'false', 'anthropic': 'false',
        'team_mode': 'maintenance', 'reason': 'Authenticated access correction with identical scientific corpus and vectors; zero new generation allowance'}


def archive_files(raw):
    # Reuse the bounded, duplicate/path/link-safe decoder, even for private
    # state evidence. Only hashes and measured totals leave this temp directory.
    with tempfile.TemporaryDirectory(prefix='catalog-recovery-auth-') as temporary:
        auth.unpack_public(raw, temporary)
        root = Path(temporary)
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def authenticate(parent_bundle, *, api=auth.existing.api):
    run = auth.json_value(api(f'actions/runs/{RUN}/attempts/{ATTEMPT}'))
    require(run.get('id') == RUN and run.get('run_attempt') == ATTEMPT
        and run.get('head_sha') == EVENT_SHA and run.get('head_branch') == 'main'
        and run.get('path') == auth.REFRESH and run.get('event') == 'workflow_dispatch'
        and run.get('status') == 'completed' and run.get('conclusion') == 'failure', 'original_run')
    packets = {}
    for role, (identifier, name, digest) in ARTIFACTS.items():
        raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
        packets[role] = archive_files(raw)
    bundle = Path(parent_bundle)
    original = c.load(bundle, PARENT)
    require(c.digest((bundle/'candidate.json').read_bytes()) == MANIFEST_SHA, 'manifest_pin')
    require(packets['candidate'] == {'candidate.json': (bundle/'candidate.json').read_bytes(),
        **{'files/' + n: (bundle/'files'/n).read_bytes() for n in original['files']}}, 'complete_parent')
    require(set(packets['receipt']) == {'receipt.json'}
        and c.digest(packets['receipt']['receipt.json']) == RECEIPT_SHA, 'prior_receipt_pin')
    prior = auth.json_value(packets['receipt']['receipt.json'])
    # The constructor augments a receipt with generation/output proof. The
    # original authenticated receipt must remain an exact subset of that proof.
    require(all(original.get('source_recovery', {}).get(k) == v for k, v in prior.items()), 'prior_recovery_receipt')
    require(original['generation_sha'] == GENERATION_SHA and original['generation_run_id'] == '36896442720'
        and original['generation_run_attempt'] == '4'
        and all(original['original_generation'][k] == original[k] for k in
            ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp')), 'original_generation')
    spending = original['source_recovery']['spending']
    require(spending['original_logical_id'] == 'offline-36896442720'
        and spending['limit_microusd'] == 2_000_000 and spending['max_requests'] == 300
        and spending['requests_used'] == 66 and spending['charged_microusd'] == 441023
        and len(spending['state_hashes']) == 69
        and all(spending[k] == 0 for k in ('new_document_ai_requests', 'new_vector_requests', 'new_team_requests')),
        'original_spending')
    # These totals and all 69 private-state hashes are already authenticated by
    # the fixed complete parent ZIP and paired receipt; no new allowance exists.
    return original, spending


def dependency_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES
        and not changes.get('teams') and not changes.get('semantic'), 'bounded_dependency_changes')
    c.git(root, 'merge-base', '--is-ancestor', GENERATION_SHA, 'HEAD')
    # Source correction cannot silently replace the retained runtime.
    c.verify_files(root, original['runtime_baseline'])


def derive(parent_bundle, audit_at):
    from tools.catalog_access_projection import projection
    from scripts.update_catalog_docs import load_catalog, render_docs, catalog_stats, update_catalog_asset_reference
    parent = Path(parent_bundle)/'files'
    outputs, proof = projection(parent, audit_at)
    with tempfile.TemporaryDirectory(prefix='catalog-access-projection-') as temporary:
        target = Path(temporary)/'workspace'
        vector_receipt = Path(temporary)/'access-package.json'
        shutil.copytree(parent, target, dirs_exist_ok=True)
        for name, raw in outputs.items():
            path = c.checked_path(target, name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        catalog = load_catalog(target/'data/opportunities.js')
        readme, project = render_docs((parent/'README.md').read_text(encoding='utf8'),
            (parent/'PROJECT.md').read_text(encoding='utf8'), catalog_stats(catalog))
        outputs.update({'README.md': readme.encode(), 'PROJECT.md': project.encode()})
        for name in ('match_explorer.html', 'team_match.html'):
            outputs[name] = update_catalog_asset_reference((parent/name).read_text(encoding='utf8'), catalog).encode()
        # Compatibility hashes include HTML references as well as catalog data.
        for name, raw in outputs.items():
            path = c.checked_path(target, name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        subprocess.run([shutil.which('node') or 'node', str(c.ROOT/'tools/catalog_access_package.mjs'),
            '--parent', str(parent), '--root', str(target), '--receipt', str(vector_receipt)],
            check=True, timeout=120, capture_output=True)
        outputs[PACKAGE_OUTPUT] = (target/PACKAGE_OUTPUT).read_bytes()
        vector = c.read_json(vector_receipt)
    return outputs, {'record_projection': proof, 'package_projection': vector}


def receipt_for(original, spending, outputs, proof, audit_at):
    return {'version': VERSION, 'parent_candidate': PARENT, 'parent_manifest_sha256': MANIFEST_SHA,
        'parent_run': RUN, 'audit_at': audit_at, 'spending': spending, 'projection': proof,
        'output_hashes': {n: c.digest(raw) for n, raw in sorted(outputs.items())},
        'retained_hashes': {n: h for n, h in original['files'].items() if n not in outputs
            and not c.FACET_FEED_NAME.fullmatch(n)}}


def verify_inputs(root, original, parent_bundle, receipt_path):
    receipt = c.read_json(receipt_path)
    from tools import catalog_schedule_correction as schedule
    if receipt.get('version') == schedule.VERSION:
        return schedule.verify_inputs(root, original, parent_bundle, receipt_path)
    authenticated, spending = authenticate(parent_bundle)
    require(original == authenticated, 'constructor_parent')
    # Verify protected implementation inputs before materialization separately;
    # the constructor's runtime has only the deterministic reference changes.
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES
        and not changes.get('teams') and not changes.get('semantic'), 'constructor_dependencies')
    outputs, proof = derive(parent_bundle, receipt['audit_at'])
    require(receipt == receipt_for(original, spending, outputs, proof, receipt['audit_at']), 'deterministic_replay')
    c.verify_files(root, receipt['output_hashes'] | receipt['retained_hashes'])
    expected_feeds = {n for n in receipt['output_hashes'] if c.FACET_FEED_NAME.fullmatch(n)}
    require(c.facet_feed_names(root) == expected_feeds, 'complete_facet_inventory')
    return {n: h for n, h in receipt['retained_hashes'].items() if n in original['generation_files']}


def recover(root, parent_bundle, output, receipt_path):
    from tools import catalog_schedule_correction as schedule
    if os.environ.get('CANDIDATE_ID') == schedule.PARENT:
        return schedule.recover(root, parent_bundle, output, receipt_path)
    root = Path(root)
    plan(root, dict(os.environ))
    original, spending = authenticate(parent_bundle)
    dependency_scope(root, original)
    audit_at = datetime.now(timezone.utc).isoformat()
    outputs, proof = derive(parent_bundle, audit_at)
    receipt = receipt_for(original, spending, outputs, proof, audit_at)
    c.write_json(receipt_path, receipt)
    # All original files are authenticated above; restore them only inside the
    # isolated recovery job, then apply the deterministic, bounded projection.
    for name in original['files']:
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(parent_bundle)/'files'/name, destination)
    for name in c.facet_feed_names(root) - {n for n in outputs if c.FACET_FEED_NAME.fullmatch(n)}:
        c.checked_path(root, name).unlink()
    for name, raw in outputs.items():
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)
    return c.create(root, output, parent=parent_bundle, access_correction=receipt_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-bundle', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    value = recover(c.ROOT, args.parent_bundle, args.bundle, args.receipt)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf8') as stream:
            stream.write('candidate_id=' + value['candidate_id'] + '\n')
    print(json.dumps({'candidate_id': value['candidate_id'], 'new_provider_requests': 0}))


if __name__ == '__main__':
    main()
