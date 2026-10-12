"""Restore two authenticated public aliases without new source or provider work."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile

from tools import release_candidate as c

POLICY = 'evaluation/catalog_identity_correction_20261012.json'
PARENT_ID = '75e383c2a4fe48ece7ca2e1afc4fc0a0470dfe9f3133654da9b306aefa8c41ff'
PREVIOUS_ID = '309e39320351c2ca959e4896289edeed5ff3ed4e37e1fc95a1d79b68813dbc67'
CHANGED = frozenset({'364039', '363829'})
REMOVED_EVENTS = frozenset({'7278311ccd6ffc55323b', '889ae59b100100c3b09b'})
PREVIOUS_RECORDS = frozenset({'nasa-roses:25-B.8-c9ad18a888', '363829'})


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_identity_projection_' + reason)


def value_hash(value):
    return c.digest(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def fixed_policy(evidence):
    require(evidence.get('schema_version') == 1 and evidence.get('candidate_id') == PARENT_ID
            and evidence.get('previous_candidate_id') == PREVIOUS_ID
            and set(evidence.get('previous_record_hashes', {})) == PREVIOUS_RECORDS
            and {row['opportunity_id'] for row in evidence['corrections']} == CHANGED
            and len(evidence['corrections']) == len(CHANGED)
            and set(evidence['removed_event_hashes']) == REMOVED_EVENTS, 'fixed_policy')


def policy():
    evidence = c.read_json(c.ROOT / POLICY)
    fixed_policy(evidence)
    return evidence


def corrected_catalog(before, evidence, audit_at):
    fixed_policy(evidence)
    audit = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    original = datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00'))
    require(audit.tzinfo is not None and original.tzinfo is not None and audit >= original, 'audit_clock')
    require(before['generated_at'] == evidence['original_generated_at'], 'generation_clock')
    records = {str(row['opportunity_id']): row for row in before['opportunities']}
    require(len(records) == len(before['opportunities']) == evidence['record_count'], 'parent_membership')
    after = deepcopy(before)
    updated = {str(row['opportunity_id']): row for row in after['opportunities']}
    proof = {}
    claimed = {str(a.get('opportunity_id')) for row in before['opportunities'] for a in row.get('source_aliases') or []}
    for item in evidence['corrections']:
        ident = item['opportunity_id']
        old = records.get(ident)
        require(old is not None and value_hash(old) == item['record_sha256'], 'exact_record')
        aliases = item['source_aliases']
        require(len(aliases) == 1 and item['previous_opportunity_id'] in PREVIOUS_RECORDS, 'alias_inventory')
        alias = aliases[0]
        expected_id = 'nasa-roses:25-B.8-c9ad18a888' if ident == '364039' else 'vpr-email:vpr-a3ddeff815d159a4'
        require(alias.get('opportunity_id') == expected_id and expected_id not in claimed
                and expected_id not in records, 'unique_alias_owner')
        require(not old.get('source_aliases'), 'original_alias_absent')
        updated[ident]['source_aliases'] = deepcopy(aliases)
        require(value_hash(updated[ident]) == item['expected_record_sha256'], 'expected_record')
        claimed.add(expected_id)
        proof[ident] = {'before_sha256': value_hash(old), 'after_sha256': value_hash(updated[ident]),
                        'changed_fields': ['source_aliases'], 'alias_id': expected_id}
    # No timestamp, diagnosis, scientific field or membership changes belong in
    # this correction. Its separate receipt carries the audit clock.
    require(all(row == records[str(row['opportunity_id'])] for row in after['opportunities']
                if str(row['opportunity_id']) not in CHANGED), 'unchanged_other_records')
    require({k: v for k, v in after.items() if k != 'opportunities'}
            == {k: v for k, v in before.items() if k != 'opportunities'}, 'unchanged_catalog_metadata')
    return after, proof


def corrected_changes(prior, before, evidence):
    fixed_policy(evidence)
    events = prior['events']
    require(len({event['id'] for event in events}) == len(events), 'unique_event_ids')
    removed = {event['id']: event for event in events if event['id'] in REMOVED_EVENTS}
    require({key: value_hash(event) for key, event in removed.items()} == evidence['removed_event_hashes'], 'exact_removed_events')
    expected = {'7278311ccd6ffc55323b': ('new', '364039'),
                '889ae59b100100c3b09b': ('closed_or_removed', 'nasa-roses:25-B.8-c9ad18a888')}
    for key, event in removed.items():
        require((event['type'], event['opportunity_id']) == expected[key]
                and event['changed_at'] == before['generated_at'], 'current_false_event')
    retained = [deepcopy(event) for event in events if event['id'] not in REMOVED_EVENTS]
    require(len(retained) == evidence['retained_event_count']
            and value_hash(retained) == evidence['retained_events_sha256'], 'exact_retained_history')
    # The source did not change during this repair. In particular, do not mint
    # an amendment from different providers' last_updated representations.
    result = deepcopy(prior)
    result['events'] = retained
    return result, {key: {'action': 'suppress_false_identity_transition', 'before_sha256': value_hash(event)}
                    for key, event in removed.items()}


def projection(parent_root, audit_at):
    from scripts.sources.merge import load_catalog
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.build_feeds import build_feeds
    from scripts.build_changes import build_atom
    parent = Path(parent_root)
    evidence = policy()
    manifest = parent.parent / 'candidate.json'
    require(c.digest(manifest.read_bytes()) == evidence['candidate_manifest_sha256']
            and c.read_json(manifest)['candidate_id'] == PARENT_ID, 'exact_parent')
    require(all(c.digest(c.checked_path(parent, name).read_bytes()) == expected
                for name, expected in evidence['input_hashes'].items()), 'exact_inputs')
    before = load_catalog(parent / 'data/opportunities.js')
    after, record_proof = corrected_catalog(before, evidence, audit_at)
    prior_changes = c.read_json(parent / 'feeds/changes.json')
    changes, event_proof = corrected_changes(prior_changes, before, evidence)
    outputs = {'data/opportunities.js': catalog_javascript_bytes(after),
               'data/catalog-metadata.js': catalog_metadata_javascript_bytes(after),
               'feeds/changes.json': (json.dumps(changes, ensure_ascii=False, indent=2) + '\n').encode(),
               'feeds/changes.xml': build_atom(changes['events'], datetime.fromisoformat(changes['generated_at'].replace('Z', '+00:00'))).encode()}
    with tempfile.TemporaryDirectory(prefix='catalog-identity-feeds-') as temporary:
        target = Path(temporary)
        feeds = target / 'feeds'
        feeds.mkdir()
        (feeds / 'changes.xml').write_bytes(outputs['feeds/changes.xml'])
        build_feeds(after, feeds)
        outputs.update({path.relative_to(target).as_posix(): path.read_text(encoding='utf8').encode()
                        for path in feeds.rglob('*') if path.is_file()})
    return outputs, {'policy_sha256': c.digest((c.ROOT / POLICY).read_bytes()),
                     'parent_candidate_id': PARENT_ID,
                     'parent_manifest_sha256': evidence['candidate_manifest_sha256'],
                     'previous_candidate_id': PREVIOUS_ID,
                     'changed_ids': sorted(CHANGED), 'records': record_proof, 'events': event_proof,
                     'retained_record_count': len(after['opportunities']),
                     'original_generated_at': before['generated_at'], 'audited_at': audit_at,
                     'unchanged_record_hashes': {str(row['opportunity_id']): value_hash(row)
                         for row in before['opportunities'] if str(row['opportunity_id']) not in CHANGED},
                     'unchanged_source_cache_sha256': evidence['input_hashes']['data/source_records.json'],
                     'output_hashes': {name: c.digest(data) for name, data in sorted(outputs.items())},
                     'source_requests': 0, 'provider_requests': 0}
