"""Revalidate cached program-area evidence without repeating source or team work.

Modern native candidates retain their original logical allowance and accepted
vector responses. The finite historical whole-pass route remains isolated.
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
from tools.offline_spend import identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'program-area-revalidation-2'
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
FACET_FEED = re.compile(r'feeds/(?:topic|source-type)/[a-z0-9]+(?:-[a-z0-9]+)*\.xml')
VECTORS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
    'data/search-v2-voyage-canaries.json', 'evaluation/search_v2_hybrid_vector_build.json')
PREFIX = 'program-area-vectors-' + PARENT_CANDIDATE + '-'
MAX_REQUESTS = 8
MAX_SECONDS = 960
PARENT_VECTOR_RECEIPT_SHA256 = '915c49a3da9e8c3a91421e9dac4d7011acc02ebd596a2f64c4391c95720ca660'
DERIVED_KEYS = {'topic_areas', 'document_program_areas', 'document_search_text'}
MODERN_VERSION = 'program-area-revalidation-modern-1'
MODERN_OPERATION_FILES = ('tools/program_area_revalidation.py', 'tools/program_area_release.py',
    'scripts/extract_document_evidence.py', 'scripts/build_feeds.py',
    'tools/build_search_release_package.mjs', 'tools/run_budgeted_vectors.mjs',
    'tools/catalog_reconcile_spend.py', 'tools/embedding_contract.mjs',
    '.github/workflows/refresh-opportunities.yml')


def require(ok, reason):
    if not ok:
        raise ValueError('program_area_revalidation_' + reason)


def sha(raw):
    return candidate.digest(raw)


def read(path):
    return auth.json_value(Path(path).read_bytes())


def hashes(root, names):
    return candidate.file_hashes(Path(root), names)


def projection_names(receipt):
    """The fixed catalog outputs plus a bounded, explicit managed feed inventory."""
    values = receipt.get('projection_hashes')
    require(isinstance(values, dict) and set(PROJECTION) <= set(values) and len(values) <= 256,
        'complete_projection_inventory')
    require(all(isinstance(name, str) and (name in PROJECTION or FACET_FEED.fullmatch(name))
        and isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) for name, value in values.items()),
        'projection_paths_and_hashes')
    return tuple(sorted(values))


def managed_feed_names(root):
    """Inventory owned feed files without following symlinks or junctions."""
    root = Path(root)
    for directory in (root/'feeds', root/'feeds/topic', root/'feeds/source-type'):
        require(not directory.is_symlink() and not getattr(directory, 'is_junction', lambda: False)(),
            'managed_feed_directory_link')
        if directory.exists():
            require(directory.is_dir() and directory.resolve().is_relative_to(root.resolve()), 'managed_feed_directory')
    names = {name for name in PROJECTION[3:] if candidate.checked_path(root, name).is_file()}
    for group in ('topic', 'source-type'):
        for path in (root/'feeds'/group).glob('*.xml'):
            name = path.relative_to(root).as_posix()
            require(FACET_FEED.fullmatch(name) and candidate.checked_path(root, name).is_file(), 'managed_feed_path')
            names.add(name)
    return names


def feed_projection(catalog, changes_xml=None):
    """Use the normal feed writer and retain every generated feed, with stable LF bytes."""
    from scripts.build_feeds import build_feeds
    stamp = catalog['document_evidence_generated_at']
    with tempfile.TemporaryDirectory(prefix='program-area-feeds-') as directory:
        root = Path(directory); feeds = root/'feeds'; feeds.mkdir()
        # Historical events are untouched. Their presence controls the index link.
        if changes_xml is not None:
            (feeds/'changes.xml').write_bytes(changes_xml)
        build_feeds(catalog, feeds, as_of=timestamp(stamp).date())
        return {name: (root/name).read_text(encoding='utf-8').encode('utf-8')
            for name in sorted(managed_feed_names(root))}


def verify_feed_index(files, names, *, changes_present):
    """No advertised facet feed may be omitted from the authenticated projection."""
    from scripts.build_feeds import FEEDS_BASE
    rows = auth.json_value(files['feeds/index.json']).get('feeds')
    require(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get('url'), str) for row in rows),
        'feed_index')
    urls = [row['url'] for row in rows]
    expected = {FEEDS_BASE + '/' + name.removeprefix('feeds/') for name in names if name.endswith('.xml')}
    if changes_present:
        expected.add(FEEDS_BASE + '/changes.xml')
    require(len(urls) == len(set(urls)) and set(urls) == expected, 'complete_feed_index_inventory')


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
    receipt = auth.json_value(files.get('receipt.json', b'{}'))
    projected = projection_names(receipt)
    expected = {'receipt.json', 'reservation.json', 'checkpoint.json',
        'prior-vector-receipt.json', *('files/' + n for n in projected + VECTORS)}
    require(set(files) == expected and files['reservation.json'] == candidate.encoded(reservation),
        'complete_checkpoint_members')
    require(cp.get('version') == VERSION and cp.get('owner') == owner
        and cp.get('files') == {n: sha(raw) for n, raw in files.items() if n != 'checkpoint.json'},
        'checkpoint_integrity')
    require(reservation['receipt_sha256'] == sha(files['receipt.json'])
        and reservation['projection_hashes'] == receipt.get('projection_hashes')
        and sha(files['prior-vector-receipt.json']) == PARENT_VECTOR_RECEIPT_SHA256
        and {n: sha(files['files/' + n]) for n in projected} == receipt['projection_hashes'],
        'checkpoint_projection_binding')
    verify_feed_index({n: files['files/' + n] for n in projected}, projected,
        changes_present='feeds/changes.xml' in receipt.get('retained_hashes', {}))
    return reservation, files


def projection(parent_root, audit_at, candidate_id=PARENT_CANDIDATE):
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
    gate = verify(after, updated, read_cache(parent_root/'data/subtopics.js'), candidate_id=candidate_id)
    require(gate['publication_ready'], 'notice_projection_gate')
    cache_bytes = (json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    outputs = {PROJECTION[0]: catalog_javascript_bytes(after), PROJECTION[1]: catalog_metadata_javascript_bytes(after),
        PROJECTION[2]: cache_bytes}
    changes_path = parent_root/'feeds/changes.xml'
    outputs.update(feed_projection(after, changes_path.read_bytes() if changes_path.is_file() else None))
    verify_feed_index(outputs, outputs, changes_present=changes_path.is_file())
    return outputs, {'affected_evidence_ids': identifiers, 'affected_catalog_ids': changed,
        'original_source_at': before['generated_at'], 'original_evidence_at': stamp,
        'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0}


def receipt_for(original, spending, outputs, changes, audit_at):
    return {'version': VERSION, 'parent_candidate': PARENT_CANDIDATE, 'parent_run': PARENT_RUN,
        'parent_generation_sha': PARENT_GENERATION_SHA, 'parent_manifest_sha256': PARENT_MANIFEST_SHA256,
        'audit_at': audit_at, 'spending': spending, 'projection': changes,
        'projection_hashes': {n: sha(raw) for n, raw in outputs.items()},
        'retained_hashes': {n: h for n, h in original['generation_files'].items()
            if n not in outputs and n not in VECTORS and not FACET_FEED.fullmatch(n)}}


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
    # Only remove obsolete direct XML outputs in the feed writer's two owned
    # directories. Never delete historical changes or unrecognized paths.
    obsolete = managed_feed_names(root) - set(outputs)
    require(all(FACET_FEED.fullmatch(name) for name in obsolete), 'obsolete_managed_feed_scope')
    for name in obsolete:
        candidate.checked_path(root, name).unlink()
    for name in original['generation_files']:
        if FACET_FEED.fullmatch(name) and name not in outputs:
            continue
        target = candidate.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(parent_bundle)/'files'/name).read_bytes())
    for name, raw in outputs.items():
        target = candidate.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    require(managed_feed_names(root) == {n for n in outputs if n.startswith('feeds/')}, 'prepared_feed_inventory')
    atomic_json(receipt_path, receipt)
    return receipt


def validate_receipt(receipt_path, root):
    receipt = read(receipt_path)
    require(receipt.get('version') == VERSION and receipt.get('parent_candidate') == PARENT_CANDIDATE
        and receipt.get('parent_run') == PARENT_RUN and receipt.get('parent_generation_sha') == PARENT_GENERATION_SHA
        and receipt.get('parent_manifest_sha256') == PARENT_MANIFEST_SHA256, 'receipt_parent')
    timestamp(receipt['audit_at'])
    projected = projection_names(receipt)
    require(hashes(root, projected) == receipt.get('projection_hashes')
        and hashes(root, receipt['retained_hashes']) == receipt['retained_hashes'], 'receipt_input_hashes')
    feeds = {n for n in projected if n.startswith('feeds/')}
    require(managed_feed_names(root) == feeds, 'complete_local_feed_inventory')
    from scripts.enrich_catalog import read_catalog
    changes_path = Path(root)/'feeds/changes.xml'
    expected = feed_projection(read_catalog(Path(root)/PROJECTION[0]),
        changes_path.read_bytes() if changes_path.is_file() else None)
    require({n: sha(raw) for n, raw in expected.items()} == {n: receipt['projection_hashes'][n] for n in feeds},
        'deterministic_feed_projection')
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
    files.update({'files/' + n: candidate.checked_path(root, n).read_bytes() for n in projection_names(receipt) + VECTORS})
    cp = {'version': VERSION, 'owner': reservation['owner'], 'files': {n: sha(raw) for n, raw in files.items()}}
    for name, raw in {**files, 'checkpoint.json': candidate.encoded(cp)}.items():
        target = candidate.checked_path(state, name); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    return cp


def verify_inputs(root, original, receipt_path, *, api=auth.existing.api):
    """Constructor gate: authenticated parent, deterministic replay and uploaded state."""
    if Path(receipt_path).is_file() and read(receipt_path).get('version') == MODERN_VERSION:
        return verify_modern_inputs(root, original, receipt_path, api=api)
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
        and all(candidate.checked_path(root, n).read_bytes() == files['files/' + n] for n in projection_names(receipt) + VECTORS),
        'uploaded_projection_and_vector_bytes')
    validate_vectors(root)
    return receipt['retained_hashes']


def modern_prefix(identifier):
    require(isinstance(identifier, str) and re.fullmatch('[a-f0-9]{64}', identifier), 'modern_parent_selector')
    return 'offline-ai-program-area-' + identifier


def modern_contract(root):
    return hashes(root, MODERN_OPERATION_FILES)


def modern_scope(root, original):
    from tools.release_dependencies import snapshot, changed_groups
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= {'scripts/extract_document_evidence.py'}
        and not changes.get('teams') and not changes.get('semantic'), 'modern_extractor_only_change')
    candidate.git(root, 'merge-base', '--is-ancestor', original['generation_sha'], 'HEAD')


def modern_producer(run):
    return {'run_id': str(run['id']), 'run_attempt': str(run['run_attempt']),
        'head_sha': run['head_sha'], 'event': run['event'], 'path': run['path']}


def modern_run(run, attempt, api, *, current=False):
    meta = auth.json_value(api(f'actions/runs/{run}/attempts/{attempt}'))
    require(str(meta.get('id')) == str(run) and str(meta.get('run_attempt')) == str(attempt)
        and meta.get('head_branch') == 'main' and meta.get('path') == auth.REFRESH
        and meta.get('event') in ({'workflow_dispatch'} if current else {'push', 'schedule', 'workflow_dispatch'})
        and re.fullmatch('[a-f0-9]{40}', str(meta.get('head_sha', '')))
        and meta.get('status') in ({'in_progress', 'completed'} if current else {'completed'}),
        'modern_protected_producer')
    return meta


def modern_packet(repository, run, artifact, api):
    from tools.fetch_release_artifact import artifact_bytes
    require(artifact.get('expired') is False and re.fullmatch('sha256:[a-f0-9]{64}', artifact.get('digest', ''))
        and str(artifact.get('workflow_run', {}).get('id')) == str(run['id'])
        and artifact['workflow_run'].get('head_sha') == run['head_sha']
        and artifact['workflow_run'].get('head_branch') == 'main', 'modern_artifact_origin')
    raw = artifact_bytes(repository, str(run['id']), artifact, api)
    require('sha256:' + sha(raw) == artifact['digest'], 'modern_artifact_digest')
    return raw


def modern_unpack(raw, destination):
    from tools.catalog_reconcile import unpack
    unpack(raw, destination)


def hydrate_public_bundle(destination, manifest, sources):
    """Fill missing private copies only with exact authenticated public bytes.

    Callers authenticate each source's native artifact first. Validate the
    entire destination and all missing-byte proofs before writing anything.
    Present corruption and extra members are never repaired or discarded.
    """
    destination = Path(destination)
    require(manifest.get('candidate_id') == sha(candidate.encoded(
        {k: v for k, v in manifest.items() if k != 'candidate_id'}))
        and (destination/'candidate.json').read_bytes() == candidate.encoded(manifest), 'hydration_manifest_identity')
    expected = {'candidate.json', *('files/' + name for name in manifest['files'])}
    directories = {parent.as_posix() for name in expected for parent in Path(name).parents if str(parent) != '.'}
    actual = set()
    require(not destination.is_symlink() and not getattr(destination, 'is_junction', lambda: False)(),
        'hydration_directory_link')
    for path in destination.rglob('*'):
        name = path.relative_to(destination).as_posix()
        require(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'hydration_member_link')
        if path.is_dir():
            require(name in directories, 'hydration_extra_directory')
        else:
            require(path.is_file() and name in expected, 'hydration_extra_member')
            actual.add(name)
    needed = {}
    for name, digest in manifest['files'].items():
        target = candidate.checked_path(destination/'files', name)
        if 'files/' + name in actual:
            require(sha(target.read_bytes()) == digest, 'hydration_present_corruption')
        else:
            needed[name] = digest
    verified = []
    for source in sources:
        source = Path(source); value = candidate.load(source)
        verified.append((source, value))
    copies = {}
    for name, digest in needed.items():
        available = [source/'files'/name for source, value in verified if value['files'].get(name) == digest]
        require(available, 'hydration_missing_authenticated_bytes')
        raw = available[0].read_bytes()
        require(sha(raw) == digest, 'hydration_source_changed')
        copies[name] = raw
    for name, raw in copies.items():
        target = candidate.checked_path(destination/'files', name)
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    require(candidate.load(destination, manifest['candidate_id']) == manifest, 'hydration_complete_candidate')
    return tuple(sorted(copies))


def authenticate_public_parent(parent, context, repository, api):
    """The public parent is an artifact authority, not an unverified cache."""
    from tools.fetch_release_artifact import run_artifacts
    producer = context['parent_producer']
    meta = modern_run(producer['run_id'], producer['run_attempt'], api)
    require(modern_producer(meta) == producer, 'hydration_parent_producer')
    pin = context['parent_artifact']
    matches = [row for row in run_artifacts(producer['run_id'], api, repository=repository)
        if row['id'] == pin['id'] or row['name'] == pin['name']]
    require(len(matches) == 1 and {'id': matches[0]['id'], 'name': matches[0]['name'],
        'sha256': matches[0]['digest'].removeprefix('sha256:')} == pin, 'hydration_parent_artifact_pin')
    raw = modern_packet(repository, meta, matches[0], api)
    with tempfile.TemporaryDirectory(prefix='program-public-parent-') as temporary:
        authenticated = Path(temporary); auth.unpack_public(raw, authenticated)
        original = candidate.load(authenticated, context['parent_candidate_id'])
        require(sha((authenticated/'candidate.json').read_bytes()) == context['parent_manifest_sha256']
            and (authenticated/'candidate.json').read_bytes() == (Path(parent)/'candidate.json').read_bytes()
            and candidate.load(parent) == original and all((authenticated/'files'/name).read_bytes() ==
                (Path(parent)/'files'/name).read_bytes() for name in original['files']), 'hydration_exact_public_parent')


def modern_original(parent, state, repository, run, identifier, api, root):
    """Authenticate the complete native candidate and its original spend owner."""
    from tools.fetch_release_artifact import run_artifacts
    original = candidate.load(parent, identifier)
    require(not original.get('derived_from_candidate') and original['generation_run_id'] == str(run),
        'modern_native_generation_parent')
    require(all(original['files'].get(name) == digest for name, digest in original['generation_files'].items()),
        'modern_generated_file_binding')
    producer = modern_run(run, original['generation_run_attempt'], api)
    rows = run_artifacts(run, api, repository=repository)
    def one(name):
        selected = [r for r in rows if r['name'] == name]
        require(len(selected) == 1, 'modern_unique_' + name.split('-')[0])
        return selected[0]
    artifact = one('candidate-' + identifier)
    with tempfile.TemporaryDirectory(prefix='program-parent-') as temporary:
        packet = Path(temporary)
        auth.unpack_public(modern_packet(repository, producer, artifact, api), packet)
        require(candidate.load(packet, identifier) == original
            and (packet/'candidate.json').read_bytes() == (Path(parent)/'candidate.json').read_bytes(),
            'modern_exact_native_candidate')
        require(all((packet/'files'/n).read_bytes() == (Path(parent)/'files'/n).read_bytes()
            for n in original['files']), 'modern_complete_native_bytes')
        require({n.relative_to(packet).as_posix() for n in packet.rglob('*') if n.is_file()} ==
            {'candidate.json', *('files/' + n for n in original['files'])}, 'modern_native_archive_inventory')
    plans = [(int(m[1]), r) for r in rows if (m := re.fullmatch(r'release-plan-([1-9][0-9]*)', r['name']))
        and int(m[1]) <= int(original['generation_run_attempt'])]
    require(plans, 'modern_generation_plan')
    latest = max(n for n, _ in plans); selected = [r for n, r in plans if n == latest]
    require(len(selected) == 1, 'modern_unique_generation_plan')
    plan_producer = modern_run(run, latest, api)
    plan = zip_files(modern_packet(repository, plan_producer, selected[0], api)).get('release-plan.json')
    require(plan is not None and auth.json_value(plan).get('release_sha') == original['generation_sha']
        and auth.json_value(plan).get('stage') == 'generate',
        'modern_actual_generation_checkout')
    candidate.git(root, 'merge-base', '--is-ancestor', original['generation_sha'], 'HEAD')
    spending = {}
    for role in ('reservation', 'state'):
        row = one(f'generation-spend-{role}-{run}-{original["generation_run_attempt"]}')
        raw = modern_packet(repository, producer, row, api)
        spending[role] = {'artifact_id': row['id'], 'zip_sha256': sha(raw)}
        modern_unpack(raw, Path(state) if role == 'state' else Path(state)/'original-reservation')
    book = read(Path(state)/'ledger.json'); reservation = read(Path(state)/'original-reservation/spend-reservation.json')
    require(book['logical_id'] == 'offline-' + str(run) and book['limit_microusd'] == 2_000_000
        and book['max_requests'] == 300 and reservation['run_id'] == str(run)
        and reservation['attempt'] == original['generation_run_attempt'] and reservation['mode'] == 'maintenance'
        and reservation['maximum_logical_spend_usd'] == 2, 'modern_original_budget')
    spending['ledger_sha256'] = identity(book)
    return original, spending, modern_producer(producer), {
        'id': artifact['id'], 'name': artifact['name'], 'sha256': artifact['digest'].removeprefix('sha256:')}


def modern_history(parent, state, root, repository, run, identifier, api):
    """Restore the newest paired task checkpoint, never an earlier allowance."""
    from tools.fetch_release_artifact import repository_artifacts, run_artifacts
    from tools.catalog_reconcile import request_identity
    from tools.catalog_reconcile_spend import context
    family = modern_prefix(identifier)
    rows = [r for r in repository_artifacts(repository, api, task_prefix=family)
        if r['name'].startswith(family + '-')]
    reservations = [r for r in rows if re.fullmatch(re.escape(family) + r'-reservation-[1-9][0-9]*-[1-9][0-9]*', r['name'])]
    states = [r for r in rows if re.fullmatch(re.escape(family) + r'-state-[1-9][0-9]*-[1-9][0-9]*', r['name'])]
    require(len(rows) == len(reservations) + len(states) and (reservations or not states), 'modern_checkpoint_inventory')
    if not reservations:
        require(os.environ.get('GITHUB_RUN_ATTEMPT', '1') == '1', 'modern_missing_prior_attempt_state')
        return None
    latest = max(reservations, key=lambda r: r['id'])
    selected = [r for r in states if r['name'] == latest['name'].replace('-reservation-', '-state-')]
    require(len(selected) == 1, 'modern_newest_paired_checkpoint')
    selected = selected[0]; _, producer_run, attempt = latest['name'].rsplit('-', 2)
    producer = modern_run(producer_run, attempt, api)
    require(latest['workflow_run'] == selected['workflow_run'], 'modern_paired_producer')
    voucher = zip_files(modern_packet(repository, producer, latest, api))
    require(set(voucher) == {'reservation.json'}, 'modern_reservation_members')
    reservation = auth.json_value(voucher['reservation.json'])
    require(reservation.get('version') == MODERN_VERSION and reservation.get('parent_candidate_id') == identifier
        and reservation.get('producer_run') == producer_run and reservation.get('producer_attempt') == attempt,
        'modern_reservation_binding')
    modern_unpack(modern_packet(repository, producer, selected, api), state)
    value = context(state)
    require(value['version'] == MODERN_VERSION and value['parent_candidate_id'] == identifier
        and value['parent_run'] == str(run)
        and value['parent_manifest_sha256'] == sha((Path(parent)/'candidate.json').read_bytes())
        and value['operation_sha256'] == reservation['operation_sha256'], 'modern_checkpoint_context')
    authenticate_public_parent(parent, value, repository, api)
    hydrate_public_bundle(Path(state)/'parent-candidate', candidate.load(parent, identifier), [parent])
    ledger = read(Path(state)/'ledger.json')
    link = {'producer': modern_producer(producer),
        'reservation': {'id': latest['id'], 'name': latest['name'], 'sha256': latest['digest'].removeprefix('sha256:')},
        'state': {'id': selected['id'], 'name': selected['name'], 'sha256': selected['digest'].removeprefix('sha256:')},
        'ledger_sha256': identity(ledger), 'request_count': len(ledger['requests']),
        'request_prefix_sha256': identity(ledger['requests']),
        'request_identity_prefix_sha256': request_identity(ledger['requests']),
        'charged_microusd': sum(r['charged_microusd'] for r in ledger['requests'])}
    completed_public_raw = None
    if value.get('completed_candidate_id'):
        child = value['completed_candidate_id']
        complete = Path(state)/'complete-candidates'/child
        loaded = read(complete/'candidate.json')
        require(loaded.get('candidate_id') == child and loaded.get('derived_from_candidate') == identifier
            and loaded.get('program_area_revalidation', {}).get('operation_sha256') == value['operation_sha256'],
            'modern_completed_child')
        available = [r for r in run_artifacts(producer_run, api, repository=repository) if r['name'] == 'candidate-' + child]
        require(len(available) <= 1, 'modern_completed_child_ambiguity')
        if available:
            completed_public_raw = modern_packet(repository, producer, available[0], api)
            with tempfile.TemporaryDirectory(prefix='program-completed-') as temporary:
                auth.unpack_public(completed_public_raw, temporary)
                require(candidate.load(temporary, child) == loaded, 'modern_completed_child_native')
                hydrate_public_bundle(complete, loaded, [Path(temporary), parent])
            link['candidate'] = {'candidate_id': child, 'manifest_sha256': sha((complete/'candidate.json').read_bytes()),
                'producer': link['producer'], 'artifact': {'id': available[0]['id'], 'name': available[0]['name'],
                    'sha256': available[0]['digest'].removeprefix('sha256:')}}
        else:
            # Upload may have failed after private persistence. The public
            # parent can supply a missing member only when its declared hash
            # proves those exact bytes also belong to this completed child.
            hydrate_public_bundle(complete, loaded, [parent])
    lineage_path = Path(state)/'consumed-checkpoints.json'
    lineage = read(lineage_path)
    if not any(r['state']['id'] == link['state']['id'] for r in lineage):
        lineage.append(link)
    # A completed replay emits a later state without a second reservation.
    # It cannot change any private byte except this append-only transport
    # lineage, and its actual workflow trace must prove zero generation work.
    newer = sorted((r for r in states if r['id'] > selected['id']), key=lambda r: r['id'])
    require(not newer or value.get('completed_candidate_id'), 'modern_state_only_requires_completed_child')
    unchanged = {n.relative_to(state).as_posix(): sha(n.read_bytes()) for n in Path(state).rglob('*')
        if n.is_file() and n.relative_to(state).as_posix() != 'consumed-checkpoints.json'}
    for transport in newer:
        _, transport_run, transport_attempt = transport['name'].rsplit('-', 2)
        transport_meta = modern_run(transport_run, transport_attempt, api)
        require(not any(r['name'] == transport['name'].replace('-state-', '-reservation-') for r in reservations),
            'modern_state_only_new_reservation')
        with tempfile.TemporaryDirectory(prefix='program-restore-') as temporary:
            restored = Path(temporary)/'state'
            modern_unpack(modern_packet(repository, transport_meta, transport, api), restored)
            hydrate_public_bundle(restored/'parent-candidate', candidate.load(parent, identifier), [parent])
            sources = [parent]
            if completed_public_raw is not None:
                public_child = Path(temporary)/'public-child'
                auth.unpack_public(completed_public_raw, public_child); sources.insert(0, public_child)
            hydrate_public_bundle(restored/'complete-candidates'/value['completed_candidate_id'], loaded, sources)
            require({n.relative_to(restored).as_posix(): sha(n.read_bytes()) for n in restored.rglob('*')
                if n.is_file() and n.relative_to(restored).as_posix() != 'consumed-checkpoints.json'} == unchanged
                and read(restored/'consumed-checkpoints.json') == lineage, 'modern_completed_transport_bytes')
        from tools.program_area_history import completed_restore
        completed_restore(repository, transport_meta, transport_meta, api=api)
        restored_link = {**link, 'producer': modern_producer(transport_meta), 'restored': True,
            'state': {'id': transport['id'], 'name': transport['name'],
                'sha256': transport['digest'].removeprefix('sha256:')}}
        restored_link.pop('candidate', None)
        child = value['completed_candidate_id']; complete = Path(state)/'complete-candidates'/child
        candidates = [r for r in run_artifacts(transport_run, api, repository=repository)
            if r['name'] == 'candidate-' + child]
        require(len(candidates) <= 1, 'modern_transport_candidate_ambiguity')
        if candidates:
            with tempfile.TemporaryDirectory(prefix='program-transport-child-') as temporary:
                auth.unpack_public(modern_packet(repository, transport_meta, candidates[0], api), temporary)
                require(candidate.load(temporary, child) == candidate.load(complete, child),
                    'modern_transport_candidate_bytes')
            restored_link['candidate'] = {'candidate_id': child,
                'manifest_sha256': sha((complete/'candidate.json').read_bytes()), 'producer': restored_link['producer'],
                'artifact': {'id': candidates[0]['id'], 'name': candidates[0]['name'],
                    'sha256': candidates[0]['digest'].removeprefix('sha256:')}}
        lineage.append(restored_link)
    atomic_json(lineage_path, lineage)
    return value


def vector_packet(root):
    """Use the normal builder's exact ordered-corpus and whole-asset contract."""
    root = Path(root).resolve()
    script = r'''
import {readFileSync} from 'node:fs'; import {createHash} from 'node:crypto'; import vm from 'node:vm';
const root=new URL(process.argv[1]); const load=n=>readFileSync(new URL(n,root));
const sha=b=>createHash('sha256').update(b).digest('hex');
const {loadHarness,makeVariantHarness}=await import(new URL('tools/run_search_diagnosis.mjs',root));
const {configuration}=await import(new URL('tools/embedding_contract.mjs',root));
const {validateCorpusAsset}=await import(new URL('tools/run_budgeted_vectors.mjs',root));
const names=JSON.parse(process.argv[2]); const hashes=Object.fromEntries(names.map(n=>[n,sha(load(n))]));
const ctx={globalThis:{},URL,TextEncoder,Uint8Array,Uint16Array,Float32Array,ArrayBuffer};
vm.runInNewContext(load('assets/search-hybrid.js').toString(),ctx);
const base=await loadHarness(),h=makeVariantHarness(base,{searchV2:true});
const corpus=ctx.globalThis.FUNDING_HYBRID_SEARCH.buildCorpus({parentCatalog:h.parentCatalog,childCatalog:h.childCatalog,
currentnessRejectedIndexes:h.parentEngine.corpusCurrentness().currentnessRejectedIndexes});
const corpusSha=sha(corpus.map(r=>`${r.passage_id}\0${r.parent_id}\0${r.text}\n`).join(''));
const configSha=sha(JSON.stringify(configuration(hashes['assets/search-hybrid.js'])));
let eligible=false;try{eligible=validateCorpusAsset(JSON.parse(load('data/search-v2-voyage-manifest.json')),
load('data/search-v2-voyage-vectors.f16'),JSON.parse(load('data/search-v2-voyage-canaries.json')),corpus,corpusSha,configSha);}catch{}
console.log(JSON.stringify({corpus_sha256:corpusSha,configuration_sha256:configSha,passage_count:corpus.length,
source_hashes:hashes,retained_asset_eligible:eligible}));
'''
    from tools.catalog_reconcile_spend import GENERATION_INPUTS
    result = subprocess.run([shutil.which('node') or 'node', '--input-type=module', '-e', script,
        root.as_uri() + '/', json.dumps(GENERATION_INPUTS)], cwd=root, capture_output=True, timeout=120, check=False)
    require(result.returncode == 0, 'modern_vector_corpus_contract')
    return auth.json_value(result.stdout)


def modern_native_vectors(root, state, parent, original, value, packet):
    from tools import catalog_reconcile_spend as spend
    book = spend.ledger(state)
    accounting, raw = spend.parent_vector_accounting(state, parent, original, value, book, book.read())
    require(accounting['classification'] in {'budgeted', 'retained'} and raw, 'modern_managed_native_vectors')
    old = spend.context(state, generation=True)['operation_contract']; current = spend.vector_binding(packet)
    compatible = (packet['retained_asset_eligible'] is True and all(old[key] == current[key]
        for key in ('corpus_sha256', 'configuration_sha256', 'passage_count'))
        and all(old['source_hashes'].get(n) == current['source_hashes'].get(n) for n in spend.VECTOR_PREPROCESSORS))
    if compatible:
        require(hashes(root, VECTORS) == {n: sha(raw[n]) for n in VECTORS}, 'modern_retained_vector_bytes')
    return compatible, accounting


def _modern_receipt(value, original, outputs, changes, ledger, consumed):
    return {k: v for k, v in value.items() if k != 'completed_candidate_id'} | {
        'projection': changes, 'projection_hashes': {n: sha(raw) for n, raw in outputs.items()},
        'retained_hashes': {n: h for n, h in original['generation_files'].items()
            if n not in outputs and n not in VECTORS and not FACET_FEED.fullmatch(n)},
        'consumed_checkpoints': consumed, 'ledger_sha256': identity(ledger),
        'new_source_requests': 0, 'new_document_requests': 0, 'new_team_requests': 0}


def prepare_modern(parent_bundle, receipt_path, state, parent_run, parent_id, *, root=ROOT,
                   api=auth.existing.api, output=None):
    from tools import catalog_reconcile_spend as spend
    require(re.fullmatch('[1-9][0-9]*', str(parent_run)) and state is not None, 'modern_exact_run_and_state')
    modern_prefix(parent_id)
    root, parent, state = Path(root), Path(parent_bundle), Path(state)
    require(not state.exists() or not any(state.iterdir()), 'modern_fresh_local_state')
    original = candidate.load(parent, parent_id); modern_scope(root, original)
    repository = os.environ['GITHUB_REPOSITORY']
    value = modern_history(parent, state, root, repository, parent_run, parent_id, api)
    if value is None:
        original, spending, producer, artifact = modern_original(parent, state, repository, parent_run, parent_id, api, root)
        value = {'version': MODERN_VERSION, 'parent_candidate_id': parent_id, 'parent_run': str(parent_run),
            'parent_attempt': original['generation_run_attempt'], 'parent_generation_sha': original['generation_sha'],
            'parent_manifest_sha256': sha((parent/'candidate.json').read_bytes()), 'parent_producer': producer,
            'parent_artifact': artifact, 'original_spend': spending, 'operation_contract': modern_contract(root),
            'audit_at': datetime.now(timezone.utc).isoformat()}
        value['operation_sha256'] = identity(value)
        atomic_json(state/'reconciliation.json', value); atomic_json(state/'consumed-checkpoints.json', [])
        shutil.copytree(parent, state/'parent-candidate')
    else:
        require(candidate.load(state/'parent-candidate', parent_id) == original, 'modern_saved_parent')
        if value.get('completed_candidate_id'):
            complete = state/'complete-candidates'/value['completed_candidate_id']
            child = candidate.load(complete)
            try:
                candidate.verify_dependencies(root, child)
            except ValueError:
                require(value['operation_contract'].get('scripts/extract_document_evidence.py') !=
                    modern_contract(root)['scripts/extract_document_evidence.py'], 'modern_completed_use_named_runtime_resume')
                receipt = child['program_area_revalidation']
                require(receipt['affected_generation']['generation_run_id'] != os.environ['GITHUB_RUN_ID'],
                    'modern_changed_child_requires_new_dispatch')
                value = {k: v for k, v in value.items() if k not in {'completed_candidate_id', 'operation_sha256'}}
                value['operation_contract'] = modern_contract(root); value['audit_at'] = datetime.now(timezone.utc).isoformat()
                value['operation_sha256'] = identity(value); atomic_json(state/'reconciliation.json', value)
            else:
                require(output is not None, 'modern_completed_output_required')
                shutil.copytree(complete, output)
                atomic_json(receipt_path, child['program_area_revalidation'])
                native = [link['candidate'] for link in read(state/'consumed-checkpoints.json')
                    if link.get('candidate', {}).get('candidate_id') == child['candidate_id']]
                return {'modern': 'true', 'vector_state': str(state), 'parent_run': str(parent_run),
                    'candidate_id': child['candidate_id'],
                    'artifact_run': native[-1]['producer']['run_id'] if native else os.environ['GITHUB_RUN_ID'],
                    'upload_candidate': 'false' if native else 'true',
                    'state_artifact': modern_prefix(parent_id) + '-state-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']}
        if value['operation_contract'] != modern_contract(root):
            value = {k: v for k, v in value.items() if k != 'operation_sha256'}
            value['operation_contract'] = modern_contract(root)
            value['operation_sha256'] = identity(value); atomic_json(state/'reconciliation.json', value)
    spend.import_history(state, parent, value['original_spend']['ledger_sha256'])
    outputs, changes = projection(parent/'files', value['audit_at'], parent_id)
    for name in managed_feed_names(root) - set(outputs):
        require(FACET_FEED.fullmatch(name), 'modern_obsolete_feed_scope'); candidate.checked_path(root, name).unlink()
    for name in original['generation_files']:
        if FACET_FEED.fullmatch(name) and name not in outputs:
            continue
        target = candidate.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((parent/'files'/name).read_bytes())
    for name, raw in outputs.items():
        target = candidate.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    packet = vector_packet(root)
    reused, accounting = modern_native_vectors(root, state, parent, original, value, packet)
    atomic_json(state/'program-vector-inputs.json', {'packet': packet, 'vector_reused': reused, 'accounting': accounting})
    ledger = read(state/'ledger.json')
    receipt = _modern_receipt(value, original, outputs, changes, ledger, read(state/'consumed-checkpoints.json'))
    atomic_json(receipt_path, receipt)
    current = modern_run(os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'], api, current=True)
    require(os.environ['GITHUB_SHA'] == current['head_sha'], 'modern_current_event')
    reservation = {'version': MODERN_VERSION, 'parent_candidate_id': parent_id,
        'operation_sha256': value['operation_sha256'], 'producer_run': str(current['id']),
        'producer_attempt': str(current['run_attempt']), 'prior_ledger_sha256': identity(ledger)}
    atomic_json(state/'reservation.json', reservation)
    reservation_path = state.parent/(state.name + '-reservation')/'reservation.json'
    atomic_json(reservation_path, reservation)
    suffix = str(current['id']) + '-' + str(current['run_attempt'])
    return {'modern': 'true', 'vector_state': str(state), 'parent_run': str(parent_run),
        'vector_reused': str(reused).lower(), 'reservation_artifact': modern_prefix(parent_id) + '-reservation-' + suffix,
        'reservation_path': str(reservation_path), 'state_artifact': modern_prefix(parent_id) + '-state-' + suffix}


def checkpoint_modern(receipt_path, state, *, root=ROOT, write=True):
    from tools import catalog_reconcile_spend as spend
    state, root = Path(state), Path(root); value = spend.context(state)
    receipt = read(receipt_path); original = candidate.load(state/'parent-candidate', value['parent_candidate_id'])
    require(receipt['operation_sha256'] == value['operation_sha256']
        and value['operation_contract'] == modern_contract(root), 'modern_checkpoint_operation')
    packet = vector_packet(root); inputs = read(state/'program-vector-inputs.json')
    require(spend.vector_binding(packet) == spend.vector_binding(inputs['packet']) and packet['retained_asset_eligible'],
        'modern_complete_current_corpus')
    if inputs['vector_reused']:
        reused, accounting = modern_native_vectors(root, state, state/'parent-candidate', original, value, packet)
        require(reused and accounting == inputs['accounting'], 'modern_retained_origin')
        proof = {'classification': 'retained_native_asset', 'accounting': accounting, 'new_requests': 0}
    else:
        binding = spend.vector_binding(packet)
        completed = spend.completed_outputs(state, value, binding, root)
        require(completed is not None and completed['status'] == 'complete', 'modern_sealed_completed_vectors')
        proof = {'classification': 'budgeted', 'accounting_origin': completed['accounting_origin'],
            'completion_sha256': sha((state/'vector-completions'/(value['operation_sha256']+'.json')).read_bytes())}
    ledger = spend.ledger(state).read()
    from tools.catalog_reconcile import request_identity
    for link in receipt['consumed_checkpoints']:
        count = link['request_count']
        require(count <= len(ledger['requests']) and request_identity(ledger['requests'][:count]) ==
            link['request_identity_prefix_sha256'] and sum(r['charged_microusd'] for r in
                ledger['requests'][:count]) <= link['charged_microusd'], 'modern_consumed_ledger_prefix')
    receipt.update(ledger_sha256=identity(ledger), vector_outputs=hashes(root, VECTORS), vector_accounting=proof)
    if write:
        atomic_json(receipt_path, receipt)
    return receipt


def verify_modern_inputs(root, original, receipt_path, *, api=auth.existing.api):
    state = Path(os.environ.get('PROGRAM_AREA_VECTOR_STATE', ''))
    require(os.environ.get('PROGRAM_AREA_VECTOR_STATE'), 'modern_constructor_private_state')
    from tools.catalog_reconcile_spend import context, import_history
    value = context(state); parent = state/'parent-candidate'
    require(candidate.load(parent, value['parent_candidate_id']) == original
        and value['version'] == MODERN_VERSION and value['parent_manifest_sha256'] == sha((parent/'candidate.json').read_bytes()),
        'modern_constructor_original')
    modern_scope(root, original)
    import_history(state, parent, value['original_spend']['ledger_sha256'])
    saved = read(receipt_path)
    require(checkpoint_modern(receipt_path, state, root=root, write=False) == saved,
        'modern_constructor_receipt_sealed')
    outputs, changes = projection(parent/'files', value['audit_at'], value['parent_candidate_id'])
    base = _modern_receipt(value, original, outputs, changes, read(state/'ledger.json'), read(state/'consumed-checkpoints.json'))
    require(all(saved.get(k) == v for k, v in base.items()), 'modern_deterministic_projection_receipt')
    require(hashes(root, outputs) == saved['projection_hashes']
        and hashes(root, saved['retained_hashes']) == saved['retained_hashes'], 'modern_constructor_exact_outputs')
    return saved['retained_hashes']


def record_modern_candidate(state, bundle):
    from tools.catalog_reconcile_spend import context
    state = Path(state); value = context(state); child = candidate.load(bundle)
    require(child.get('derived_from_candidate') == value['parent_candidate_id']
        and child.get('program_area_revalidation', {}).get('operation_sha256') == value['operation_sha256'],
        'modern_record_completed_candidate')
    complete = state/'complete-candidates'/child['candidate_id']
    if complete.exists():
        require(candidate.load(complete) == child, 'modern_immutable_completed_candidate')
    else:
        shutil.copytree(bundle, complete)
    value['completed_candidate_id'] = child['candidate_id']; atomic_json(state/'reconciliation.json', value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'vectors-restore', 'vectors-reserve', 'vectors-checkpoint'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--parent-bundle', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--reservation', type=Path)
    parser.add_argument('--parent-run')
    parser.add_argument('--parent-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); outputs = {'receipt_path': str(args.receipt)}
    if args.action == 'prepare':
        require(args.parent_bundle is not None, 'parent_bundle_required')
        if args.parent_id and args.parent_id != PARENT_CANDIDATE:
            outputs.update(prepare_modern(args.parent_bundle, args.receipt, args.state,
                args.parent_run, args.parent_id, root=args.root, output=args.output))
        else:
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
        if read(args.receipt).get('version') == MODERN_VERSION:
            checkpoint_modern(args.receipt, args.state, root=args.root)
        else:
            value = checkpoint_vectors(args.receipt, args.state, root=args.root)
            outputs.update(artifact_name=artifact_name('state', value['owner']), artifact_path=str(args.state))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in outputs.items():
                stream.write(f'{key}={value}\n')
    print(json.dumps(outputs, sort_keys=True))


if __name__ == '__main__':
    main()
