"""Exact, provider-free source identity correction of the retained October 12 catalog.

This derivation has no generation allowance. It authenticates the original
candidate, spending and previous-publication ZIPs, replays identity-only corrections, and
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

VERSION = 'catalog-identity-correction-20261012-v1'
PARENT = '75e383c2a4fe48ece7ca2e1afc4fc0a0470dfe9f3133654da9b306aefa8c41ff'
RUN = 38275115281
ATTEMPT = 1
EVENT_SHA = '16af45fe20c11a1c9f7ebc86f3d9f93a6a2746f9'
GENERATION_SHA = EVENT_SHA
MANIFEST_SHA = '7c6435ad52fa90f5501ffc8edea190a0db5f529ce691fd99c78b1ccc293a0bd8'
LEDGER_SHA = '4af7aba201fad8d74d135342de590ebfd0a483fe67bac2126253325a52abe271'
ARTIFACTS = {
    'candidate': (11758399417, 'candidate-' + PARENT,
        'c1f0736c9367beb2bb9a6d4b53690b64cdebb319c0a0464a0c886b79ca329bc7'),
    'state': (11758299582, 'generation-spend-state-38275115281-1',
        '099fbcc068418a9b5e3fb477618f3ffc857831b9e7d6c2086340467cd2f7e728'),
    'reservation': (11759315089, 'generation-spend-reservation-38275115281-1',
        '9898e50a2c1bc445e21d9d244f11f7b79c75a529080b0b2f8ab907747b394599'),
}
PREVIOUS = '309e39320351c2ca959e4896289edeed5ff3ed4e37e1fc95a1d79b68813dbc67'
PREVIOUS_RUN = 38265638208
PREVIOUS_SHA = '096d2750422ed3cfb66228cfff473679dc3e1116'
PREVIOUS_MANIFEST_SHA = '8d4ffcd0d4bac644336404620f7ea696d84b64f1fa28d1d6b8692a358e0977f2'
PREVIOUS_ARTIFACT = (11754517554, 'candidate-' + PREVIOUS,
    'd9d9a479311a8cfb6833bdd8ad0e60d2a896cac9a736a414eeccd5779134612c')
STAGE = 'catalog-identity-correction'
PACKAGE_OUTPUT = 'data/search-v2-release.json'
SOURCE_REPAIR_FILES = {'scripts/sources/merge.py', 'scripts/sources/__main__.py', '@generation_invocations'}
INVOCATIONS_BEFORE = '360328b4ef8d2fe0ab8e5fdcfb6d0cb9391c140bc32f39827ead2f6f66bbf491'
INVOCATIONS_AFTER = 'f16cc32b6f8388b5089606b3bcb57dd9042e08731ca4ea20b23362f4f404a305'


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_identity_correction_' + reason)


def reject_quarantined(manifest):
    require(manifest.get('candidate_id') != PARENT,
        'rejected_candidate_requires_exact_identity_correction')


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
        'team_mode': 'maintenance', 'reason': 'Authenticated source identity correction with identical scientific corpus and vectors; zero new generation allowance'}


def archive_files(raw):
    # Reuse the bounded, duplicate/path/link-safe decoder, even for private
    # state evidence. Only hashes and measured totals leave this temp directory.
    with tempfile.TemporaryDirectory(prefix='catalog-recovery-auth-') as temporary:
        auth.unpack_public(raw, temporary)
        root = Path(temporary)
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def original_run(identifier, sha, conclusion, *, api):
    run = auth.json_value(api(f'actions/runs/{identifier}/attempts/1'))
    require(run.get('id') == identifier and run.get('run_attempt') == 1
        and run.get('head_sha') == sha and run.get('head_branch') == 'main'
        and run.get('path') == auth.REFRESH and run.get('event') == 'workflow_dispatch'
        and run.get('status') == 'completed' and run.get('conclusion') == conclusion, 'original_run')
    return run


def authenticate_previous(*, api):
    from tools.catalog_identity_projection import policy, value_hash
    run = original_run(PREVIOUS_RUN, PREVIOUS_SHA, 'success', api=api)
    identifier, name, digest = PREVIOUS_ARTIFACT
    raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
    packet = archive_files(raw)
    manifest = auth.json_value(packet['candidate.json'])
    require(c.digest(packet['candidate.json']) == PREVIOUS_MANIFEST_SHA
        and manifest.get('candidate_id') == PREVIOUS
        and c.digest(c.encoded({k:v for k,v in manifest.items() if k != 'candidate_id'})) == PREVIOUS,
        'previous_manifest')
    require(set(packet) == {'candidate.json'} | {'files/' + n for n in manifest['files']}
        and all(c.digest(packet['files/' + n]) == h for n,h in manifest['files'].items()), 'complete_previous')
    text = packet['files/data/opportunities.js'].decode('utf-8')
    catalog = json.loads(text[text.index('{'):text.rindex('}')+1])
    records = {str(row['opportunity_id']):row for row in catalog['opportunities']}
    evidence = policy()
    expected = evidence['previous_record_hashes']
    require(evidence['previous_candidate_id'] == PREVIOUS
        and evidence['previous_manifest_sha256'] == PREVIOUS_MANIFEST_SHA
        and set(expected) == {'nasa-roses:25-B.8-c9ad18a888', '363829'}
        and all(key in records and value_hash(records[key]) == digest for key,digest in expected.items()),
        'previous_identity_evidence')
    transitions = {'364039': 'nasa-roses:25-B.8-c9ad18a888', '363829': '363829'}
    require(len(evidence['corrections']) == 2
        and {item['opportunity_id']:item['previous_opportunity_id'] for item in evidence['corrections']} == transitions,
        'exact_identity_transitions')
    for item in evidence['corrections']:
        old = records[item['previous_opportunity_id']]
        if item['opportunity_id'] == item['previous_opportunity_id']:
            aliases = old.get('source_aliases') or []
        else:
            aliases = [{key: old[key] for key in ('opportunity_id', 'opportunity_number', 'source',
                        'detail_page', 'funding_opportunity_url') if old.get(key)}]
        require(item['source_aliases'] == aliases, 'previous_alias_values')
    return {'candidate_id': PREVIOUS, 'manifest_sha256': PREVIOUS_MANIFEST_SHA,
        'run_id': PREVIOUS_RUN, 'artifact_id': identifier, 'artifact_sha256': digest,
        'record_hashes': expected}


def authenticate(parent_bundle, *, api=auth.existing.api):
    run = original_run(RUN, EVENT_SHA, 'failure', api=api)
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
        and ledger['requests'] == [] and ledger['events'] == [
            {'kind': 'service_stop', 'reason': 'quality_gate_pending', 'service': 'teams'}], 'original_ledger')
    require(set(packets['reservation']) == {'spend-reservation.json'} and
        auth.json_value(packets['reservation']['spend-reservation.json']) == {
            'attempt': '1', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': '52d9934aedd0dde3266c52e648012bf6b218e5c434361b5a4a360ccfd41fa4ca',
            'run_id': str(RUN)}, 'original_reservation')
    vector = c.read_json(bundle/'files/evaluation/search_v2_hybrid_vector_build.json')
    require(vector['API_request_count'] == 6 and vector['usage_total_tokens'] == 300499
        and vector['estimated_cost_at_published_paid_pricing_usd'] == 0.006010, 'original_vector_accounting')
    previous = authenticate_previous(api=api)
    return original, {'original_logical_id': ledger['logical_id'], 'limit_microusd': 2_000_000,
        'max_requests': 300, 'requests_used': 0, 'charged_microusd': 0,
        'new_document_ai_requests': 0, 'new_vector_requests': 0, 'new_team_requests': 0,
        'state_hashes': {n: c.digest(raw) for n, raw in sorted(state.items())},
        'prior_vector_requests': 6, 'prior_vector_tokens': 300499, 'previous_identity': previous,
        'artifacts': {role: {'id': item[0], 'name': item[1], 'sha256': item[2]}
            for role, item in ARTIFACTS.items()}}


def verify_source_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    current = snapshot(root)
    changes = changed_groups(original['dependency_groups'], current)
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES
        and not changes.get('teams') and not changes.get('semantic'), 'bounded_dependency_changes')
    if '@generation_invocations' in changes.get('source', []):
        require(original['dependency_groups']['source']['files'].get('@generation_invocations') == INVOCATIONS_BEFORE
            and current['source']['files'].get('@generation_invocations') == INVOCATIONS_AFTER,
            'exact_previous_catalog_invocation')


def dependency_scope(root, original):
    verify_source_scope(root, original)
    c.git(root, 'merge-base', '--is-ancestor', GENERATION_SHA, 'HEAD')
    c.verify_files(root, original['runtime_baseline'])


def derive_metadata(parent_bundle, audit_at, projection, *, package_kind=None):
    """Shared deterministic rendering; each caller supplies a fixed, authenticated policy."""
    from scripts.update_catalog_docs import load_catalog, render_docs, catalog_stats, update_catalog_asset_reference
    parent = Path(parent_bundle)/'files'
    outputs, proof = projection(parent, audit_at)
    with tempfile.TemporaryDirectory(prefix='catalog-identity-projection-') as temporary:
        target = Path(temporary)/'workspace'
        vector_receipt = Path(temporary)/'identity-package.json'
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
        subprocess.run([shutil.which('node') or 'node', str(c.ROOT/'tools/catalog_identity_package.mjs'),
            '--parent', str(parent), '--root', str(target), '--receipt', str(vector_receipt)]
            + (['--kind', package_kind] if package_kind else []),
            check=True, timeout=120, capture_output=True)
        outputs[PACKAGE_OUTPUT] = (target/PACKAGE_OUTPUT).read_bytes()
        vector = c.read_json(vector_receipt)
    return outputs, {'record_projection': proof, 'package_projection': vector}


def derive(parent_bundle, audit_at):
    from tools.catalog_identity_projection import projection
    return derive_metadata(parent_bundle, audit_at, projection)


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
    verify_source_scope(root, original)
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
    return c.create(root, output, parent=parent_bundle, identity_correction=receipt_path)


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
