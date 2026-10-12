"""Pinned NYSERDA navigation metadata repair; historical acquisitions stay exact."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import re
import tempfile

from tools import release_candidate as c
from tools.catalog_identity_projection import value_hash

POLICY = 'evaluation/catalog_url_correction_20261012.json'
PARENT_ID = '051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4'
MANIFEST_SHA = 'f11c8bed90de162868348b262d6b200e2f36bb13c2601b73fbb423c5de4162c1'
PAYLOADS = ('data/opportunities.js', 'data/source_records.json', 'feeds/changes.json')
PRESERVED = ('data/document_evidence.json', 'data/link_health.json')
INVALIDATED_FIELDS = ('document_evidence', 'document_evidence_checked_at', 'document_evidence_status',
                      'document_status_signals', 'submission_requirements')
EVIDENCE_COUNTS = ('document_current_count', 'document_pending_count', 'document_failed_count',
                   'citation_fact_count', 'document_deadline_count', 'limited_submission_review_count',
                   'review_queue_count', 'changed_document_count')
BROKEN = re.compile(r'https://portal\.nyserda\.ny\.gov/CORE_Solicitation_Detail_Page\? SolicitationId=[A-Za-z0-9]{18}')


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_url_projection_' + reason)


def fixed_policy(evidence):
    require(evidence.get('schema_version') == 1 and evidence.get('kind') == 'url'
            and evidence.get('candidate_id') == PARENT_ID
            and evidence.get('candidate_manifest_sha256') == MANIFEST_SHA
            and set(evidence.get('payloads', {})) == set(PAYLOADS)
            and set(evidence.get('preserved_input_hashes', {})) == set(PRESERVED), 'fixed_policy')
    invalidations = evidence.get('evidence_invalidations')
    require(isinstance(invalidations, dict) and all(
        identifier.startswith('nyserda:') and item.get('changed_fields') == list(INVALIDATED_FIELDS)
        and all(re.fullmatch(r'[0-9a-f]{64}', item.get(key, '')) for key in ('before_sha256', 'after_sha256'))
        for identifier, item in invalidations.items()), 'fixed_evidence_invalidations')
    diagnostics = evidence.get('evidence_diagnostics')
    require(isinstance(diagnostics, dict) and set(diagnostics) == {'before', 'after'}
            and all(isinstance(values, dict) and set(values) == set(EVIDENCE_COUNTS)
                    and all(type(value) is int and value >= 0 for value in values.values())
                    for values in diagnostics.values()), 'fixed_evidence_diagnostics')
    replacements = evidence['url_replacements']
    require(bool(replacements) and all(BROKEN.fullmatch(old)
            and new == old.replace('? ', '?', 1) for old, new in replacements.items()), 'exact_url_normalization')


def policy():
    evidence = c.read_json(c.ROOT / POLICY)
    fixed_policy(evidence)
    return evidence


def record_projection(record, replacements):
    """Only navigation and citation URL leaves; no description or acquisition rewrite."""
    after = deepcopy(record)
    count = 0
    def update(value, key):
        nonlocal count
        if isinstance(value, dict) and isinstance(value.get(key), str) and value[key] in replacements:
            value[key] = replacements[value[key]]
            count += 1
    for key in ('detail_page', 'funding_opportunity_url'):
        update(after, key)
    for collection in ('deadlines', 'contacts'):
        for item in after.get(collection) or []:
            update(item, 'source_url')
    update((after.get('next_submission') or {}).get('event'), 'source_url')
    return after, count


def payload_projection(name, before, replacements):
    after = deepcopy(before)
    proof = {}
    if name == PAYLOADS[0]:
        rows = after['opportunities']
        originals = before['opportunities']
        identities = [str(row['opportunity_id']) for row in originals]
    elif name == PAYLOADS[1]:
        rows = after['sources']['nyserda']['records']
        originals = before['sources']['nyserda']['records']
        identities = [str(row['opportunity_id']) for row in originals]
    elif name == PAYLOADS[2]:
        rows = after['events']
        originals = before['events']
        identities = [str(row['id']) for row in originals]
    else:
        require(False, 'payload_name')
    require(len(set(identities)) == len(identities), 'unique_payload_membership')
    for index, original in enumerate(originals):
        record = original['record'] if name == PAYLOADS[2] else original
        updated, count = record_projection(record, replacements)
        if not count:
            continue
        require(str(record.get('opportunity_id') or original.get('opportunity_id')).startswith('nyserda:'), 'nyserda_scope')
        if name == PAYLOADS[2]:
            rows[index]['record'] = updated
        else:
            rows[index] = updated
        proof[identities[index]] = {'before_sha256': value_hash(original), 'after_sha256': value_hash(rows[index]),
                                    'url_leaf_count': count}
    return after, proof


def invalidate_public_evidence(record, entry, pin, replacements):
    """Project a changed source without relabeling its historical acquisition."""
    from scripts.extract_document_evidence import merge_document_entry, source_for_record
    from scripts.submission_schedule import project
    require(value_hash(record) == pin['before_sha256'], 'exact_evidence_record')
    source = source_for_record(record)
    prior_url = (entry or {}).get('source_url')
    require(source and prior_url in replacements and replacements[prior_url] == source['url']
            and entry.get('status') == 'current' and not entry.get('facts')
            and not entry.get('program_areas') and not entry.get('subtopics'), 'changed_empty_acquisition')
    require(record.get('document_evidence_status') == 'current'
            and isinstance(record.get('document_evidence'), dict)
            and not record['document_evidence'].get('facts')
            and not record.get('document_search_text') and not record.get('document_program_areas')
            and record.get('submission_requirements') == [] and record.get('document_status_signals') == []
            and record.get('document_evidence_checked_at'), 'empty_public_evidence')
    changed_entry = deepcopy(entry)
    changed_entry['status'] = 'source_changed'
    after = project(merge_document_entry(record, changed_entry), date.fromisoformat(record['next_submission']['as_of']))
    expected = deepcopy(record)
    expected['document_evidence_status'] = 'source_changed'
    expected['document_evidence'] = None
    for key in ('document_evidence_checked_at', 'document_status_signals', 'submission_requirements'):
        expected.pop(key)
    require(after == expected and pin['changed_fields'] == list(INVALIDATED_FIELDS)
            and value_hash(after) == pin['after_sha256'], 'exact_evidence_invalidation')
    return after


def corrected_payload(name, before, evidence, *, cache=None):
    fixed_policy(evidence)
    item = evidence['payloads'][name]
    require(value_hash(before) == item['before_sha256'], 'exact_payload')
    after, proof = payload_projection(name, before, evidence['url_replacements'])
    if name == PAYLOADS[0]:
        pending = set(evidence['evidence_invalidations'])
        for index, record in enumerate(after['opportunities']):
            identifier = str(record['opportunity_id'])
            if identifier not in pending:
                continue
            require(identifier in proof, 'invalidation_requires_url_change')
            record = invalidate_public_evidence(record, ((cache or {}).get('records') or {}).get(identifier),
                evidence['evidence_invalidations'][identifier], evidence['url_replacements'])
            after['opportunities'][index] = record
            proof[identifier]['after_sha256'] = value_hash(record)
            pending.remove(identifier)
        require(not pending, 'complete_evidence_invalidations')
        # These eight values describe the public records, unlike acquisition,
        # retry and parser metrics, which attest the retained original run.
        from scripts.extract_document_evidence import document_metrics
        counts = lambda rows: {key: value for key, value in document_metrics(rows, {}, 0, 0, []).items()
                               if key in EVIDENCE_COUNTS}
        prior_counts, current_counts = counts(before['opportunities']), counts(after['opportunities'])
        diagnostics = before['diagnostics']['document_evidence']
        pinned = evidence['evidence_diagnostics']
        require(prior_counts == pinned['before']
                and {key: diagnostics.get(key) for key in EVIDENCE_COUNTS} == prior_counts
                and current_counts == pinned['after'], 'exact_evidence_diagnostics')
        require({key for key in EVIDENCE_COUNTS if prior_counts[key] != current_counts[key]}
                <= {'document_current_count', 'review_queue_count'}, 'bounded_evidence_diagnostic_changes')
        for key in EVIDENCE_COUNTS:
            if prior_counts[key] != current_counts[key]:
                after['diagnostics']['document_evidence'][key] = current_counts[key]
    require(value_hash(after) == item['after_sha256'] and proof == item['affected_items'], 'exact_url_only_projection')
    return after, proof


def projection(parent_root, audit_at):
    from scripts.sources.merge import load_catalog
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.build_feeds import build_feeds
    from scripts.build_changes import build_atom
    parent = Path(parent_root)
    evidence = policy()
    manifest = parent.parent / 'candidate.json'
    require(c.digest(manifest.read_bytes()) == MANIFEST_SHA
            and c.read_json(manifest)['candidate_id'] == PARENT_ID, 'exact_parent')
    inputs = evidence['input_hashes'] | evidence['preserved_input_hashes']
    require(set(evidence['input_hashes']) == set(PAYLOADS)
            and all(c.digest(c.checked_path(parent, name).read_bytes()) == expected
                    for name, expected in inputs.items()), 'exact_inputs')
    before = load_catalog(parent / PAYLOADS[0])
    audit = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    original = datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00'))
    require(audit.tzinfo is not None and original.tzinfo is not None and audit >= original, 'audit_clock')
    require(before['generated_at'] == evidence['original_generated_at']
            and len(before['opportunities']) == evidence['record_count'], 'original_frame')
    corrected, proofs = {}, {}
    cache = c.read_json(parent / 'data/document_evidence.json')
    for name in PAYLOADS:
        value = before if name == PAYLOADS[0] else c.read_json(parent / name)
        corrected[name], proofs[name] = corrected_payload(name, value, evidence, cache=cache)
    catalog = corrected[PAYLOADS[0]]
    changes = corrected[PAYLOADS[2]]
    outputs = {PAYLOADS[0]: catalog_javascript_bytes(catalog),
               'data/catalog-metadata.js': catalog_metadata_javascript_bytes(catalog),
               PAYLOADS[1]: (json.dumps(corrected[PAYLOADS[1]], ensure_ascii=False, indent=2) + '\n').encode(),
               PAYLOADS[2]: (json.dumps(changes, ensure_ascii=False, indent=2) + '\n').encode(),
               'feeds/changes.xml': build_atom(changes['events'], datetime.fromisoformat(changes['generated_at'].replace('Z', '+00:00'))).encode()}
    with tempfile.TemporaryDirectory(prefix='catalog-url-feeds-') as temporary:
        target = Path(temporary); feeds = target / 'feeds'; feeds.mkdir()
        (feeds / 'changes.xml').write_bytes(outputs['feeds/changes.xml'])
        build_feeds(catalog, feeds)
        outputs.update({path.relative_to(target).as_posix(): path.read_text(encoding='utf8').encode()
                        for path in feeds.rglob('*') if path.is_file()})
    return outputs, {'kind': 'url', 'policy_sha256': c.digest((c.ROOT / POLICY).read_bytes()),
                     'parent_candidate_id': PARENT_ID, 'parent_manifest_sha256': MANIFEST_SHA,
                     'original_generated_at': before['generated_at'], 'audited_at': audit_at,
                     'payloads': proofs, 'retained_record_count': len(catalog['opportunities']),
                     'preserved_acquisition_hashes': evidence['preserved_input_hashes'],
                     'evidence_invalidations': evidence['evidence_invalidations'],
                     'evidence_diagnostics': evidence['evidence_diagnostics'],
                     'output_hashes': {name: c.digest(raw) for name, raw in sorted(outputs.items())},
                     'source_requests': 0, 'provider_requests': 0}
