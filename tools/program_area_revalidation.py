"""One authenticated, zero-fetch program-area repair of the September 28 candidate.

The original document budget is evidence, never a newly allocated allowance.
A separate immutable whole-pass reservation prevents repeating vector spend,
including on a later workflow run. Interrupted paid work fails closed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from tools import catalog_smoke_receipt as auth, release_candidate as candidate
from tools.offline_spend import atomic_json

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'program-area-revalidation-1'
PARENT_CANDIDATE = '85954ae156ca45aea2b6bac4db500f747e9e64725c230716087b085817c0c1de'
PARENT_RUN = 36480049073
PARENT_ATTEMPT = 2
PARENT_EVENT_SHA = '9ce9d8143c9998a8e2fa61f567907cd82ca308ef'
PARENT_GENERATION_SHA = '1ce50e3cc16be1d0c9de1dc2c4643b85c3ad2b1d'
PARENT_EXTRACTOR_SHA256 = '8a252f08fd516853a20ed25783f9656b9b2b7e9bd372e717057b5b0b913c31e5'
PARENT_MANIFEST_SHA256 = '9e10cf7605e52d70162ed355b86ca1108d0c9a634929b8c9530ddaad00295546'
PARENT_ARTIFACTS = {
    'candidate': (11000691178, 'candidate-' + PARENT_CANDIDATE,
        'e23d5f2d5e375e0cfdfb26281e2184b0ef5ed211f815d762866536d8679ca184'),
    'state': (11000741012, 'generation-spend-state-36480049073-2',
        '998b347ebb0ee5abdcfd134f3087540409b15c047634081f388386ef83b5ca00'),
    'reservation': (10999829648, 'generation-spend-reservation-36480049073-2',
        '7d3e00c0f7bdccc0ec92f304dc78990b40a74ba5d93da6892d2dfea54cf5c7c0'),
}
PROJECTION = ('data/opportunities.js', 'data/catalog-metadata.js', 'data/document_evidence.json',
    'feeds/all.xml', 'feeds/index.html', 'feeds/index.json')
VECTORS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
    'data/search-v2-voyage-canaries.json', 'evaluation/search_v2_hybrid_vector_build.json')
PREFIX = 'program-area-vectors-' + PARENT_CANDIDATE + '-'
MAX_REQUESTS = 8
MAX_SECONDS = 960
PARENT_VECTOR_RECEIPT_SHA256 = '915c49a3da9e8c3a91421e9dac4d7011acc02ebd596a2f64c4391c95720ca660'
DERIVED_KEYS = {'topic_areas', 'document_program_areas', 'document_search_text'}


def require(ok, reason):
    if not ok:
        raise ValueError('program_area_revalidation_' + reason)


def sha(raw):
    return candidate.digest(raw)


def read(path):
    return auth.json_value(Path(path).read_bytes())


def hashes(root, names):
    return candidate.file_hashes(Path(root), names)


def timestamp(value):
    require(isinstance(value, str), 'timestamp_type')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'timestamp_timezone')
    return parsed


def zip_files(raw):
    with tempfile.TemporaryDirectory(prefix='program-area-auth-') as temporary:
        path = Path(temporary)
        auth.unpack_public(raw, path)
        return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}


def authenticate_parent(parent_bundle, *, api=auth.existing.api):
    """Authenticate server metadata, raw ZIPs, complete manifest and spend owner."""
    run = auth.trusted_run(PARENT_RUN, auth.REFRESH, terminal=False, allow_failed=True,
        attempt=PARENT_ATTEMPT, api=api)
    require(run['head_sha'] == PARENT_EVENT_SHA, 'parent_event_sha')
    packets = {}
    for role, (identifier, name, digest) in PARENT_ARTIFACTS.items():
        raw, _ = auth.authenticated_zip(identifier, name, run, 'sha256:' + digest, api=api)
        packets[role] = zip_files(raw)
    raw_manifest = packets['candidate'].get('candidate.json', b'')
    require(sha(raw_manifest) == PARENT_MANIFEST_SHA256, 'parent_manifest_digest')
    require(set(packets['state']) == {'ledger.json', 'team-progress.json', 'usage-summary.json'}
        and set(packets['reservation']) == {'spend-reservation.json'}, 'parent_spend_archive_members')
    ledger = auth.json_value(packets['state']['ledger.json'])
    reservation = auth.json_value(packets['reservation']['spend-reservation.json'])
    require(ledger.get('logical_id') == 'offline-' + str(PARENT_RUN)
        and ledger.get('limit_microusd') == 2_000_000 and ledger.get('max_requests') == 300
        and ledger.get('requests') == [], 'parent_document_ledger')
    require(reservation == {'attempt': '2', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
        'prior_ledger_hash': 'ca9b06673147b96f093e891f870da4d5039f0c5dc300caf39348b740d2c475ee',
        'run_id': str(PARENT_RUN)}, 'parent_document_reservation')
    bundle = Path(parent_bundle)
    original = candidate.load(bundle, PARENT_CANDIDATE)
    require((bundle / 'candidate.json').read_bytes() == raw_manifest, 'local_parent_manifest')
    expected = {'candidate.json': raw_manifest, **{'files/' + n: (bundle/'files'/n).read_bytes()
        for n in original['files']}}
    require(packets['candidate'] == expected, 'complete_authenticated_parent')
    require(original['generation_sha'] == PARENT_GENERATION_SHA
        and str(original['generation_run_id']) == str(PARENT_RUN)
        and str(original['generation_run_attempt']) == '2'
        and original['dependency_groups']['source']['files']['scripts/extract_document_evidence.py']
            == PARENT_EXTRACTOR_SHA256, 'parent_generation_identity')
    require(sha((bundle/'files'/VECTORS[3]).read_bytes()) == PARENT_VECTOR_RECEIPT_SHA256,
        'parent_vector_receipt')
    vector = read(bundle/'files'/VECTORS[3])
    require(vector['API_request_count'] == 7 and vector['usage_total_tokens'] == 313283
        and read(bundle/'files'/VECTORS[0])['reuse_permitted'] is False, 'parent_vector_spend')
    return original, {'logical_id': ledger['logical_id'], 'document_limit_microusd': 2_000_000,
        'document_requests': 0, 'ledger_sha256': sha(packets['state']['ledger.json']),
        'prior_vector_receipt_sha256': PARENT_VECTOR_RECEIPT_SHA256,
        'prior_vector_requests': 7, 'prior_vector_tokens': 313283,
        'artifacts': {role: {'id': v[0], 'name': v[1], 'sha256': v[2]} for role, v in PARENT_ARTIFACTS.items()}}


def inventory(*, api=auth.existing.api):
    """Complete repository-wide inventory: a new workflow run is not a new budget."""
    result = []
    for page in range(1, 101):
        payload = auth.json_value(api(f'actions/artifacts?per_page=100&page={page}'))
        rows = payload.get('artifacts')
        require(isinstance(rows, list) and type(payload.get('total_count')) is int, 'artifact_inventory')
        result.extend(rows)
        if len(rows) < 100:
            require(len(result) == payload['total_count'], 'complete_artifact_inventory')
            require(len({row['id'] for row in result}) == len(result), 'unique_artifact_inventory')
            return [row for row in result if row.get('name', '').startswith(PREFIX)]
    raise ValueError('program_area_revalidation_artifact_inventory_bound')


def checkpoint_artifact(meta, kind, *, api=auth.existing.api):
    match = re.fullmatch(re.escape(PREFIX + kind + '-') + r'([1-9][0-9]*)-([1-9][0-9]*)', meta.get('name', ''))
    require(match is not None, 'checkpoint_name')
    run = auth.trusted_run(int(match[1]), auth.REFRESH, terminal=False, allow_failed=True,
        attempt=int(match[2]), api=api)
    raw, _ = auth.authenticated_zip(meta['id'], meta['name'], run, meta.get('digest'), api=api)
    return zip_files(raw), {'run_id': run['id'], 'run_attempt': run['run_attempt'], 'head_sha': run['head_sha']}


def history(*, api=auth.existing.api):
    rows = inventory(api=api)
    reservations = [r for r in rows if r['name'].startswith(PREFIX + 'reservation-')]
    states = [r for r in rows if r['name'].startswith(PREFIX + 'state-')]
    require(len(rows) == len(reservations) + len(states), 'unknown_checkpoint_artifact')
    require(len(reservations) <= 1 and len(states) <= 1, 'conflicting_vector_owners')
    require(not states or reservations, 'orphan_vector_state')
    if not reservations:
        return None, None
    files, owner = checkpoint_artifact(reservations[0], 'reservation', api=api)
    require(set(files) == {'reservation.json'}, 'reservation_members')
    reservation = auth.json_value(files['reservation.json'])
    require(reservation.get('version') == VERSION and reservation.get('parent_candidate') == PARENT_CANDIDATE
        and reservation.get('owner') == owner and reservation.get('max_requests') == MAX_REQUESTS
        and reservation.get('max_seconds') == MAX_SECONDS, 'reservation_identity')
    if not states:
        return reservation, None
    files, state_owner = checkpoint_artifact(states[0], 'state', api=api)
    require(state_owner == owner, 'checkpoint_owner')
    cp = auth.json_value(files.get('checkpoint.json', b'{}'))
    expected = {'receipt.json', 'reservation.json', 'checkpoint.json',
        'prior-vector-receipt.json', *('files/' + n for n in PROJECTION + VECTORS)}
    require(set(files) == expected and files['reservation.json'] == candidate.encoded(reservation),
        'complete_checkpoint_members')
    require(cp.get('version') == VERSION and cp.get('owner') == owner
        and cp.get('files') == {n: sha(raw) for n, raw in files.items() if n != 'checkpoint.json'},
        'checkpoint_integrity')
    receipt = auth.json_value(files['receipt.json'])
    require(reservation['receipt_sha256'] == sha(files['receipt.json'])
        and reservation['projection_hashes'] == receipt.get('projection_hashes')
        and sha(files['prior-vector-receipt.json']) == PARENT_VECTOR_RECEIPT_SHA256
        and {n: sha(files['files/' + n]) for n in PROJECTION} == receipt['projection_hashes'],
        'checkpoint_projection_binding')
    return reservation, files


def projection(parent_root, audit_at):
    """Pure replay plus an explicit firewall around all non-program-area facts."""
    from scripts import extract_document_evidence as evidence
    from scripts.build_catalog import facet_counts, catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.enrich_catalog import read_catalog
    from scripts.subtopic_records import read_cache
    from tools.verify_notice_publication import verify
    parent_root = Path(parent_root)
    before = read_catalog(parent_root/PROJECTION[0]); cache = read(parent_root/PROJECTION[2])
    stamp = before['document_evidence_generated_at']
    timestamp(audit_at)
    require(timestamp(audit_at) >= timestamp(stamp), 'audit_precedes_original_evidence')
    after, updated, identifiers = evidence.revalidate_program_areas_only(deepcopy(before), deepcopy(cache), now=timestamp(stamp))
    after['facets'] = facet_counts(after['opportunities'])
    after['catalog_audit_generated_at'] = audit_at
    require(after['document_evidence_generated_at'] == stamp and updated['generated_at'] == cache['generated_at'],
        'original_evidence_clock')
    require(len(after['opportunities']) == len(before['opportunities']), 'row_count')
    changed = []
    for old, new in zip(before['opportunities'], after['opportunities'], strict=True):
        require({k: v for k, v in old.items() if k not in DERIVED_KEYS}
            == {k: v for k, v in new.items() if k not in DERIVED_KEYS}, 'unchanged_facts_and_membership')
        if old != new:
            changed.append(str(old['opportunity_id']))
            require(str(old['opportunity_id']) in identifiers, 'affected_rows_only')
    require({k: v for k, v in before.items() if k not in {'opportunities', 'facets', 'search_index', 'catalog_audit_generated_at'}}
        == {k: v for k, v in after.items() if k not in {'opportunities', 'facets', 'search_index', 'catalog_audit_generated_at'}},
        'unchanged_catalog_clocks_and_diagnostics')
    stripped = deepcopy(updated)
    require(set(cache.get('records', {})) == set(updated.get('records', {})), 'unchanged_evidence_membership')
    for identifier, entry in updated['records'].items():
        previous = cache['records'][identifier]
        require(all(hit in previous.get('program_areas', []) for hit in entry.get('program_areas', [])),
            'no_new_evidence_hits')
        if 'program_areas' in previous:
            stripped['records'][identifier]['program_areas'] = previous['program_areas']
        else:
            stripped['records'][identifier].pop('program_areas', None)
    require(stripped == cache, 'unchanged_evidence_facts_and_clocks')
    gate = verify(after, updated, read_cache(parent_root/'data/subtopics.js'), candidate_id=PARENT_CANDIDATE)
    require(gate['publication_ready'], 'notice_projection_gate')
    cache_bytes = (json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    outputs = {PROJECTION[0]: catalog_javascript_bytes(after), PROJECTION[1]: catalog_metadata_javascript_bytes(after),
        PROJECTION[2]: cache_bytes}
    from scripts.build_feeds import build_feeds
    with tempfile.TemporaryDirectory(prefix='program-area-feeds-') as directory:
        feeds = Path(directory)
        # Preserve historical change events and the original package inventory.
        # The builder sees changes.xml so its existing index entry is retained.
        if (parent_root/'feeds/changes.xml').is_file():
            (feeds/'changes.xml').write_bytes((parent_root/'feeds/changes.xml').read_bytes())
        build_feeds(after, feeds, as_of=timestamp(stamp).date())
        for name in PROJECTION[3:]:
            outputs[name] = (feeds/Path(name).name).read_text(encoding='utf-8').encode('utf-8')
    return outputs, {'affected_evidence_ids': identifiers, 'affected_catalog_ids': changed,
        'original_source_at': before['generated_at'], 'original_evidence_at': stamp,
        'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0}


def receipt_for(original, spending, outputs, changes, audit_at):
    return {'version': VERSION, 'parent_candidate': PARENT_CANDIDATE, 'parent_run': PARENT_RUN,
        'parent_generation_sha': PARENT_GENERATION_SHA, 'parent_manifest_sha256': PARENT_MANIFEST_SHA256,
        'audit_at': audit_at, 'spending': spending, 'projection': changes,
        'projection_hashes': {n: sha(raw) for n, raw in outputs.items()},
        'retained_hashes': {n: h for n, h in original['generation_files'].items() if n not in PROJECTION + VECTORS}}


def verify_dependency_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(changes.get('source') == ['scripts/extract_document_evidence.py']
        and not changes.get('teams') and not changes.get('semantic'), 'only_program_area_extractor_dependency_change')
    candidate.git(root, 'merge-base', '--is-ancestor', PARENT_GENERATION_SHA, 'HEAD')


def require_original_correction_run(reservation, *, api=auth.existing.api):
    if reservation:
        current = owner(api=api)
        require(current['run_id'] == reservation['owner']['run_id'],
            'resume_original_correction_run_' + str(reservation['owner']['run_id']))


def prepare(parent_bundle, receipt_path, *, root=ROOT, api=auth.existing.api):
    original, spending = authenticate_parent(parent_bundle, api=api)
    verify_dependency_scope(root, original)
    reservation, files = history(api=api)
    require_original_correction_run(reservation, api=api)
    require(not reservation or files, 'prior_vector_reservation_requires_complete_checkpoint')
    audit_at = auth.json_value(files['receipt.json'])['audit_at'] if files else datetime.now(timezone.utc).isoformat()
    outputs, changes = projection(Path(parent_bundle)/'files', audit_at)
    receipt = receipt_for(original, spending, outputs, changes, audit_at)
    if files:
        require(candidate.encoded(receipt) == files['receipt.json'], 'replay_differs_from_checkpoint')
    root = Path(root)
    for name in original['generation_files']:
        target = candidate.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(parent_bundle)/'files'/name).read_bytes())
    for name, raw in outputs.items():
        candidate.checked_path(root, name).write_bytes(raw)
    atomic_json(receipt_path, receipt)
    return receipt


def validate_receipt(receipt_path, root):
    receipt = read(receipt_path)
    require(receipt.get('version') == VERSION and receipt.get('parent_candidate') == PARENT_CANDIDATE
        and receipt.get('parent_run') == PARENT_RUN and receipt.get('parent_generation_sha') == PARENT_GENERATION_SHA
        and receipt.get('parent_manifest_sha256') == PARENT_MANIFEST_SHA256, 'receipt_parent')
    timestamp(receipt['audit_at'])
    require(hashes(root, PROJECTION) == receipt.get('projection_hashes')
        and hashes(root, receipt['retained_hashes']) == receipt['retained_hashes'], 'receipt_input_hashes')
    return receipt


def owner(*, api=auth.existing.api):
    run_id = os.environ.get('GITHUB_RUN_ID', ''); attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    require(run_id.isdigit() and attempt.isdigit(), 'workflow_owner_required')
    run = auth.trusted_run(int(run_id), auth.REFRESH, terminal=False, allow_failed=True, attempt=int(attempt), api=api)
    require(os.environ.get('GITHUB_SHA') == run['head_sha'], 'workflow_head')
    return {'run_id': run['id'], 'run_attempt': run['run_attempt'], 'head_sha': run['head_sha']}


def artifact_name(kind, value):
    return f"{PREFIX}{kind}-{value['run_id']}-{value['run_attempt']}"


def reserve_vectors(receipt_path, reservation_path, *, root=ROOT, api=auth.existing.api):
    receipt = validate_receipt(receipt_path, root)
    prior, files = history(api=api)
    require(prior is None and files is None, 'vector_pass_already_reserved')
    value = {'version': VERSION, 'parent_candidate': PARENT_CANDIDATE, 'owner': owner(api=api),
        'receipt_sha256': sha(candidate.encoded(receipt)), 'projection_hashes': receipt['projection_hashes'],
        'original_spending': receipt['spending'], 'max_requests': MAX_REQUESTS, 'max_seconds': MAX_SECONDS}
    require(not Path(reservation_path).exists(), 'local_reservation_already_exists')
    atomic_json(reservation_path, value)
    return value


def validate_vectors(root):
    """Read-only full asset/corpus validation; no provider is available here."""
    root = Path(root)
    result = subprocess.run([shutil.which('node') or 'node', str(ROOT/'tools/program_area_revalidation.mjs'), str(root)],
        capture_output=True, timeout=120, check=False)
    require(result.returncode == 0, 'coherent_vector_asset_and_corpus')
    manifest = read(root/VECTORS[0]); receipt = read(root/VECTORS[3])
    requests = receipt.get('API_requests', [])
    require(receipt.get('status') == 'written' and receipt.get('model') == 'voyage-4-lite'
        and manifest.get('dimension') == 1024 and manifest.get('passage_count') == 1557
        and receipt.get('passage_count') == 1557 and receipt.get('reused_passage_count') == 0
        and receipt.get('embedded_passage_count') == 1557 and receipt.get('API_request_count') == len(requests)
        and 0 < len(requests) <= MAX_REQUESTS
        and all(r.get('http_status') == 200 and r.get('model') == 'voyage-4-lite'
            and type(r.get('usage_total_tokens')) is int and r['usage_total_tokens'] >= 0 for r in requests)
        and receipt.get('usage_total_tokens') == sum(r['usage_total_tokens'] for r in requests)
        and receipt.get('source_hashes') == hashes(root, ('assets/search-hybrid.js', 'data/opportunities.js', 'data/subtopics.js'))
        and receipt.get('corpus_sha256') == manifest.get('corpus_sha256')
        and receipt.get('vector_sha256') == manifest.get('vector_sha256'), 'vector_receipt_and_budget')


def restore_vectors(receipt_path, state_path, *, root=ROOT, api=auth.existing.api):
    receipt = validate_receipt(receipt_path, root)
    reservation, files = history(api=api)
    require_original_correction_run(reservation, api=api)
    if reservation is None:
        return False
    require(files is not None, 'prior_vector_reservation_requires_complete_checkpoint')
    require(files['receipt.json'] == candidate.encoded(receipt), 'restore_receipt')
    for name in VECTORS:
        candidate.checked_path(root, name).write_bytes(files['files/' + name])
    validate_vectors(root)
    state = Path(state_path); state.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        target = candidate.checked_path(state, name); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    return True


def checkpoint_vectors(receipt_path, state_path, *, root=ROOT, api=auth.existing.api):
    receipt = validate_receipt(receipt_path, root)
    reservation, previous = history(api=api)
    require(reservation is not None and previous is None, 'unique_uploaded_vector_reservation')
    require(reservation['owner'] == owner(api=api)
        and reservation['receipt_sha256'] == sha(candidate.encoded(receipt)), 'reserved_vector_owner_and_inputs')
    validate_vectors(root)
    state = Path(state_path)
    require(not state.exists() or not any(state.iterdir()), 'fresh_checkpoint_directory')
    state.mkdir(parents=True, exist_ok=True)
    files = {'receipt.json': candidate.encoded(receipt), 'reservation.json': candidate.encoded(reservation)}
    parent_run = auth.trusted_run(PARENT_RUN, auth.REFRESH, terminal=False, allow_failed=True, attempt=2, api=api)
    ident, name, digest = PARENT_ARTIFACTS['candidate']
    raw, _ = auth.authenticated_zip(ident, name, parent_run, 'sha256:' + digest, api=api)
    files['prior-vector-receipt.json'] = zip_files(raw)['files/' + VECTORS[3]]
    files.update({'files/' + n: candidate.checked_path(root, n).read_bytes() for n in PROJECTION + VECTORS})
    cp = {'version': VERSION, 'owner': reservation['owner'], 'files': {n: sha(raw) for n, raw in files.items()}}
    for name, raw in {**files, 'checkpoint.json': candidate.encoded(cp)}.items():
        target = candidate.checked_path(state, name); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    return cp


def verify_inputs(root, original, receipt_path, *, api=auth.existing.api):
    """Constructor gate: authenticated parent, deterministic replay and uploaded state."""
    receipt = validate_receipt(receipt_path, root)
    with tempfile.TemporaryDirectory(prefix='program-area-parent-') as directory:
        bundle = Path(directory)
        parent_run = auth.trusted_run(PARENT_RUN, auth.REFRESH, terminal=False, allow_failed=True, attempt=2, api=api)
        ident, name, digest = PARENT_ARTIFACTS['candidate']
        raw, _ = auth.authenticated_zip(ident, name, parent_run, 'sha256:' + digest, api=api)
        auth.unpack_public(raw, bundle)
        authenticated, spending = authenticate_parent(bundle, api=api)
        require(original == authenticated, 'constructor_original_parent')
        verify_dependency_scope(root, authenticated)
        outputs, changes = projection(bundle/'files', receipt['audit_at'])
        require(receipt == receipt_for(authenticated, spending, outputs, changes, receipt['audit_at']), 'deterministic_receipt')
    reservation, files = history(api=api)
    require_original_correction_run(reservation, api=api)
    require(reservation is not None and files is not None, 'uploaded_vector_checkpoint_required')
    require(files['receipt.json'] == candidate.encoded(receipt)
        and all(candidate.checked_path(root, n).read_bytes() == files['files/' + n] for n in PROJECTION + VECTORS),
        'uploaded_projection_and_vector_bytes')
    validate_vectors(root)
    return receipt['retained_hashes']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'vectors-restore', 'vectors-reserve', 'vectors-checkpoint'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--parent-bundle', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--reservation', type=Path)
    args = parser.parse_args(); outputs = {'receipt_path': str(args.receipt)}
    if args.action == 'prepare':
        require(args.parent_bundle is not None, 'parent_bundle_required')
        prepare(args.parent_bundle, args.receipt, root=args.root)
    elif args.action == 'vectors-restore':
        require(args.state is not None, 'state_path_required')
        outputs['restored'] = str(restore_vectors(args.receipt, args.state, root=args.root)).lower()
    elif args.action == 'vectors-reserve':
        require(args.reservation is not None and args.reservation.name == 'reservation.json', 'reservation_filename')
        value = reserve_vectors(args.receipt, args.reservation, root=args.root)
        outputs.update(artifact_name=artifact_name('reservation', value['owner']), artifact_path=str(args.reservation))
    else:
        require(args.state is not None, 'state_path_required')
        value = checkpoint_vectors(args.receipt, args.state, root=args.root)
        outputs.update(artifact_name=artifact_name('state', value['owner']), artifact_path=str(args.state))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in outputs.items():
                stream.write(f'{key}={value}\n')
    print(json.dumps(outputs, sort_keys=True))


if __name__ == '__main__':
    main()
