"""Add corrected lexical topic labels to one retained immutable catalog.

The original protected classifier supplies the baseline. Only newly recognized
labels may join existing labels; source facts, document caches and clocks stay
retained. No source, document, team or embedding requests belong to this stage.
"""
import ast
from copy import deepcopy
import json
from pathlib import Path
import re

from scripts import build_catalog
from tools import program_area_revalidation as common


def require(ok, reason):
    if not ok:
        raise ValueError('topic_area_revalidation_' + reason)


def prior_rules(generation_sha, *, root=None):
    root = common.ROOT if root is None else Path(root)
    require(isinstance(generation_sha, str) and re.fullmatch('[a-f0-9]{40}', generation_sha),
        'protected_generation_sha')
    common.candidate.git(root, 'merge-base', '--is-ancestor', generation_sha, 'HEAD')
    source = common.candidate.git(root, 'show', generation_sha + ':scripts/build_catalog.py')
    values = [node.value for node in ast.parse(source).body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'TOPIC_RULES' for target in node.targets)]
    require(len(values) == 1, 'unique_original_topic_rules')
    try:
        rules = ast.literal_eval(values[0])
    except (ValueError, TypeError, SyntaxError):
        raise ValueError('topic_area_revalidation_literal_original_topic_rules') from None
    require(isinstance(rules, dict) and rules and all(isinstance(key, str) and isinstance(value, str)
        for key, value in rules.items()), 'original_topic_rules')
    return {key: re.compile(value, re.I) for key, value in rules.items()}


def classified(row, rules):
    text = ' '.join(part for part in (row.get('title'), row.get('description'),
        ' '.join(row.get('funding_categories') or [])) if part)
    return [name for name, pattern in rules.items() if pattern.search(text)]


def record_firewall(before, after, additions):
    expected = deepcopy(before)
    topics = list(dict.fromkeys(list(before.get('topic_areas') or []) + list(additions)))
    expected['topic_areas'] = topics
    receipt = (before.get('document_evidence') or {}).get('source_fields', {}).get('topic_areas')
    if receipt is not None:
        require(isinstance(receipt, dict) and set(receipt) == {'present', 'value'}
            and receipt['present'] is True and receipt['value'] == before.get('topic_areas'),
            'bound_original_source_topics')
        expected['document_evidence']['source_fields']['topic_areas']['value'] = topics
    require(after == expected, 'only_additive_topics_and_bound_source_receipt')


def project_catalog(catalog, original_rules):
    before, after = deepcopy(catalog), deepcopy(catalog)
    changed, receipts = [], []
    for old, row in zip(before['opportunities'], after['opportunities'], strict=True):
        prior = classified(old, original_rules)
        current = build_catalog.topic_areas(old.get('title'), old.get('description'),
            old.get('funding_categories') or [])
        require(set(prior) <= set(current), 'classifier_removes_original_topic')
        additions = [topic for topic in current if topic not in prior]
        if not additions:
            continue
        row['topic_areas'] = list(dict.fromkeys(list(old.get('topic_areas') or []) + additions))
        source_receipt = (row.get('document_evidence') or {}).get('source_fields', {}).get('topic_areas')
        if source_receipt is not None:
            source_receipt['value'] = deepcopy(row['topic_areas'])
        record_firewall(old, row, additions)
        if row != old:
            changed.append(str(old['opportunity_id']))
            if source_receipt is not None:
                receipts.append(str(old['opportunity_id']))
    if changed:
        after['facets'] = build_catalog.facet_counts(after['opportunities'])
        after['search_index'] = build_catalog.build_search_index(after['opportunities'])
    require({key: value for key, value in before.items() if key not in {'opportunities', 'facets', 'search_index'}}
        == {key: value for key, value in after.items() if key not in {'opportunities', 'facets', 'search_index'}},
        'retained_catalog_metadata')
    return after, changed, receipts


def verify_serialized_catalog(before, raw, original_rules):
    published = json.loads(raw.decode('utf-8').split('=', 1)[1].strip().removesuffix(';'))
    require(len(before['opportunities']) == len(published['opportunities']), 'serialized_row_membership')
    for old, new in zip(before['opportunities'], published['opportunities'], strict=True):
        prior = classified(old, original_rules)
        additions = [topic for topic in build_catalog.topic_areas(old.get('title'), old.get('description'),
            old.get('funding_categories') or []) if topic not in prior]
        if additions:
            record_firewall(old, new, additions)
        else:
            require(old == new, 'serialized_unaffected_row')
    require({key: value for key, value in before.items()
        if key not in {'opportunities', 'facets', 'search_index', 'catalog_audit_generated_at'}} ==
        {key: value for key, value in published.items()
        if key not in {'opportunities', 'facets', 'search_index', 'catalog_audit_generated_at'}},
        'serialized_catalog_metadata')
    return published


def projection(parent_root, audit_at, candidate_id):
    from scripts.build_changes import refresh_current_generation_snapshots, render_change_feed
    from scripts.enrich_catalog import read_catalog
    from scripts.subtopic_records import read_cache
    from tools.catalog_publication_evidence import change_snapshot_findings
    from tools.verify_notice_publication import verify

    parent_root = Path(parent_root)
    manifest = common.candidate.load(parent_root.parent, candidate_id)
    before = read_catalog(parent_root / common.PROJECTION[0])
    cache_raw = (parent_root / common.PROJECTION[2]).read_bytes()
    cache = json.loads(cache_raw)
    stamp = before['document_evidence_generated_at']
    require(common.timestamp(audit_at) >= common.timestamp(stamp), 'audit_precedes_evidence')
    original_rules = prior_rules(manifest['generation_sha'])
    after, changed, receipts = project_catalog(before, original_rules)
    after['catalog_audit_generated_at'] = audit_at
    gate = verify(after, cache, read_cache(parent_root / 'data/subtopics.js'), candidate_id=candidate_id)
    require(gate['publication_ready'], 'notice_projection_gate')
    outputs = {common.PROJECTION[0]: build_catalog.catalog_javascript_bytes(after),
        common.PROJECTION[1]: build_catalog.catalog_metadata_javascript_bytes(after),
        common.PROJECTION[2]: cache_raw}
    verify_serialized_catalog(before, outputs[common.PROJECTION[0]], original_rules)
    original_changes = json.loads((parent_root / 'feeds/changes.json').read_bytes())
    canonical = build_catalog.compact_catalog_payload(after)
    refreshed = refresh_current_generation_snapshots(original_changes, canonical, affected_ids=changed)
    for old, new in zip(original_changes['events'], refreshed['events'], strict=True):
        if old.get('type') == 'closed_or_removed':
            new.clear(); new.update(deepcopy(old))
    rendered = {'feeds/' + name: raw for name, raw in render_change_feed(refreshed).items()}
    require(not change_snapshot_findings(canonical, json.loads(rendered['feeds/changes.json'])),
        'serialized_change_snapshot_gate')
    outputs.update(rendered)
    outputs.update(common.feed_projection(after, rendered['feeds/changes.xml'],
        as_of=common.timestamp(audit_at).date()))
    common.verify_feed_index(outputs, outputs, changes_present=True)
    return outputs, {'projection_kind': 'topic_area', 'affected_catalog_ids': changed,
        'affected_evidence_ids': [], 'updated_source_topic_receipt_ids': receipts,
        'original_source_at': before['generated_at'], 'original_evidence_at': stamp,
        'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0,
        'refreshed_change_event_ids': [new['id'] for old, new in
            zip(original_changes['events'], refreshed['events'], strict=True) if old != new]}
