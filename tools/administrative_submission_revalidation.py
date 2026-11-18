"""Project explicit administrative close qualifications from retained public facts.

This never reparses, retrieves or changes the document cache. The ordinary
extractor's bounded record refinement and shared submission selector own the
interpretation; this module limits the outputs that a continuation may change.
"""
from copy import deepcopy
import json
from pathlib import Path

from tools import program_area_revalidation as common

RECORD_FIELDS = frozenset({'deadlines', 'close_date_kind', 'document_evidence',
    'document_search_text', 'next_submission'})
QUALIFICATION_FIELDS = frozenset({'label', 'kind', 'deadline_kind', 'stage',
    'date_qualifier', 'date_qualifier_citation'})
CYCLE_FIELDS = frozenset({'cycle', 'cycle_citation', 'field_authority', 'parser_version',
    'stage', 'application_class', 'track', 'invitation_required', 'prerequisite', 'obligation'})


def require(ok, reason):
    if not ok:
        raise ValueError('administrative_submission_revalidation_' + reason)


def unchanged_fields(before, after, allowed):
    return {k: v for k, v in before.items() if k not in allowed} == {
        k: v for k, v in after.items() if k not in allowed}


def qualified_items(before, after, *, facts=False):
    require(isinstance(before, list) and isinstance(after, list) and len(before) == len(after),
        'retained_fact_membership')
    for old, new in zip(before, after, strict=True):
        require(isinstance(old, dict) and isinstance(new, dict), 'fact_shape')
        if facts and old.get('type') != 'deadline':
            require(old == new, 'unchanged_non_deadline_document_fact')
            continue
        require(unchanged_fields(old, new, QUALIFICATION_FIELDS | {'document_source_fields'}),
            'retained_fact_values_and_citations')
        # A refinement can add reversible field receipts, never rewrite an
        # existing source-value receipt or the facts to which it points.
        prior = old.get('document_source_fields', {})
        retained = new.get('document_source_fields', {})
        require(isinstance(prior, dict) and isinstance(retained, dict)
            and all(retained.get(k) == v for k, v in prior.items()), 'retained_source_fields')
        for key in set(retained) - set(prior):
            require(key in QUALIFICATION_FIELDS and retained[key] == {
                'present': key in old, 'value': old.get(key)}, 'reversible_source_fields')


def record_firewall(before, after):
    from scripts.extract_document_evidence import refine_application_cycles

    require(unchanged_fields(before, after, RECORD_FIELDS), 'unchanged_non_deadline_facts')
    cycle_baseline = deepcopy(before)
    if refine_application_cycles(cycle_baseline):
        old_document = before.get('document_evidence') or {}
        cycle_document = cycle_baseline.get('document_evidence') or {}
        require(unchanged_fields(old_document, cycle_document, {'facts'}),
            'retained_cycle_document_identity_and_clock')
        old_facts = old_document.get('facts', [])
        cycle_facts = cycle_document.get('facts', [])
        require([fact for fact in old_facts if fact.get('type') != 'deadline'] ==
            [fact for fact in cycle_facts if fact.get('type') != 'deadline'],
            'retained_non_deadline_cycle_facts')
        by_id = {fact.get('id'): fact for fact in cycle_facts}
        require(len(by_id) == len(cycle_facts), 'unique_cycle_fact_ids')
        citation_fields = {'structural_reference'}
        retained_citations = [{k: v for k, v in fact.get('citation', {}).items() if k not in citation_fields}
            for fact in old_facts if fact.get('type') == 'deadline']
        for fact in old_facts:
            if fact.get('type') != 'deadline':
                continue
            retained = by_id.get(fact.get('id'), {})
            require(unchanged_fields(fact, retained, CYCLE_FIELDS | {'citation'}),
                'retained_cycle_fact_values')
            require(unchanged_fields(fact.get('citation', {}), retained.get('citation', {}), citation_fields),
                'retained_cycle_fact_citation')
        old_ids = {fact.get('id') for fact in old_facts}
        require(all(fact.get('type') == 'deadline' and
            {k: v for k, v in fact.get('citation', {}).items() if k not in citation_fields} in retained_citations
            for fact in cycle_facts if fact.get('id') not in old_ids), 'owned_cited_cycle_additions')
        before = cycle_baseline
    qualified_items(before.get('deadlines', []), after.get('deadlines', []))
    old, new = before.get('document_evidence') or {}, after.get('document_evidence') or {}
    require(unchanged_fields(old, new, {'facts'}), 'retained_document_identity_and_clock')
    qualified_items(old.get('facts', []), new.get('facts', []), facts=True)
    if before.get('document_search_text') != after.get('document_search_text'):
        from scripts.extract_document_evidence import clean_text
        def text(record):
            values = [value for fact in (record.get('document_evidence') or {}).get('facts', [])
                for value in (fact.get('label'), fact.get('display_value'),
                    (fact.get('citation') or {}).get('quote'))]
            values.extend(record.get('document_program_areas') or [])
            return clean_text(' '.join(str(value) for value in values if value))
        require(before.get('document_search_text') == text(before)
            and after.get('document_search_text') == text(after), 'derived_public_fact_text')


def project_catalog(catalog, cache):
    from scripts.extract_document_evidence import refine_administrative_close, refine_application_cycles
    from scripts.submission_schedule import project
    before, after = deepcopy(catalog), deepcopy(catalog)
    rows = after['opportunities']; changed = []
    require(isinstance(rows, list), 'catalog_rows')
    as_of = common.timestamp(before['generated_at']).date()
    for index, old in enumerate(before['opportunities']):
        row = rows[index]
        cycle_changed = refine_application_cycles(row)
        administrative_changed = refine_administrative_close(row)
        if not (cycle_changed or administrative_changed):
            require(row == old, 'unaffected_row')
            continue
        row = project(row, as_of)
        record_firewall(old, row)
        require(row != old, 'affected_row')
        rows[index] = row
        changed.append(str(old['opportunity_id']))
    if changed:
        from scripts.build_catalog import build_search_index
        after['search_index'] = build_search_index(rows)
    require(unchanged_fields(before, after, {'opportunities', 'search_index'}), 'unchanged_catalog_metadata')
    return after, deepcopy(cache), changed


def projection(parent_root, audit_at, candidate_id):
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.enrich_catalog import read_catalog
    from scripts.subtopic_records import read_cache
    from tools.verify_notice_publication import verify
    parent_root = Path(parent_root)
    before = read_catalog(parent_root / common.PROJECTION[0])
    cache_raw = (parent_root / common.PROJECTION[2]).read_bytes()
    cache = json.loads(cache_raw)
    stamp = before['document_evidence_generated_at']
    require(common.timestamp(audit_at) >= common.timestamp(stamp), 'audit_precedes_evidence')
    after, retained_cache, changed = project_catalog(before, cache)
    require(retained_cache == cache, 'raw_cache_unchanged')
    after['catalog_audit_generated_at'] = audit_at
    gate = verify(after, retained_cache, read_cache(parent_root / 'data/subtopics.js'), candidate_id=candidate_id)
    require(gate['publication_ready'], 'notice_projection_gate')
    outputs = {common.PROJECTION[0]: catalog_javascript_bytes(after),
        common.PROJECTION[1]: catalog_metadata_javascript_bytes(after),
        common.PROJECTION[2]: cache_raw}
    changes_path = parent_root / 'feeds/changes.xml'
    original_changes_path = parent_root / 'feeds/changes.json'
    refreshed_event_ids = []
    changes_xml = changes_path.read_bytes() if changes_path.is_file() else None
    if original_changes_path.is_file():
        from scripts.build_changes import refresh_current_generation_snapshots, render_change_feed
        original_changes = json.loads(original_changes_path.read_bytes())
        refreshed = refresh_current_generation_snapshots(original_changes, after, affected_ids=changed)
        refreshed_event_ids = [new['id'] for old, new in zip(original_changes['events'], refreshed['events'])
            if old != new]
        rendered_changes = {'feeds/' + name: raw for name, raw in render_change_feed(refreshed).items()}
        changes_xml = rendered_changes['feeds/changes.xml']
        outputs.update(rendered_changes)
    outputs.update(common.feed_projection(after, changes_xml, as_of=common.timestamp(audit_at).date()))
    common.verify_feed_index(outputs, outputs, changes_present=changes_xml is not None)
    return outputs, {'projection_kind': 'administrative_submission', 'affected_catalog_ids': changed,
        'affected_evidence_ids': [], 'original_source_at': before['generated_at'],
        'original_evidence_at': stamp, 'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0,
        'refreshed_change_event_ids': refreshed_event_ids}
