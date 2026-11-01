"""Recover two reviewed primary notices without repeating catalog generation.

The protected input packet names exact official PDF bytes. Only those documents
are acquired, with completed acquisition and safe extraction checkpoints kept in
the original release state. Public candidates contain ordinary cited projections,
never the PDF bytes or unrestricted extracted text.
"""
from copy import deepcopy
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts import extract_document_evidence as evidence
from scripts.enrich_catalog import read_catalog, select_primary_document
from tools.offline_spend import atomic_json, identity
from tools import program_area_revalidation as common

ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = ROOT / 'config/primary_document_recovery.json'
VERSION = 'primary-document-recovery-1'
ENRICHMENT = 'data/opportunity_enrichment.json'
RECIPE_FILES = ('tools/primary_document_revalidation.py', 'scripts/extract_document_evidence.py',
    'scripts/source_documents.py', 'scripts/enrich_catalog.py', 'scripts/pull_grants.py',
    'scripts/subtopic_sources.py', 'scripts/notice_semantics.py', 'scripts/notice_fact_guards.py')
PRIMARY_KEYS = {'primary_document_' + key for key in ('url', 'name', 'source', 'confidence')}
DERIVED_KEYS = {'document_evidence', 'document_evidence_status', 'document_evidence_checked_at',
    'document_evidence_processing_reason', 'document_program_areas', 'document_search_text',
    'document_status_signals', 'deadlines', 'submission_requirements', 'has_preliminary_stage',
    'preliminary_stage_type', 'limited_submission', 'limited_submission_review',
    'status_verification_required', 'actionability_status', 'topic_areas', 'next_submission'}


def require(ok, reason):
    if not ok:
        raise ValueError('primary_document_revalidation_' + reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def unchanged(before, after, allowed):
    return {k: v for k, v in before.items() if k not in allowed} == {
        k: v for k, v in after.items() if k not in allowed}


def selected_primary(row, old_entry, old_enrichment, spec):
    from scripts.source_documents import is_doe_companion_document
    old = spec['previous_primary']
    require(row['opportunity_number'] == spec['opportunity_number']
        and row.get('source') == 'Grants.gov', 'record_identity')
    require(row.get('primary_document_url') == old['url']
        and row.get('primary_document_name') == old['name']
        and old_entry.get('document', {}).get('sha256') == old['sha256']
        and old_enrichment.get('primary_document', {}).get('url') == old['url']
        and is_doe_companion_document(old_entry['document']), 'original_companion_identity')
    chosen = select_primary_document(spec['attachments'])
    expected = spec['selected_document']
    require(chosen and chosen['url'] == expected['url'] and chosen['name'] == expected['name']
        and not is_doe_companion_document(chosen), 'reviewed_primary_selection')
    attachments = [a for a in spec['attachments'] if a.get('id') == expected['attachment_id']]
    require(len(attachments) == 1 and attachments[0]['download_url'] == expected['url']
        and attachments[0]['file_name'] == expected['name'], 'owned_attachment')
    require(re.fullmatch(r'https://grants.gov/grantsws/rest/opportunity/att/download/[1-9][0-9]*',
        expected['url']) and expected['url'].endswith('/' + str(expected['attachment_id']))
        and re.fullmatch('[a-f0-9]{64}', expected['sha256'])
        and type(expected['bytes']) is int and 0 < expected['bytes'] <= 8 * 1024 * 1024,
        'bounded_official_input')
    return chosen


def response_identity(response, expected):
    raw = response['content']
    require(raw.startswith(b'%PDF') and len(raw) == expected['bytes']
        and digest(raw) == expected['sha256'], 'exact_pdf_bytes')
    parsed = urlparse(response['url'])
    require(parsed.scheme == 'https' and not parsed.username and not parsed.password
        and (parsed.hostname == 'grants.gov' or re.fullmatch(r'apply[0-9]+\.grants\.gov', parsed.hostname or ''))
        and parsed.path == '/grantsws/rest/opportunity/att/download/' + str(expected['attachment_id'])
        and not parsed.query and not parsed.fragment, 'official_pdf_route')


def acquire_pdf(directory, expected, *, acquire):
    """Reuse completed public bytes even if parsing or a later step failed."""
    directory.mkdir(parents=True, exist_ok=True)
    meta_path = directory / 'acquisition.json'
    pin = identity(expected)
    if meta_path.exists():
        saved = read(meta_path)
        require(saved.get('input_sha256') == pin and saved.get('document_requests') == 1
            and len(saved.get('content_base64', '')) <= (expected['bytes'] + 2) // 3 * 4,
            'acquisition_checkpoint')
        common.timestamp(saved['source_checked_at'])
        response = saved['response'] | {'content': base64.b64decode(saved['content_base64'], validate=True),
            'source_checked_at': saved['source_checked_at']}
        response_identity(response, expected)
        return response
    require(acquire, 'acquisition_not_permitted')
    attempts_path = directory / 'attempts.json'
    attempts = read(attempts_path) if attempts_path.exists() else {'input_sha256': pin, 'count': 0}
    require(attempts.get('input_sha256') == pin and type(attempts.get('count')) is int
        and 0 <= attempts['count'] < 3, 'bounded_acquisition_attempts')
    attempts['count'] += 1
    atomic_json(attempts_path, attempts)
    try:
        response = evidence.download_document(expected['url'], timeout=45,
            maximum_bytes=expected['bytes'], headers={
                'Accept': 'application/pdf, application/octet-stream;q=0.9, */*;q=0.8'})
    except Exception as error:
        # Bounded diagnostics contain neither response bodies nor credentials.
        atomic_json(attempts_path, attempts | {'last_error_type': type(error).__name__})
        raise
    require(response.get('status_code') == 200, 'complete_pdf_response')
    response_identity(response, expected)
    response['source_checked_at'] = datetime.now(timezone.utc).isoformat()
    # The existing HTTP client verifies every public redirect and time/size bound.
    # Cache its actual route/headers, not a reconstructed claim about retrieval.
    metadata = {k: response.get(k) for k in ('status_code', 'url', 'content_type', 'etag', 'last_modified')}
    # Bytes and retrieval metadata are one atomic private checkpoint. A crash
    # cannot leave a completed PDF without the route needed to authenticate it.
    atomic_json(meta_path, {'input_sha256': pin, 'document_requests': 1, 'response': metadata,
        'source_checked_at': response['source_checked_at'],
        'content_base64': base64.b64encode(response['content']).decode('ascii')})
    return response


def safe_entry(row, previous, spec, directory, binding, audit_at, *, acquire, acquisition_directory=None):
    path = directory / 'entry.json'
    entry_binding = identity({'operation': binding, 'record': row, 'previous': previous, 'input': spec})
    if path.exists():
        saved = read(path)
        require(saved.get('binding') == entry_binding and saved.get('sha256') == identity(saved.get('entry')),
            'safe_entry_checkpoint')
        return saved['entry']
    require(acquire, 'extraction_not_permitted')
    response = acquire_pdf(acquisition_directory or directory, spec['selected_document'], acquire=acquire)
    entry, _ = evidence.build_document_entry(row, evidence.source_for_record(row), response,
        deepcopy(previous), common.timestamp(audit_at), enable_subtopics=False, structure_cache=None)
    # A corrected recipe can reinterpret the same retrieved bytes. Its new
    # interpretation clock must not claim another upstream retrieval.
    entry['checked_at'] = response['source_checked_at']
    entry['document']['first_seen_at'] = response['source_checked_at']
    entry['document']['last_seen_at'] = response['source_checked_at']
    require(entry.get('status') == 'current' and entry['document']['sha256'] == spec['selected_document']['sha256'],
        'current_pinned_entry')
    # Both reviewed parents already completed segmentation of this same Part 1
    # with no accepted child topics. Preserve that decision; do not queue AI work.
    require(previous.get('subtopics') == [] and any(
        attempt.get('source') == spec['selected_document']['name']
        and attempt.get('outcome') == 'no_layer_accepted' and attempt.get('subtopics') == 0
        for attempt in previous.get('subtopic_attempts', [])), 'retained_empty_subtopic_decision')
    for key, value in previous.items():
        if key == 'subtopics' or key.startswith('subtopic_'):
            entry[key] = deepcopy(value)
    atomic_json(path, {'binding': entry_binding, 'sha256': identity(entry), 'entry': entry})
    return entry


def project_catalog(before, cache, enrichment, packet, entries, audit_at):
    from scripts.build_catalog import build_search_index, facet_counts
    from scripts.submission_schedule import project
    after, updated, details = deepcopy(before), deepcopy(cache), deepcopy(enrichment)
    targets = packet['records']
    require(set(entries) == set(targets) and len(targets) == 2, 'complete_bounded_entries')
    found = set()
    for index, old in enumerate(before['opportunities']):
        identifier = str(old['opportunity_id'])
        if identifier not in targets:
            continue
        found.add(identifier)
        chosen = selected_primary(old, cache['records'][identifier], enrichment['records'][identifier], targets[identifier])
        row = deepcopy(old)
        row.update({'primary_document_' + key: value for key, value in chosen.items()})
        entry = deepcopy(entries[identifier])
        row = evidence.merge_document_entry(row, entry)
        # Keep the existing catalog's evaluation day, not the recovery wall clock.
        as_of = (old.get('next_submission') or {}).get('as_of', before['generated_at'][:10])
        row = project(row, as_of)
        require(unchanged(old, row, PRIMARY_KEYS | DERIVED_KEYS), 'source_scalar_firewall')
        # Strip the projections with the production ownership logic to prove the
        # authoritative source values survive new deadlines, topics and flags.
        old_source = evidence.merge_document_entry(old, None)
        new_source = evidence.merge_document_entry(row, None)
        require(unchanged(old_source, new_source, PRIMARY_KEYS | {'next_submission'}), 'source_owned_fields')
        require(entry['document']['sha256'] == targets[identifier]['selected_document']['sha256']
            and row['document_evidence']['document']['sha256'] == entry['document']['sha256'], 'public_document_identity')
        after['opportunities'][index] = row
        updated['records'][identifier] = entry
        details['records'][identifier]['primary_document'] = chosen
        require(unchanged(enrichment['records'][identifier], details['records'][identifier], {'primary_document'}),
            'enrichment_source_clock_and_values')
    require(found == set(targets), 'target_membership')
    require(unchanged(before, after, {'opportunities'}), 'catalog_source_clocks')
    require(unchanged(cache, updated, {'records'}) and unchanged(enrichment, details, {'records'}),
        'cache_source_clocks')
    require(set(cache['records']) == set(updated['records']) and set(enrichment['records']) == set(details['records']),
        'cache_membership')
    for identifier, entry in cache['records'].items():
        if identifier not in targets:
            require(entry == updated['records'][identifier], 'unaffected_document')
    for identifier, entry in enrichment['records'].items():
        if identifier not in targets:
            require(entry == details['records'][identifier], 'unaffected_enrichment')
    after['search_index'] = build_search_index(after['opportunities'])
    after['facets'] = facet_counts(after['opportunities'])
    after['catalog_audit_generated_at'] = audit_at
    return after, updated, details


def projection(parent_root, audit_at, candidate_id, *, checkpoint_directory=None, acquire=False):
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.subtopic_records import read_cache
    from tools.verify_notice_publication import verify
    parent_root = Path(parent_root)
    require(checkpoint_directory is not None, 'checkpoint_required')
    checkpoint = Path(checkpoint_directory)
    packet = read(PACKET_PATH)
    require(packet.get('version') == VERSION and packet['parent_candidate_id'] == candidate_id
        and digest((parent_root.parent / 'candidate.json').read_bytes()) == packet['parent_manifest_sha256'],
        'reviewed_parent')
    manifest = read(parent_root.parent / 'candidate.json')
    require(manifest['generation_run_id'] == packet['parent_run']
        and manifest['generation_sha'] == packet['parent_generation_sha'], 'original_generation')
    before = read_catalog(parent_root / common.PROJECTION[0])
    cache = read(parent_root / common.PROJECTION[2]); enrichment = read(parent_root / ENRICHMENT)
    require(common.timestamp(audit_at) >= common.timestamp(before['document_evidence_generated_at']), 'truthful_audit_clock')
    recipe = {name: digest((ROOT / name).read_bytes()) for name in RECIPE_FILES}
    binding = identity({'version': VERSION, 'packet': packet, 'recipe': recipe, 'audit_at': audit_at})
    # A changed reviewed recipe may reinterpret these same pinned bytes. Keep
    # all prior safe results and acquisitions; only reuse an exact recipe seal.
    variant = checkpoint / 'recipes' / binding
    variant.mkdir(parents=True, exist_ok=True)
    seal_path = variant / 'projection.json'
    if seal_path.exists():
        sealed = read(seal_path)
        require(sealed.get('binding') == binding and sealed.get('sha256') == identity({
            k: v for k, v in sealed.items() if k != 'sha256'}), 'projection_checkpoint_binding')
        common.projection_names({'projection_kind': 'primary_document', 'projection_hashes': sealed['files']})
        require(ENRICHMENT in sealed['files'], 'complete_enrichment_projection')
        outputs = {name: (variant / 'files' / name).read_bytes() for name in sealed['files']}
        require(all(digest(raw) == sealed['files'][name] for name, raw in outputs.items()), 'projection_checkpoint_hashes')
        return outputs, sealed['changes']
    require(acquire, 'unsealed_projection')
    rows = {str(row['opportunity_id']): row for row in before['opportunities']}
    entries = {}
    for identifier, spec in sorted(packet['records'].items()):
        old = rows[identifier]
        selected = selected_primary(old, cache['records'][identifier], enrichment['records'][identifier], spec)
        row = deepcopy(old); row.update({'primary_document_' + key: value for key, value in selected.items()})
        entries[identifier] = safe_entry(row, cache['records'][identifier], spec,
            variant / 'entries' / identifier, binding, audit_at, acquire=acquire,
            acquisition_directory=checkpoint / 'documents' / identifier / spec['selected_document']['sha256'])
    after, updated, details = project_catalog(before, cache, enrichment, packet, entries, audit_at)
    gate = verify(after, updated, read_cache(parent_root / 'data/subtopics.js'), candidate_id=candidate_id)
    atomic_json(variant / 'notice-projection-report.json', gate)
    require(gate['publication_ready'], 'notice_projection_gate')
    outputs = {common.PROJECTION[0]: catalog_javascript_bytes(after),
        common.PROJECTION[1]: catalog_metadata_javascript_bytes(after),
        common.PROJECTION[2]: json_bytes(updated), ENRICHMENT: json_bytes(details)}
    changes_path = parent_root / 'feeds/changes.xml'
    outputs.update(common.feed_projection(after, changes_path.read_bytes() if changes_path.is_file() else None))
    common.verify_feed_index(outputs, outputs, changes_present=changes_path.is_file())
    changes = {'projection_kind': 'primary_document', 'affected_catalog_ids': sorted(entries),
        'affected_evidence_ids': sorted(entries), 'original_source_at': before['generated_at'],
        'original_evidence_at': before['document_evidence_generated_at'],
        'input_packet_sha256': identity(packet), 'document_requests': len(entries),
        'document_acquisition_attempts': sum(read(checkpoint / 'documents' / identifier /
            spec['selected_document']['sha256'] / 'attempts.json')['count']
            for identifier, spec in packet['records'].items()),
        'document_request_accounting': 'Completed authenticated inputs; attempted acquisitions reported separately',
        'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0,
        'documents': {identifier: {'sha256': entry['document']['sha256'], 'url': entry['document']['url'],
            'checked_at': entry['checked_at']} for identifier, entry in entries.items()}}
    for name, raw in outputs.items():
        target = variant / 'files' / name
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    sealed = {'binding': binding, 'files': {n: digest(raw) for n, raw in outputs.items()}, 'changes': changes}
    atomic_json(seal_path, sealed | {'sha256': identity(sealed)})
    return outputs, changes
