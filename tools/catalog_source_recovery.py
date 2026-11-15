"""Exact, provider-free recovery of selected rejected catalog candidates.

This derivation has no generation allowance. It authenticates the original
candidate/spending ZIPs, replays documented record withdrawals and copies
only unchanged vector rows. Publication still requires new exact-byte gates.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
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
ROSES_VERSION = 'catalog-source-recovery-20261113-v2'
ROSES_PARENT = 'cf3f76587bd136588a8b86ceb149224b34a10580a4a3fa64677df29a126d3487'
ROSES_RUN = 43476458676
ROSES_ATTEMPT = 1
ROSES_EVENT_SHA = 'b298444c6c4f4023388a96ed6a2ebbcf0824e837'
ROSES_MANIFEST_SHA = '04ff87ae51e717d115228a2bf1fb19ad8b03ec9363a203e649dbe31973f9f97c'
ROSES_LEDGER_SHA = 'a3897f1f269653e85617d30551db125074023c69e8dd8ad3746b2cc0fa18321d'
ROSES_PREDECESSOR = '65700404080d5ea34195759d796539751a7e4a12b85232529df08fa9d8dd3a51'
ROSES_ARTIFACTS = {
    'candidate': (14064296748, 'candidate-' + ROSES_PARENT,
        '1363d2d250498d7a53fb29a8e897b60fa5bd0d867210f746d64caad8476e6ab0'),
    'state': (14063598453, 'generation-spend-state-43476458676-1',
        '7c47b47d3819c64a82c143085bb9a0f83829419e05a445af33a7b199f366d058'),
    'reservation': (14063716213, 'generation-spend-reservation-43476458676-1',
        '3ba77ee3556508dc22905e9c1c4e3bf790adff338b81118b4cb75029a111246a'),
    'plan': (14062542364, 'release-plan-1',
        'f12122501f4c68e84dceb73404ec4da1aae9eedadc425e764293fd0dd08f409d'),
}
# The first recovery passed validation but review rejected its stale feeds.
# Retire this exact zero-generation derivation after its replacement publishes.
ROSES_REJECTED_RECOVERY = {
    'run': 43749185636,
    'head': '94e4f05a4df212c6a84401b6f4f578aca0af046e',
    'candidate_id': '5efe6b1191539cc22e191b3c97efd4bcdb6e4c2b1417c526aa26976894d68165',
    'artifacts': {
        'candidate': (14175601896, 'a2aa8b0ad838235f6b65541cf9824b3838821fd52bfcd372bb641998dcaf9275'),
        'projection': (14175457224, '9a06f2098e1e79a195de7f8f382a573f3f6ab58b96bf17f6c3913c6f70c21a76'),
        'review': (14176162839, '3ea987b6d68489ba47985aec74fa36430675bc09f81d577c928bf179b7d42b06'),
    },
}
FOA_VERSION = 'catalog-source-recovery-20261115-v1'
FOA_PARENT = 'e8bd098f1aca899ff496006f93b1b6648e88029b63d06c8f78c985ba77a8199e'
FOA_RUN = 43754874937
FOA_EVENT_SHA = 'b84e974d4110a9ec1913019872cb242c931c5863'
FOA_MANIFEST_SHA = '1901e7b34963869df707ce8421f2de7cb692534d9c8b7eafc1d566b07b694125'
FOA_ARTIFACTS = {
    'candidate': (14177807889, 'candidate-' + FOA_PARENT,
        '5670303ef0ade2580a19a66d7a897ee499789dcb38b31eafc2b282250ea369ea'),
    'state': (14177533075, 'generation-spend-state-43754874937-1',
        '52c1af59b850e8cfb006393fef463fe57eb297706323015d89d8d88cf2059e55'),
    'reservation': (14177527690, 'generation-spend-reservation-43754874937-1',
        '757e922703389db47c51a352c4e4f304c568008383d5118776f4acde2810cc06'),
    'plan': (14178121734, 'release-plan-1',
        'e4035509c996f5d3eacc81c572a77d108c652f113b42512c94ccf56f0e94c99b'),
    'review': (14178218809, 'publication-' + FOA_PARENT + '-1',
        'ca83dbb606218d4afc1a32654621d9eb7c95168f2b103e58d7aca84fde0be92e'),
}
STAGE = 'catalog-source-recovery'
VECTOR_OUTPUTS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
    'data/search-v2-release.json', 'workers/search-voyage-proxy/generated/corpus-allowlist.json')
# Only the bounded source invariant repairs may differ from the retained run.
SOURCE_REPAIR_FILES = {'scripts/solicitation_identity.py', 'scripts/sources/merge.py',
    'scripts/sources/intake.py',
    'scripts/sources/official_identity.py', 'scripts/sources/nsf_identity.py', 'scripts/sources/validate.py',
    'scripts/sources/adapters/doe_exchange.py', 'scripts/sources/adapters/doe_exchange_listing.py'}
FOA_SOURCE_REPAIR_FILES = {'scripts/build_catalog.py', 'scripts/source_documents.py',
    'scripts/enrich_catalog.py', 'scripts/pull_grants.py', 'scripts/extract_document_evidence.py',
    'scripts/subtopic_sources.py'}


@dataclass(frozen=True)
class RecoveryPolicy:
    version: str
    candidate: str
    run: int
    attempt: int
    event_sha: str
    generation_sha: str
    manifest_sha: str
    artifacts: dict
    event: str
    conclusion: str
    ledger_sha: str
    requests: int
    charged: int
    prior_ledger: str
    vector_tokens: int
    predecessor: str | None = None


def recovery_policies():
    return {
        PARENT: RecoveryPolicy(VERSION, PARENT, RUN, ATTEMPT, EVENT_SHA, GENERATION_SHA, MANIFEST_SHA,
            ARTIFACTS, 'schedule', 'cancelled', LEDGER_SHA, 66, 441023,
            'eac564e5caed08887a815aaa64ae19e0e0e01c430b77ef7abde684a5bea8370e', 298906),
        ROSES_PARENT: RecoveryPolicy(ROSES_VERSION, ROSES_PARENT, ROSES_RUN, ROSES_ATTEMPT, ROSES_EVENT_SHA,
            ROSES_EVENT_SHA, ROSES_MANIFEST_SHA, ROSES_ARTIFACTS, 'schedule', 'failure', ROSES_LEDGER_SHA, 6, 6523,
            '4404c1f0a1ef1452809c436e636e41c9c82cd32ff54dcf7ff25b61c4ef1dac91', 325974, ROSES_PREDECESSOR),
        FOA_PARENT: RecoveryPolicy(FOA_VERSION, FOA_PARENT, FOA_RUN, 1, FOA_EVENT_SHA,
            FOA_EVENT_SHA, FOA_MANIFEST_SHA, FOA_ARTIFACTS, 'workflow_dispatch', 'failure',
            'c0ecdb506e02b4341936c29c391a8db76f9abd16cf6af900812f4d070351bf6f', 6, 6366,
            '028e3803ea18754a4c054f68459dd16f9417dd26b92a1ac59b96e9a3d4817c26', 318161,
            '513d9ec3279e395d1b2352d732aa3988a27f5a8b177535b00bd98ed1cf896961'),
    }


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_source_recovery_' + reason)


def reject_quarantined(manifest):
    require(manifest.get('candidate_id') not in (*recovery_policies(), ROSES_REJECTED_RECOVERY['candidate_id']),
        'rejected_candidate_requires_exact_source_recovery')


def plan(root, environment):
    expected = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main'}
    parent, run = environment.get('CANDIDATE_ID'), environment.get('CANDIDATE_RUN')
    selected = recovery_policies().get(parent)
    require(all(environment.get(k) == v for k, v in expected.items())
        and selected is not None and run == str(selected.run), 'exact_protected_manual_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
        and environment.get('QUALIFICATION_PILOT') != 'true', 'no_other_generation_or_recovery')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'),
        'candidate_id': parent, 'candidate_run': run, 'openai': 'false', 'anthropic': 'false',
        'team_mode': 'maintenance', 'reason': 'Authenticated record withdrawal and unchanged vector-row projection; zero new generation allowance'}


def archive_files(raw):
    # Reuse the bounded, duplicate/path/link-safe decoder, even for private
    # state evidence. Only hashes and measured totals leave this temp directory.
    with tempfile.TemporaryDirectory(prefix='catalog-recovery-auth-') as temporary:
        auth.unpack_public(raw, temporary)
        root = Path(temporary)
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def authenticate(parent_bundle, *, api=auth.existing.api):
    bundle = Path(parent_bundle)
    selected = recovery_policies().get(c.read_json(bundle/'candidate.json').get('candidate_id'))
    require(selected is not None, 'known_parent_identity')
    run = auth.json_value(api(f'actions/runs/{selected.run}/attempts/{selected.attempt}'))
    require(run.get('id') == selected.run and run.get('run_attempt') == selected.attempt
        and run.get('head_sha') == selected.event_sha and run.get('head_branch') == 'main'
        and run.get('path') == auth.REFRESH and run.get('event') == selected.event
        and run.get('status') == 'completed' and run.get('conclusion') == selected.conclusion, 'original_run')
    packets = {}
    for role, (identifier, name, digest) in selected.artifacts.items():
        raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
        packets[role] = archive_files(raw)
    original = c.load(bundle, selected.candidate)
    require(c.digest((bundle/'candidate.json').read_bytes()) == selected.manifest_sha, 'manifest_pin')
    require(packets['candidate'] == {'candidate.json': (bundle/'candidate.json').read_bytes(),
        **{'files/' + n: (bundle/'files'/n).read_bytes() for n in original['files']}}, 'complete_parent')
    require(original['generation_sha'] == selected.generation_sha
        and original['generation_run_id'] == str(selected.run)
        and original['generation_run_attempt'] == str(selected.attempt), 'original_generation')
    if selected.predecessor:
        original_plan = auth.json_value(packets['plan']['release-plan.json'])
        require(original_plan['stage'] == 'generate' and original_plan['release_sha'] == selected.generation_sha
                and original_plan['candidate_id'] == selected.predecessor,
                'protected_generation_plan')
    if selected.candidate == FOA_PARENT:
        blocked = auth.json_value(packets['review']['review-blocked.json'])
        expected = {'schema_version': 1, 'status': 'review_findings', 'candidate_id': FOA_PARENT,
            'artifact_run': str(FOA_RUN), 'head_sha': '204ba70394b5a0f0a166f2ccd606d1875ebf3116',
            'pr_number': 412, 'repository': 'mporosoff/grants-scraper',
            'production_mutated': False, 'finding_count': 1}
        require(all(blocked.get(key) == value for key, value in expected.items()), 'exact_parent_rejection')
    state = packets['state']; ledger = auth.json_value(state['ledger.json'])
    require(c.digest(state['ledger.json']) == selected.ledger_sha and ledger['logical_id'] == 'offline-' + str(selected.run)
        and ledger['limit_microusd'] == 2_000_000 and ledger['max_requests'] == 300
        and len(ledger['requests']) == selected.requests
        and sum(r['charged_microusd'] for r in ledger['requests']) == selected.charged, 'original_ledger')
    require(set(packets['reservation']) == {'spend-reservation.json'} and
        auth.json_value(packets['reservation']['spend-reservation.json']) == {
            'attempt': str(selected.attempt), 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': selected.prior_ledger, 'run_id': str(selected.run)}, 'original_reservation')
    vector = c.read_json(bundle/'files/evaluation/search_v2_hybrid_vector_build.json')
    require(vector['API_request_count'] == 6 and vector['usage_total_tokens'] == selected.vector_tokens,
        'original_vector_accounting')
    ledger_evidence = {'ledger_sha256': selected.ledger_sha} if selected.predecessor else {
        'state_hashes': {n: c.digest(raw) for n, raw in sorted(state.items())}}
    return original, {'original_logical_id': ledger['logical_id'], 'limit_microusd': 2_000_000,
        'max_requests': 300, 'requests_used': selected.requests, 'charged_microusd': selected.charged,
        'new_document_ai_requests': 0, 'new_vector_requests': 0, 'new_team_requests': 0,
        **ledger_evidence,
        'prior_vector_requests': 6, 'prior_vector_tokens': selected.vector_tokens,
        'artifacts': {role: {'id': item[0], 'name': item[1], 'sha256': item[2]}
            for role, item in selected.artifacts.items()}}


def dependency_scope(root, original):
    verify_source_scope(root, original)
    selected = recovery_policies()[original.get('candidate_id', PARENT)]
    c.git(root, 'merge-base', '--is-ancestor', selected.generation_sha, 'HEAD')
    # Source correction cannot silently replace the retained runtime.
    c.verify_files(root, original['runtime_baseline'])


def verify_source_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    parent = original.get('candidate_id')
    required = {'scripts/sources/adapters/nasa_roses.py'} if parent == ROSES_PARENT else (
        {'scripts/build_catalog.py'} if parent == FOA_PARENT else set())
    allowed = FOA_SOURCE_REPAIR_FILES if parent == FOA_PARENT else required or SOURCE_REPAIR_FILES
    require(set(changes.get('source', [])) <= allowed
        and not changes.get('teams') and not changes.get('semantic'), 'bounded_dependency_changes')
    if required:
        require(required <= set(changes.get('source', [])), 'source_repair_required')


def derive(parent_bundle, audit_at):
    from scripts.update_catalog_docs import load_catalog, render_docs, catalog_stats, update_catalog_asset_reference
    bundle = Path(parent_bundle)
    parent = bundle/'files'
    parent_id = c.read_json(bundle/'candidate.json')['candidate_id']
    if parent_id == ROSES_PARENT:
        from tools.catalog_roses_withdrawal import projection
    elif parent_id == FOA_PARENT:
        from tools.catalog_foa_withdrawal import projection
    else:
        from tools.catalog_record_withdrawal import projection
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
    selected = recovery_policies()[original.get('candidate_id', PARENT)]
    receipt = {'version': selected.version, 'parent_candidate': selected.candidate,
        'parent_manifest_sha256': selected.manifest_sha,
        'parent_run': selected.run, 'audit_at': audit_at, 'spending': spending, 'projection': proof,
        'output_hashes': {n: c.digest(raw) for n, raw in sorted(outputs.items())},
        'retained_hashes': {n: h for n, h in original['files'].items() if n not in outputs
            and not c.FACET_FEED_NAME.fullmatch(n)}}
    if selected.candidate == ROSES_PARENT:
        receipt['superseded_recovery_run'] = ROSES_REJECTED_RECOVERY['run']
        receipt['superseded_recovery_candidate'] = ROSES_REJECTED_RECOVERY['candidate_id']
    return receipt


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
    selected = plan(root, dict(os.environ))
    original, spending = authenticate(parent_bundle)
    require(original['candidate_id'] == selected['candidate_id'], 'selected_parent')
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
