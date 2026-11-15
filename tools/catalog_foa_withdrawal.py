"""Withdraw one exact grant after its sponsor closed the announcement."""
from datetime import datetime
import json
from pathlib import Path

from tools import release_candidate as c
from tools.catalog_record_withdrawal import record_hash, withdraw_catalog_records
from tools.catalog_roses_withdrawal import current_feed_outputs

IDENTIFIER = '363660'
NOTICE = 'https://grants.gov/grantsws/rest/opportunity/att/download/355655'
NOTICE_SHA = 'bdc24d9315298a1e5bdf333accdaf499c1025f3fdb242c3ca5708a7145dad82a'
LISTING = 'https://www.grants.gov/search-results-detail/363660'
AGENCY = ('https://mygrants.servicenowservices.com/mygrants'
          '?id=mygrants_form&table=x_g_usd4_d_grant_funding_opportunity'
          '&sys_id=9b532e8f1b0e87502405ea85624bcbf0&view=Default')
NOTICE_LISTED_AT = '2026-11-13T13:43:00Z'
PARENT_CLOCK = '2026-11-15T19:54:40.772589Z'
ROW_SHA = 'd743dc5c1a4d423dff1cffb57b0b86d144328a7b8dac97c86725350cc198693c'
AMENDMENT = 'e600323e1fb306d45481'
AMENDMENT_SHA = 'c0875c6dcdaf9e98e9ed234da1c4044bd1ad09f96a993392239d2c89cfea3af9'


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_foa_withdrawal_' + reason)


def project_sidecars(parent):
    evidence = c.read_json(parent / 'data/document_evidence.json')
    detail = c.read_json(parent / 'data/opportunity_enrichment.json')
    link_health = c.read_json(parent / 'data/link_health.json')
    coverage = c.read_json(parent / 'evaluation/release_coverage.json')
    sidecar = (parent / 'data/subtopics.js').read_text(encoding='utf-8')
    split = sidecar.index('{')
    subtopics = json.loads(sidecar[split:sidecar.rindex('}') + 1])

    entry = evidence['records'].pop(IDENTIFIER)
    require(record_hash(entry) == '3d02fd5fb2bab02ed5493145b4241e6dce04f74f27da95fd7d9cf3df4f96eb03'
            and entry['document']['sha256'] == NOTICE_SHA
            and entry['structure_identity']['document_sha256'] == NOTICE_SHA
            and IDENTIFIER not in evidence['subtopic_only'], 'exact_notice_evidence')
    require(record_hash(detail['records'].pop(IDENTIFIER))
            == '42f760ac5a6855bb47a95c9f9390ecf5676f3539d07bb495e86e17d694a83a0e',
            'exact_primary_selection')
    require(record_hash(subtopics['records'].pop(IDENTIFIER))
            == '49d1e55a921d34d186153fe7ecc857c266417736f0e9f0bffc05eb88c1ee0840'
            and all(not str(key).startswith(IDENTIFIER) for key in subtopics['search_index']['record_ids']),
            'zero_child_parent')
    linked = {url for url, entry in link_health['records'].items() if IDENTIFIER in entry.get('record_ids', [])}
    require(linked == {NOTICE, AGENCY, LISTING}, 'exact_link_set')
    for url in linked:
        require(link_health['records'].pop(url)['record_ids'] == [IDENTIFIER], 'exclusive_link_record')
    require(coverage['source_states'].pop(IDENTIFIER) == 'current', 'coverage_state')
    for field in ('document_status:current', 'retained_structure_identity'):
        coverage['source_counts'][field] -= 1
        coverage['source_count_deltas'][field] -= 1
    coverage['catalog_records'] -= 1
    link_health['url_count'] = len(link_health['records'])
    return {
        'data/document_evidence.json': c.encoded(evidence),
        'data/opportunity_enrichment.json': (json.dumps(detail, ensure_ascii=False, indent=2) + '\n').encode(),
        'data/link_health.json': (json.dumps(link_health, ensure_ascii=False, indent=2) + '\n').encode(),
        'data/subtopics.js': (sidecar[:split] + json.dumps(subtopics, ensure_ascii=False, indent=1) + ';\n').encode(),
        'evaluation/release_coverage.json': c.encoded(coverage),
    }


def project_changes(parent, row):
    from scripts import build_changes as changes

    old = c.read_json(parent / 'feeds/changes.json')
    matches = [event for event in old['events']
               if event['opportunity_id'] == IDENTIFIER and event['changed_at'] == PARENT_CLOCK]
    require(len(matches) == 1 and matches[0]['id'] == AMENDMENT and record_hash(matches[0]) == AMENDMENT_SHA,
            'exact_false_amendment')
    closed = changes._snapshot(row)
    closed.update(status='closed', close_date=None, deadlines=[], funding_opportunity_url=NOTICE,
                  primary_document_url=None)
    closed['next_submission'] = {**row['next_submission'], 'access': 'closed',
                                 'date': None, 'event': None, 'prerequisites': []}
    kind = 'closed_or_removed'
    detail = 'The Department of State published a closure notice on November 13 and is no longer accepting submissions.'
    event_id = changes._event_id(kind, row, PARENT_CLOCK, detail)
    require(all(event['id'] != event_id for event in old['events']), 'unique_closure_event')
    replacement = {'id': event_id, 'type': kind, 'label': changes.EVENT_LABELS[kind],
                   'changed_at': PARENT_CLOCK, 'opportunity_id': IDENTIFIER, 'detail': detail, 'record': closed}
    events = [replacement if event['id'] == AMENDMENT else event for event in old['events']]
    events.sort(key=lambda event: (event['changed_at'], event['id']), reverse=True)
    return changes.render_change_feed({**old, 'events': events}), event_id


def projection(parent, audit_at):
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.enrich_catalog import enrichment_metrics
    from scripts.extract_document_evidence import document_metrics
    from scripts.sources.merge import load_catalog

    parent = Path(parent)
    before = load_catalog(parent / 'data/opportunities.js')
    audit = datetime.fromisoformat(audit_at)
    require(before['generated_at'] == PARENT_CLOCK and audit.tzinfo is not None
            and audit >= datetime.fromisoformat(PARENT_CLOCK), 'catalog_clock')
    records = {str(row['opportunity_id']): row for row in before['opportunities']}
    row = records.get(IDENTIFIER)
    require(len(records) == len(before['opportunities']) and record_hash(row) == ROW_SHA
            and row['opportunity_number'] == 'DFOP0019410' and row['agency_code'] == 'DOS-AF'
            and row['primary_document_url'] == NOTICE and row['status'] == 'posted'
            and row['next_submission']['access'] == 'open', 'exact_retained_grant')
    removed = {'opportunity_id': IDENTIFIER, 'reason': 'officially_closed', 'official_evidence_url': NOTICE,
               'official_notice_sha256': NOTICE_SHA, 'official_notice_listed_at': NOTICE_LISTED_AT,
               'removed_amendment_event_id': AMENDMENT}
    after = withdraw_catalog_records(before, [removed], audit_at)
    for field, count in enrichment_metrics([row]).items():
        after['diagnostics']['detail_enrichment'][field] -= count
    affected_metrics = document_metrics([row], {}, 0, 0, [])
    for field, count in affected_metrics.items():
        if type(count) is int and count:
            after['diagnostics']['document_evidence'][field] -= count
    require(all(item == records[str(item['opportunity_id'])] for item in after['opportunities']),
            'unchanged_retained_records')

    changes, event_id = project_changes(parent, row)
    outputs = project_sidecars(parent)
    outputs.update(current_feed_outputs(after, changes['changes.xml'], audit_at))
    outputs.update({f'feeds/{name}': raw for name, raw in changes.items()})
    outputs.update({'data/opportunities.js': catalog_javascript_bytes(after),
                    'data/catalog-metadata.js': catalog_metadata_javascript_bytes(after)})
    return outputs, {'withdrawn': [removed | {'closure_event_id': event_id}],
                     'original_generated_at': PARENT_CLOCK, 'retained_record_count': len(after['opportunities']),
                     'source_requests': 0, 'provider_requests': 0}
