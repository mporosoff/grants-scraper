"""Replay two official ROSES closures against one retained catalog."""
from datetime import datetime
import json
from pathlib import Path
import tempfile

from tools import release_candidate as c
from tools.catalog_record_withdrawal import record_hash, withdraw_catalog_records


CASES = {
    'nasa-roses:25-A.10-87da4095c3': {
        'record': '124f883dd9953ab3c160e4a6cf81e4efdfede44306ef5fe0322bebc022eb6bb0',
        'cache': '42c64e43745ff62f6f2d682e8d69b4f5dcc7623d38b5cd57bd42d4aa0b465b6e',
        'event': '380fdee277229d07bbd2',
        'event_hash': '305d9569207a718a5af904803ce53b7b0744de1424fd1be4c3d0fa085b15ed0b',
        'guid': '9E3216E9-ADB7-B72A-A1D7-12EC8050DC3F',
        'deadline': '2026-08-31',
        'amendment': 'amendment-41-a-10-innovate-updates/',
        'access': 'closed',
        'existing_coverage': True,
    },
    'nasa-roses:25-C.2-e5e8e39f99': {
        'record': '31ea7738416b38b98b88ecf767634214bb553efa793b69831b5bab96bfe6292d',
        'cache': '03694aecc552ae943d6ca6189b34f6b2767a636c3ac75a23ed5a21ba79552245',
        'event': '94bee1c7e97444fc08f1',
        'event_hash': '5e029bde57a14780755ea83772fbe30744b880939ae2301fc2208c7ab37abd87',
        'guid': 'C92A28D2-9E30-4149-24B7-8A40ED4F564B',
        'deadline': '2026-11-12',
        'amendment': 'amendment-60-final-2025-due-date-extended-for-c-2-solar-system-science/',
        'access': 'not_listed',
        'existing_coverage': False,
    },
}
NASA = 'https://science.nasa.gov/researchers/solicitations/roses-2025/'
NSPIRES = 'https://nspires.nasaprs.com/external/solicitations/summary.do?solId={%s}&path=&method=init'
PARENT_CLOCK = '2026-11-13T17:51:59.801255Z'
SOLAR_SYSTEM_ALIAS = 'nasa-roses:25-C.2-e5e8e39f99'
CANONICAL_EVENT = 'c982d4c2dbcf40023166'
CANONICAL_EVENT_SHA = 'fb4e6a42c1dd617ccdb38fc40471444b7fb59d60f840a36fd96b195afdc1adee'


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_roses_withdrawal_' + reason)


def project_membership(before, source_cache, changes, audit_at):
    clock = datetime.fromisoformat(before['generated_at'])
    audit = datetime.fromisoformat(audit_at)
    require(before['generated_at'] == PARENT_CLOCK and audit.tzinfo is not None
            and audit >= clock, 'catalog_clock')
    source = source_cache['sources']['nasa-roses']
    records = {str(row['opportunity_id']): row for row in before['opportunities']}
    cached = {row['opportunity_id']: row for row in source['records']}
    events = {row['id']: row for row in changes['events']}
    require(len(records) == len(before['opportunities']) and len(cached) == len(source['records'])
            and len(events) == len(changes['events']), 'unique_input_identities')
    removals = []
    for identifier, case in CASES.items():
        record, cache = records.get(identifier), cached.get(identifier)
        require(record is not None and record_hash(record) == case['record'], 'exact_public_record')
        require(cache is not None and record_hash(cache) == case['cache'], 'exact_source_record')
        url = NSPIRES % case['guid']
        require(record['agency'] == 'NASA Headquarters' and record['source'] == 'NASA ROSES'
                and record['status'] == 'posted' and record['close_date'] is None
                and record['next_submission']['access'] == case['access']
                and record['funding_opportunity_url'] == cache['funding_opportunity_url'] == url
                and case['deadline'] < clock.date().isoformat(), 'same_sponsor_and_past_cutoff')
        event = events.get(case['event'])
        require(event is not None and record_hash(event) == case['event_hash']
                and event['opportunity_id'] == identifier and event['type'] == 'new'
                and event['changed_at'][:10] > case['deadline'], 'false_new_event')
        removals.append({'opportunity_id': identifier, 'reason': 'officially_closed',
            'official_evidence_url': NASA + case['amendment'], 'official_cutoff': case['deadline'],
            'nspires_url': url, 'removed_new_event_id': case['event']})
    canonical = events.get(CANONICAL_EVENT)
    require(canonical is not None and record_hash(canonical) == CANONICAL_EVENT_SHA
            and canonical['opportunity_id'] == '360004' and canonical['type'] == 'closed_or_removed'
            and '360004' not in records, 'exact_canonical_closure')
    deadline = canonical['record']['next_submission']['event']
    solar_system = CASES[SOLAR_SYSTEM_ALIAS]
    require(canonical['record']['agency'] == 'NASA Headquarters'
            and canonical['record']['funding_opportunity_url'] == NSPIRES % solar_system['guid']
            and canonical['record']['close_date'] == deadline['date'] == solar_system['deadline']
            and deadline['source_field'] == 'CloseDate'
            and deadline['confidence'] == 'official_structured', 'canonical_structured_deadline')
    source['records'] = [row for row in source['records'] if row['opportunity_id'] not in CASES]
    source['record_count'] = len(source['records'])
    dropped = {row['removed_new_event_id'] for row in removals}
    changes['events'] = [row for row in changes['events'] if row['id'] not in dropped]
    after = withdraw_catalog_records(before, removals, audit_at)
    require(all(row == records[str(row['opportunity_id'])] for row in after['opportunities']),
            'unchanged_retained_records')
    return after, removals


def project_sidecars(parent):
    evidence = c.read_json(parent / 'data/document_evidence.json')
    link_health = c.read_json(parent / 'data/link_health.json')
    coverage = c.read_json(parent / 'evaluation/release_coverage.json')
    sidecar = (parent / 'data/subtopics.js').read_text(encoding='utf8')
    split = sidecar.index('{')
    subtopics = json.loads(sidecar[split:sidecar.rindex('}') + 1])
    for identifier, case in CASES.items():
        url = NSPIRES % case['guid']
        entry = evidence['records'].pop(identifier)
        require(entry['source_url'] == url and entry['status'] == 'current' and entry.get('structure_identity')
                and not entry.get('parser_pending') and identifier not in evidence.get('subtopic_only', {}),
                'scoped_document_evidence')
        require(subtopics['records'].pop(identifier)['subtopics'] == []
                and all(not str(key).startswith(identifier) for key in subtopics['search_index']['record_ids']),
                'empty_subtopic_parent')
        require(link_health['records'].pop(url)['record_ids'] == [identifier], 'withdrawn_link_diagnostic')
        require(coverage['source_states'].pop(identifier) == 'current', 'withdrawn_coverage_row')
        if not case['existing_coverage']:
            coverage['source_transitions']['new->current'] -= 1
    for field in ('document_status:current', 'retained_structure_identity'):
        coverage['source_counts'][field] -= len(CASES)
        coverage['source_count_deltas'][field] -= len(CASES)
    coverage['catalog_records'] -= len(CASES)
    link_health['url_count'] = len(link_health['records'])
    return {
        'data/document_evidence.json': c.encoded(evidence),
        'data/link_health.json': (json.dumps(link_health, ensure_ascii=False, indent=2) + '\n').encode(),
        'data/subtopics.js': (sidecar[:split] + json.dumps(subtopics, ensure_ascii=False, indent=1) + ';\n').encode(),
        'evaluation/release_coverage.json': c.encoded(coverage),
    }


def projection(parent, audit_at):
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.build_changes import build_atom
    from scripts.build_feeds import build_feeds
    from scripts.sources.merge import load_catalog

    parent = Path(parent)
    before = load_catalog(parent / 'data/opportunities.js')
    source = c.read_json(parent / 'data/source_records.json')
    changes = c.read_json(parent / 'feeds/changes.json')
    catalog, removals = project_membership(before, source, changes, audit_at)
    outputs = project_sidecars(parent)
    outputs.update({
        'data/opportunities.js': catalog_javascript_bytes(catalog),
        'data/catalog-metadata.js': catalog_metadata_javascript_bytes(catalog),
        'data/source_records.json': c.encoded(source),
        'feeds/changes.json': (json.dumps(changes, ensure_ascii=False, indent=2) + '\n').encode(),
        'feeds/changes.xml': build_atom(changes['events'], datetime.fromisoformat(changes['generated_at'])).encode(),
    })
    with tempfile.TemporaryDirectory(prefix='roses-withdrawal-feeds-') as directory:
        root = Path(directory)
        feeds = root / 'feeds'
        feeds.mkdir()
        (feeds / 'changes.xml').write_bytes(outputs['feeds/changes.xml'])
        build_feeds(catalog, feeds, as_of=datetime.fromisoformat(PARENT_CLOCK).date())
        outputs.update({path.relative_to(root).as_posix(): path.read_bytes()
                        for path in feeds.rglob('*') if path.is_file()})
    require(all(identifier.encode() not in raw for name, raw in outputs.items() for identifier in CASES
                if name not in ('data/opportunities.js', 'data/catalog-metadata.js')),
            'no_withdrawn_record_in_current_projections')
    return outputs, {
        'withdrawn': removals, 'protected_canonical_closure_event': CANONICAL_EVENT,
        'original_generated_at': before['generated_at'], 'retained_record_count': len(catalog['opportunities']),
        'source_requests': 0, 'provider_requests': 0,
    }
