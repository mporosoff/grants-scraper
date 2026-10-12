"""Exact, provider-free recovery of the rejected October 8 catalog candidate.

This derivation has no generation allowance. It authenticates the original
candidate/spending ZIPs, replays six documented record withdrawals and copies
only unchanged vector rows. Publication still requires new exact-byte gates.
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

VERSION = 'catalog-source-recovery-20261008-v1'
PARENT = '5801e4912b642ad70e4383b0f805adc95aad7d892b85f8b7638aeca958da85e6'
RUN = 36896442720
ATTEMPT = 4
EVENT_SHA = '80664ce12e3ab727845ad3e603dc5ee0ce450c61'
GENERATION_SHA = '3c2002b8794f90a9e67b733230df12bf83cd64e9'
MANIFEST_SHA = '13c34c94b4ca1fc76d67e07ee0271cdcfccd392b45f6d66786abf02d5215dee2'
LEDGER_SHA = 'c56a2f8ccfd96d6030b3af5e79dc5646b1450e9f0be4c863086e720df23638f6'
ARTIFACTS = {
    'candidate': (11573380277, 'candidate-' + PARENT,
        '564cbb1b14df9cc3f6a216289d589325d8c7afd2975c26009ee0ebd7380ac2c9'),
    'state': (11573091286, 'generation-spend-state-36896442720-4',
        'e17ac069e241431caf6e409cf55c6b4bcbd34a0a38d5506933e5aa0ea8b7197c'),
    'reservation': (11572916212, 'generation-spend-reservation-36896442720-4',
        '16547cd734ad029ffa73e3dad1098cab7cf9faf3cec9558f61c6c5529bff2c13'),
}
STAGE = 'catalog-source-recovery'
VECTOR_OUTPUTS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
    'data/search-v2-release.json', 'workers/search-voyage-proxy/generated/corpus-allowlist.json')
# Only the bounded source invariant repairs may differ from the retained run.
SOURCE_REPAIR_FILES = {'scripts/solicitation_identity.py', 'scripts/sources/merge.py',
    'scripts/sources/intake.py',
    'scripts/sources/official_identity.py', 'scripts/sources/nsf_identity.py', 'scripts/sources/validate.py',
    'scripts/sources/adapters/doe_exchange.py', 'scripts/sources/adapters/doe_exchange_listing.py'}


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_source_recovery_' + reason)


def reject_quarantined(manifest):
    require(manifest.get('candidate_id') != PARENT,
        'rejected_candidate_requires_exact_source_recovery')


def plan(root, environment):
    expected = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
        'CANDIDATE_ID': PARENT, 'CANDIDATE_RUN': str(RUN)}
    require(all(environment.get(k) == v for k, v in expected.items()), 'exact_protected_manual_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
        and environment.get('QUALIFICATION_PILOT') != 'true', 'no_other_generation_or_recovery')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'),
        'candidate_id': PARENT, 'candidate_run': str(RUN), 'openai': 'false', 'anthropic': 'false',
        'team_mode': 'maintenance', 'reason': 'Authenticated record withdrawal and unchanged vector-row projection; zero new generation allowance'}


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
        and run.get('path') == auth.REFRESH and run.get('event') == 'schedule'
        and run.get('status') == 'completed' and run.get('conclusion') == 'cancelled', 'original_run')
    packets = {}
    for role, (identifier, name, digest) in ARTIFACTS.items():
        raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
        packets[role] = archive_files(raw)
    bundle = Path(parent_bundle)
    original = c.load(bundle, PARENT)
    require(c.digest((bundle/'candidate.json').read_bytes()) == MANIFEST_SHA, 'manifest_pin')
    require(packets['candidate'] == {'candidate.json': (bundle/'candidate.json').read_bytes(),
        **{'files/' + n: (bundle/'files'/n).read_bytes() for n in original['files']}}, 'complete_parent')
    require(original['generation_sha'] == GENERATION_SHA and original['generation_run_id'] == str(RUN)
        and original['generation_run_attempt'] == str(ATTEMPT), 'original_generation')
    state = packets['state']; ledger = auth.json_value(state['ledger.json'])
    require(c.digest(state['ledger.json']) == LEDGER_SHA and ledger['logical_id'] == 'offline-' + str(RUN)
        and ledger['limit_microusd'] == 2_000_000 and ledger['max_requests'] == 300
        and len(ledger['requests']) == 66
        and sum(r['charged_microusd'] for r in ledger['requests']) == 441023, 'original_ledger')
    require(set(packets['reservation']) == {'spend-reservation.json'} and
        auth.json_value(packets['reservation']['spend-reservation.json']) == {
            'attempt': '4', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': 'eac564e5caed08887a815aaa64ae19e0e0e01c430b77ef7abde684a5bea8370e',
            'run_id': str(RUN)}, 'original_reservation')
    vector = c.read_json(bundle/'files/evaluation/search_v2_hybrid_vector_build.json')
    require(vector['API_request_count'] == 6 and vector['usage_total_tokens'] == 298906,
        'original_vector_accounting')
    return original, {'original_logical_id': ledger['logical_id'], 'limit_microusd': 2_000_000,
        'max_requests': 300, 'requests_used': 66, 'charged_microusd': 441023,
        'new_document_ai_requests': 0, 'new_vector_requests': 0, 'new_team_requests': 0,
        'state_hashes': {n: c.digest(raw) for n, raw in sorted(state.items())},
        'prior_vector_requests': 6, 'prior_vector_tokens': 298906,
        'artifacts': {role: {'id': item[0], 'name': item[1], 'sha256': item[2]}
            for role, item in ARTIFACTS.items()}}


def dependency_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES
        and not changes.get('teams') and not changes.get('semantic'), 'bounded_dependency_changes')
    c.git(root, 'merge-base', '--is-ancestor', GENERATION_SHA, 'HEAD')
    # Source correction cannot silently replace the retained runtime.
    c.verify_files(root, original['runtime_baseline'])


def derive(parent_bundle, audit_at):
    from tools.catalog_record_withdrawal import projection
    from scripts.update_catalog_docs import load_catalog, render_docs, catalog_stats, update_catalog_asset_reference
    parent = Path(parent_bundle)/'files'
    outputs, proof = projection(parent, audit_at)
    with tempfile.TemporaryDirectory(prefix='catalog-source-projection-') as temporary:
        target = Path(temporary)/'workspace'
        vector_receipt = Path(temporary)/'vector-subset.json'
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
        subprocess.run([shutil.which('node') or 'node', str(c.ROOT/'tools/catalog_vector_subset.mjs'),
            '--parent', str(parent), '--root', str(target), '--receipt', str(vector_receipt)],
            check=True, timeout=120, capture_output=True)
        outputs.update({name: (target/name).read_bytes() for name in VECTOR_OUTPUTS})
        vector = c.read_json(vector_receipt)
    return outputs, {'record_projection': proof, 'vector_projection': vector}


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
    return c.create(root, output, parent=parent_bundle, source_recovery=receipt_path)


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
