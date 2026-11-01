"""Withhold disproved retained facts without recollecting source documents.

The same quote guard protects ordinary extraction and this explicit recovery.
Only proved invalid facts, their derived public text, and their removal receipts
may change. Source identity, source clocks, and all other facts remain exact.
"""
from copy import deepcopy
import json
from pathlib import Path

from scripts import extract_document_evidence as evidence
from scripts import notice_fact_guards as guards
from tools import program_area_revalidation as common


def require(ok, reason):
    if not ok:
        raise ValueError('document_fact_revalidation_' + reason)


def unchanged(before, after, allowed):
    return {k: v for k, v in before.items() if k not in allowed} == {
        k: v for k, v in after.items() if k not in allowed}


def search_text(row):
    values = [value for fact in (row.get('document_evidence') or {}).get('facts', [])
        for value in (fact.get('label'), fact.get('display_value'),
                      (fact.get('citation') or {}).get('quote'))]
    values.extend(row.get('document_program_areas') or [])
    return evidence.clean_text(' '.join(str(value) for value in values if value))


def fact_firewall(before, after, document):
    expected, changes = guards.repair_facts(before, document)
    require(after == expected, 'only_proved_fact_removals')
    # Removal preserves both order and complete retained dictionaries. This
    # separate check prevents a guard change from silently broadening recovery
    # into new facts, edited citations, new amounts, or new interpretations.
    cursor = iter(before)
    require(all(any(old == fact for old in cursor) for fact in after),
            'unchanged_retained_facts_and_order')
    return changes


def record_firewall(before, after):
    require(unchanged(before, after, {'document_evidence', 'document_search_text'}),
            'unchanged_source_fields_and_clocks')
    old, new = before.get('document_evidence') or {}, after.get('document_evidence') or {}
    require(unchanged(old, new, {'facts', 'review_queue'}), 'unchanged_document_identity')
    changes = fact_firewall(old.get('facts', []), new.get('facts', []), old.get('document') or {})
    if changes:
        require(before.get('document_search_text') == search_text(before)
                and after.get('document_search_text') == search_text(after),
                'canonical_public_fact_text')
    else:
        require(before == after, 'unaffected_record')
    return changes


def project_catalog(catalog, cache):
    from scripts.build_catalog import build_search_index

    before, after, updated = deepcopy(catalog), deepcopy(catalog), deepcopy(cache)
    require(isinstance(before.get('opportunities'), list)
            and isinstance(cache.get('records'), dict), 'retained_inputs')
    cache_changes, public_changes = {}, {}
    for identifier, old in cache['records'].items():
        require(isinstance(old, dict), 'cache_entry')
        entry = updated['records'][identifier]
        changes = guards.repair_entry(entry)
        if not changes:
            require(entry == old, 'unaffected_cache_entry')
            continue
        require(unchanged(old, entry, {'facts', 'fact_guard'}),
                'unchanged_cache_document_and_clocks')
        fact_firewall(old.get('facts', []), entry.get('facts', []), old.get('document') or {})
        # Reconstruct the permitted entry with the deterministic shared guard;
        # no general document reparse or parser-family migration is authorized.
        expected = deepcopy(old)
        require(guards.repair_entry(expected) == changes and entry == expected,
                'exact_cache_guard_receipt')
        cache_changes[str(identifier)] = changes

    require(unchanged(cache, updated, {'records'})
            and set(cache['records']) == set(updated['records']), 'unchanged_cache_inventory_and_clock')
    for index, old in enumerate(before['opportunities']):
        identifier = str(old['opportunity_id'])
        row = after['opportunities'][index]
        document = (old.get('document_evidence') or {}).get('document') or {}
        facts = (old.get('document_evidence') or {}).get('facts', [])
        retained, changes = guards.repair_facts(facts, document)
        if not changes:
            require(row == old, 'unaffected_record')
            continue
        require(identifier in cache_changes and old.get('document_evidence_status') == 'current',
                'matching_current_cache_correction')
        entry = deepcopy(updated['records'][identifier])
        replay = evidence.merge_document_entry(deepcopy(old), entry)
        require(entry == updated['records'][identifier], 'no_unrelated_cache_repair')
        replay_evidence = replay.get('document_evidence') or {}
        require(replay_evidence.get('facts') == retained, 'matching_public_cache_facts')
        row['document_evidence']['facts'] = retained
        row['document_evidence']['review_queue'] = deepcopy(replay_evidence.get('review_queue', []))
        row['document_search_text'] = search_text(row)
        record_firewall(old, row)
        public_changes[identifier] = changes

    if public_changes:
        after['search_index'] = build_search_index(after['opportunities'])
    require(unchanged(before, after, {'opportunities', 'search_index'}),
            'unchanged_catalog_metadata')
    return after, updated, {'affected_catalog_ids': sorted(public_changes),
        'affected_evidence_ids': sorted(cache_changes), 'public_fact_changes': public_changes,
        'cached_fact_changes': cache_changes, 'guard_version': guards.VERSION}


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
    after, updated, changes = project_catalog(before, cache)
    after['catalog_audit_generated_at'] = audit_at
    gate = verify(after, updated, read_cache(parent_root / 'data/subtopics.js'), candidate_id=candidate_id)
    require(gate['publication_ready'], 'notice_projection_gate')
    cache_bytes = ((json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
                   if updated != cache else cache_raw)
    outputs = {common.PROJECTION[0]: catalog_javascript_bytes(after),
        common.PROJECTION[1]: catalog_metadata_javascript_bytes(after), common.PROJECTION[2]: cache_bytes}
    changes_path = parent_root / 'feeds/changes.xml'
    outputs.update(common.feed_projection(after, changes_path.read_bytes() if changes_path.is_file() else None))
    common.verify_feed_index(outputs, outputs, changes_present=changes_path.is_file())
    return outputs, changes | {'projection_kind': 'document_facts',
        'original_source_at': before['generated_at'], 'original_evidence_at': stamp,
        'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0}
