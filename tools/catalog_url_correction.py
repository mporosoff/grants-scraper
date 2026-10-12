"""Authenticated URL-only descendant of the preserved October 12 identity repair."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
import json

from tools import catalog_identity_correction as identity
from tools import catalog_smoke_receipt as auth
from tools import release_candidate as c

VERSION = 'catalog-url-correction-20261012-v1'
PARENT = '051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4'
RUN = 38280685194
ATTEMPT = 1
EVENT_SHA = 'dc5113ee791906fce1eb0b2f38db85032803681b'
GENERATION_SHA = identity.GENERATION_SHA
MANIFEST_SHA = 'f11c8bed90de162868348b262d6b200e2f36bb13c2601b73fbb423c5de4162c1'
STAGE = 'catalog-url-correction'
SOURCE_REPAIR_FILES = {'scripts/build_catalog.py'}
ARTIFACTS = {
    'candidate': (11761850155, 'candidate-' + PARENT,
        '840ed6e75e6090ffa16c47071b82c031c133031de1324654200e3a26cb788123'),
    'receipt': (11760638378, 'identity-correction-38280685194-1',
        '5e8ce46113b26d2714039d77793a7886ae25c5fa5d62ded5b0a9bb5ca3706f17'),
}
IDENTITY_RECEIPT_SHA = '792f7c054059eb0d7d79a5ba8f3c2c0dc4beea2694b9041e17e280937fa235a8'


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_url_correction_' + reason)


def reject_quarantined(manifest):
    require(manifest.get('candidate_id') != PARENT, 'rejected_candidate_requires_exact_url_correction')


def plan(root, environment):
    expected = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
        'CANDIDATE_ID': PARENT, 'CANDIDATE_RUN': str(RUN), 'REQUESTED_STAGE': STAGE}
    require(all(environment.get(k) == v for k, v in expected.items()), 'exact_protected_manual_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
        and environment.get('QUALIFICATION_PILOT') != 'true', 'no_other_generation_or_recovery')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'),
        'candidate_id': PARENT, 'candidate_run': str(RUN), 'openai': 'false', 'anthropic': 'false',
        'team_mode': 'maintenance', 'reason': 'Authenticated NYSERDA navigation correction; identical science and vectors; no new allowance'}


def authenticate(parent_bundle, *, api=auth.existing.api):
    run = identity.original_run(RUN, EVENT_SHA, 'failure', api=api)
    packets = {}
    for role, (identifier, name, digest) in ARTIFACTS.items():
        raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
        packets[role] = identity.archive_files(raw)
    bundle = Path(parent_bundle)
    original = c.load(bundle, PARENT)
    require(c.digest((bundle/'candidate.json').read_bytes()) == MANIFEST_SHA, 'manifest_pin')
    require(packets['candidate'] == {'candidate.json': (bundle/'candidate.json').read_bytes(),
        **{'files/' + n: (bundle/'files'/n).read_bytes() for n in original['files']}}, 'complete_parent')
    require(set(packets['receipt']) == {'receipt.json'}
        and c.digest(packets['receipt']['receipt.json']) == IDENTITY_RECEIPT_SHA, 'identity_receipt_pin')
    prior = auth.json_value(packets['receipt']['receipt.json'])
    require(prior['version'] == identity.VERSION and prior['parent_candidate'] == identity.PARENT
        and original['derived_from_candidate'] == identity.PARENT and original['assembly_sha'] == EVENT_SHA
        and all(original['identity_correction'].get(k) == v for k, v in prior.items()), 'identity_receipt_lineage')
    affected = original['identity_correction']['affected_generation']
    require(affected['generation_sha'] == EVENT_SHA and affected['generation_run_id'] == str(RUN)
        and affected['generation_run_attempt'] == str(ATTEMPT), 'identity_owner')
    require(original['generation_sha'] == GENERATION_SHA and original['generation_run_id'] == str(identity.RUN)
        and original['generation_run_attempt'] == str(identity.ATTEMPT), 'original_generation')
    # Reuse original exact spending/ZIP authentication. Neither receipt nor a
    # cache can grant a new logical allowance. The old public candidate is
    # materialized only in a temporary authentication directory.
    original_run = identity.original_run(identity.RUN, identity.EVENT_SHA, 'failure', api=api)
    identifier, name, digest = identity.ARTIFACTS['candidate']
    raw, _ = auth.authenticated_zip(identifier, name, original_run, 'sha256:' + digest, api=api)
    with tempfile.TemporaryDirectory(prefix='catalog-url-origin-') as temporary:
        auth.unpack_public(raw, temporary)
        generated, spending = identity.authenticate(temporary, api=api)
    require(prior['spending'] == spending, 'original_spending')
    require(all(original[k] == generated[k] for k in ('generation_sha', 'generation_run_id',
        'generation_run_attempt', 'generation_timestamp', 'team_identity', 'semantic_identity')),
        'retained_science_origin')
    require(original['original_generation'] == {k: generated[k] for k in original['original_generation']},
        'original_generation_receipt')
    return original, dict(spending) | {'identity_parent': {'candidate_id': PARENT,
        'manifest_sha256': MANIFEST_SHA, 'run_id': RUN, 'receipt_sha256': IDENTITY_RECEIPT_SHA,
        'artifacts': {role: {'id': item[0], 'name': item[1], 'sha256': item[2]}
            for role, item in ARTIFACTS.items()}}}


def verify_source_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES
        and not changes.get('teams') and not changes.get('semantic'), 'bounded_dependency_changes')


def dependency_scope(root, original):
    verify_source_scope(root, original)
    c.git(root, 'merge-base', '--is-ancestor', EVENT_SHA, 'HEAD')
    c.verify_files(root, original['runtime_baseline'])


def derive(parent_bundle, audit_at):
    from tools.catalog_url_projection import projection
    return identity.derive_metadata(parent_bundle, audit_at, projection, package_kind='url')


def receipt_for(original, spending, outputs, proof, audit_at):
    return {'version': VERSION, 'parent_candidate': PARENT, 'parent_manifest_sha256': MANIFEST_SHA,
        'parent_run': RUN, 'audit_at': audit_at, 'spending': spending, 'projection': proof,
        'output_hashes': {n: c.digest(raw) for n, raw in sorted(outputs.items())},
        'retained_hashes': {n: h for n, h in original['files'].items() if n not in outputs
            and not c.FACET_FEED_NAME.fullmatch(n)}}


def verify_inputs(root, original, parent_bundle, receipt_path):
    receipt = c.read_json(receipt_path)
    authenticated, spending = authenticate(parent_bundle)
    require(original == authenticated, 'constructor_parent')
    verify_source_scope(root, original)
    outputs, proof = derive(parent_bundle, receipt['audit_at'])
    require(receipt == receipt_for(original, spending, outputs, proof, receipt['audit_at']), 'deterministic_replay')
    c.verify_files(root, receipt['output_hashes'] | receipt['retained_hashes'])
    require(c.facet_feed_names(root) == {n for n in receipt['output_hashes'] if c.FACET_FEED_NAME.fullmatch(n)},
        'complete_facet_inventory')
    return {n: h for n, h in receipt['retained_hashes'].items() if n in original['generation_files']}


def recover(root, parent_bundle, output, receipt_path):
    root = Path(root)
    plan(root, dict(os.environ))
    original, spending = authenticate(parent_bundle)
    dependency_scope(root, original)
    audit_at = datetime.now(timezone.utc).isoformat()
    outputs, proof = derive(parent_bundle, audit_at)
    c.write_json(receipt_path, receipt_for(original, spending, outputs, proof, audit_at))
    for name in original['files']:
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(parent_bundle)/'files'/name, destination)
    for name in c.facet_feed_names(root) - {n for n in outputs if c.FACET_FEED_NAME.fullmatch(n)}:
        c.checked_path(root, name).unlink()
    for name, raw in outputs.items():
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    return c.create(root, output, parent=parent_bundle, url_correction=receipt_path)


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
