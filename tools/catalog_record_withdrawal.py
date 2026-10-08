"""Deterministic, evidence-pinned withdrawals; never re-collect or enrich sources."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile

from tools import release_candidate as c

POLICY = 'evaluation/catalog_source_withdrawals_20261008.json'
REMOVED = frozenset({'eere-exchange:DE-TA1-0003589', 'vpr-email:NSF26-510',
    'vpr-email:NSF26-512', 'vpr-email:26-514', 'vpr-email:vpr-e4cc1ac2aa40787d', 'vpr-email:NSF25-544'})


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_record_withdrawal_' + reason)


def record_hash(record):
    return c.digest(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def policy():
    value = c.read_json(c.ROOT/POLICY)
    require(value['candidate_id'] == '5801e4912b642ad70e4383b0f805adc95aad7d892b85f8b7638aeca958da85e6'
        and {r['opportunity_id'] for r in value['removals']} == REMOVED
        and len(value['removals']) == len(REMOVED), 'fixed_policy')
    return value


def corrected_catalog(before, evidence, audit_at):
    from scripts.build_catalog import facet_counts, quality_metrics, build_search_index
    require({r['opportunity_id'] for r in evidence['removals']} == REMOVED
        and len(evidence['removals']) == len(REMOVED), 'fixed_withdrawal_set')
    audit = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    stamp = datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00'))
    require(audit.tzinfo is not None and audit >= stamp, 'audit_clock')
    records = {str(r['opportunity_id']): r for r in before['opportunities']}
    require(len(records) == len(before['opportunities']), 'unique_parent_ids')
    for row in evidence['removals']:
        require(row['opportunity_id'] in records
            and record_hash(records[row['opportunity_id']]) == row['record_sha256'], 'exact_removed_record')
        if row['reason'] in ('duplicate', 'stale_edition_conflict'):
            require(row['retained_id'] not in REMOVED and row['retained_id'] in records
                and record_hash(records[row['retained_id']]) == row['retained_record_sha256'], 'exact_retained_record')
        else:
            require(row['reason'] == 'officially_closed' and row['official_status'] == 'Closed'
                and row['opportunity_id'] == 'eere-exchange:DE-TA1-0003589', 'official_terminal_evidence')
    after = deepcopy(before)
    after['opportunities'] = [r for r in after['opportunities'] if str(r['opportunity_id']) not in REMOVED]
    require(len(before['opportunities']) - len(after['opportunities']) == len(REMOVED), 'exact_removal_count')
    after['record_count'] = len(after['opportunities'])
    after['status_counts'] = dict(sorted(Counter(r['status'] for r in after['opportunities']).items()))
    after['facets'] = facet_counts(after['opportunities'])
    after['search_index'] = build_search_index(after['opportunities'])
    after['diagnostics']['quality'] = quality_metrics(after['opportunities'])
    additional = after['diagnostics']['additional_sources']
    additional['source_record_counts'] = dict(sorted(Counter(r['source'] for r in after['opportunities']
        if r.get('source') and r['source'] != 'Grants.gov').items()))
    # Keep historical adapter health/last-success clocks. This audit certifies
    # exact withdrawals, not a successful refresh of a whole migrated source.
    after['diagnostics']['record_withdrawal'] = {'audited_at': audit_at,
        'records': [{k: row[k] for k in ('opportunity_id', 'reason', 'official_evidence_url')}
            for row in evidence['removals']], 'new_provider_requests': 0}
    after['catalog_audit_generated_at'] = audit_at
    return after


def corrected_cache(before, evidence, audit_at):
    result = deepcopy(before)
    found = set()
    for slug, source in result['sources'].items():
        rows = source.get('records', [])
        removed = [r for r in rows if str(r.get('opportunity_id')) in REMOVED]
        if not removed:
            continue
        found.update(str(r['opportunity_id']) for r in removed)
        source['records'] = [r for r in rows if str(r.get('opportunity_id')) not in REMOVED]
        source['record_count'] = len(source['records'])
        source.setdefault('diagnostics', {})['record_withdrawal'] = {
            'audited_at': audit_at, 'ids': sorted(str(r['opportunity_id']) for r in removed)}
    require(found == REMOVED, 'all_withdrawals_removed_from_fallback')
    # Identity witnesses remain immutable historical facts, not current records.
    return result


def change_projection(parent, before, after, evidence, audit_at):
    from scripts import build_changes as changes
    stamp = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    prior = c.read_json(parent/'feeds/changes.json')
    records = {str(r['opportunity_id']): r for r in before['opportunities']}
    events = []
    for row in evidence['removals']:
        closed = row['reason'] == 'officially_closed'
        kind = 'closed_or_removed' if closed else 'source_correction'
        record = deepcopy(records[row['opportunity_id'] if closed else row['retained_id']])
        if closed:
            record['status'] = 'closed'
            record['detail_page'] = row['official_evidence_url']
            record['funding_opportunity_url'] = row['official_evidence_url']
        detail = ('Official DOE portal marks this call Closed.' if closed else
            'Duplicate digest entry removed; the official call remains available.' if row['reason'] == 'duplicate' else
            'Digest entry cited an older solicitation; the separately verified current edition remains available.')
        events.append({'id': changes._event_id(kind, records[row['opportunity_id']], audit_at, detail),
            'type': kind, 'label': changes.EVENT_LABELS[kind], 'changed_at': audit_at,
            'opportunity_id': row['opportunity_id'], 'detail': detail, 'record': changes._snapshot(record)})
    # Preserve every retained historical event byte-for-value; append only the
    # newly evidenced corrections, without re-running unrelated change detection.
    merged = {event['id']: event for event in prior['events']}
    merged.update({event['id']: event for event in events})
    ordered = sorted(merged.values(), key=lambda e: (e.get('changed_at', ''), e['id']), reverse=True)
    payload = {**prior, 'generated_at': audit_at, 'events': ordered}
    return {'feeds/changes.json': (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode(),
        'feeds/changes.xml': changes.build_atom(ordered, stamp).encode()}


def projection(parent_root, audit_at):
    from scripts.sources.merge import load_catalog
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.build_feeds import build_feeds
    parent = Path(parent_root); evidence = policy()
    before = load_catalog(parent/'data/opportunities.js')
    after = corrected_catalog(before, evidence, audit_at)
    cache = corrected_cache(c.read_json(parent/'data/source_records.json'), evidence, audit_at)
    outputs = {'data/opportunities.js': catalog_javascript_bytes(after),
        'data/catalog-metadata.js': catalog_metadata_javascript_bytes(after),
        'data/source_records.json': c.encoded(cache)}
    outputs.update(change_projection(parent, before, after, evidence, audit_at))
    with tempfile.TemporaryDirectory(prefix='catalog-withdrawal-feeds-') as temporary:
        root = Path(temporary); feeds = root/'feeds'; feeds.mkdir()
        (feeds/'changes.xml').write_bytes(outputs['feeds/changes.xml'])
        build_feeds(after, feeds, as_of=datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00')).date())
        outputs.update({p.relative_to(root).as_posix(): p.read_text(encoding='utf8').encode()
            for p in feeds.rglob('*') if p.is_file()})
    require(all(r == next(old for old in before['opportunities'] if old['opportunity_id'] == r['opportunity_id'])
        for r in after['opportunities']), 'unchanged_retained_records')
    return outputs, {'policy_sha256': c.digest((c.ROOT/POLICY).read_bytes()),
        'removed_ids': sorted(REMOVED), 'retained_record_count': len(after['opportunities']),
        'unchanged_retained_record_hashes': {str(r['opportunity_id']): record_hash(r) for r in after['opportunities']},
        'original_generated_at': before['generated_at'], 'source_requests': 0, 'provider_requests': 0}
