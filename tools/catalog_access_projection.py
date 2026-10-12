"""Replay an exact retained catalog's access interpretation without recollection."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile

from tools import release_candidate as c

POLICY = 'evaluation/catalog_access_correction_20261012.json'
PARENT_ID = 'ac68ff0aef1e4aff66c06971c1500673a46bd0c7a40f2cc0cd71c9559ea402a8'
CHANGED = frozenset({'362990', '360458', '361213', '361606', '363454', '362575', '363874', '362574', '363734'})
ACCESS_FIELDS = frozenset({'deadlines', 'submission_requirements', 'next_submission'})
NASA_STAGE_FIELDS = {'has_preliminary_stage': True, 'preliminary_required': True,
                     'preliminary_stage_type': 'preproposal'}


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_access_projection_' + reason)


def value_hash(value):
    return c.digest(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())


def policy():
    evidence = c.read_json(c.ROOT / POLICY)
    require(evidence.get('schema_version') == 1 and evidence.get('candidate_id') == PARENT_ID
            and {row['opportunity_id'] for row in evidence['corrections']} == CHANGED
            and len(evidence['corrections']) == len(CHANGED), 'fixed_policy')
    return evidence


def corrected_catalog(before, evidence, audit_at):
    from scripts.submission_schedule import project
    require({row['opportunity_id'] for row in evidence['corrections']} == CHANGED
            and len(evidence['corrections']) == len(CHANGED), 'fixed_correction_set')
    audit = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    original = datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00'))
    require(audit.tzinfo is not None and original.tzinfo is not None and audit >= original, 'audit_clock')
    records = {str(row['opportunity_id']): row for row in before['opportunities']}
    require(len(records) == len(before['opportunities']) == evidence['record_count'], 'parent_membership')
    after = deepcopy(before)
    corrected = {str(row['opportunity_id']): row for row in after['opportunities']}
    proof = {}
    for item in evidence['corrections']:
        ident = item['opportunity_id']
        require(ident in records and value_hash(records[ident]) == item['record_sha256'], 'exact_record')
        old = records[ident]
        require(old['next_submission']['access'] == 'open', 'original_access')
        for citation in item['evidence']:
            require(citation['quote'] in str(old.get(citation['source_field']) or ''), 'evidence_quote')
        new = project(old, old['next_submission']['as_of'])
        changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)
                   or (key in old) != (key in new)}
        allowed = ACCESS_FIELDS | (NASA_STAGE_FIELDS.keys() if ident == '363734' else set())
        require(changed and changed <= allowed, 'only_access_fields')
        if ident == '363734':
            require(item.get('stage_fields') == NASA_STAGE_FIELDS
                    and all(new.get(key) == value for key, value in NASA_STAGE_FIELDS.items()), 'nasa_stage_fields')
        require(new['next_submission']['access'] == item['expected_access']
                and new['next_submission']['date'] == old['next_submission']['date']
                and new['next_submission']['as_of'] == old['next_submission']['as_of'], 'expected_access')
        # The interpreter may attach access evidence; it cannot alter an existing
        # source deadline, its clock, or its unrelated qualifications.
        for field in ('deadlines', 'submission_requirements'):
            prior = old.get(field) or []
            updated = new.get(field) or []
            additions = item.get('additional_submission_events', {}).get(field, [])
            require(len(updated) == len(prior) + len(additions)
                    and updated[len(prior):] == additions, 'source_event_inventory')
            for a, b in zip(prior, updated):
                require(all(key in b and b[key] == value for key, value in a.items()), 'source_event_values')
        corrected[ident].clear()
        corrected[ident].update(new)
        proof[ident] = {'before_sha256': value_hash(old), 'after_sha256': value_hash(new),
                        'changed_fields': sorted(changed), 'access': new['next_submission']['access']}
    require(all(row == records[str(row['opportunity_id'])] for row in after['opportunities']
                if str(row['opportunity_id']) not in CHANGED), 'unchanged_other_records')
    after.setdefault('diagnostics', {})['access_correction'] = {
        'audited_at': audit_at, 'opportunity_ids': sorted(CHANGED),
        'source_requests': 0, 'provider_requests': 0}
    after['catalog_audit_generated_at'] = audit_at
    return after, proof


def corrected_changes(prior, before, after, evidence, audit_at):
    from scripts import build_changes as changes
    original_events = prior['events']
    require(len({event['id'] for event in original_events}) == len(original_events), 'unique_event_ids')
    affected = {event['id']: value_hash(event) for event in original_events
                if str(event.get('opportunity_id')) in CHANGED}
    require(affected == evidence['affected_event_hashes'], 'exact_affected_events')
    actions = {item['event_id']: item for item in evidence['event_corrections']}
    require(len(actions) == len(evidence['event_corrections']) and set(actions) <= set(affected), 'event_actions')
    records = {str(row['opportunity_id']): row for row in after['opportunities']}
    result = []
    event_proof = {}
    for event in original_events:
        action = actions.get(event['id'])
        if action is None:
            result.append(deepcopy(event))
            continue
        ident = str(event['opportunity_id'])
        require(event['changed_at'] == before['generated_at']
                and records[ident]['next_submission']['access'] != 'open', 'current_event_access')
        if action['action'] == 'suppress_closing_soon':
            require(event['type'] == 'closing_soon', 'closing_event_type')
            event_proof[event['id']] = {'action': action['action'], 'before_sha256': value_hash(event)}
        elif action['action'] == 'correct_current_new_snapshot':
            require(event['type'] == 'new', 'new_event_type')
            updated = deepcopy(event)
            for field in ACCESS_FIELDS:
                if field in records[ident]:
                    updated['record'][field] = deepcopy(records[ident][field])
                else:
                    updated['record'].pop(field, None)
            result.append(updated)
            event_proof[event['id']] = {'action': action['action'], 'before_sha256': value_hash(event),
                                        'after_sha256': value_hash(updated)}
        else:
            require(False, 'unknown_event_action')
    for ident in sorted(CHANGED):
        row = records[ident]
        qualification = ('an invitation is required' if row['next_submission']['access'] == 'invitation_required'
                         else 'the required preliminary submission deadline has passed')
        detail = ('Submission access interpretation corrected: ' + qualification + '. '
                  'The official source deadline and source snapshot dates are unchanged.')
        event = {'id': changes._event_id('source_correction', row, audit_at, detail),
                 'type': 'source_correction', 'label': changes.EVENT_LABELS['source_correction'],
                 'changed_at': audit_at, 'opportunity_id': ident, 'detail': detail,
                 'record': changes._snapshot(row)}
        require(event['id'] not in {old['id'] for old in original_events}, 'new_correction_event')
        result.append(event)
        event_proof[event['id']] = {'action': 'append_interpretation_correction',
                                    'after_sha256': value_hash(event)}
    result.sort(key=lambda event: (event.get('changed_at', ''), event['id']), reverse=True)
    require(all(next(item for item in result if item['id'] == event['id']) == event
                for event in original_events if event['id'] not in actions), 'unchanged_history')
    # Feed generation is an audit action; each retained historical event keeps its
    # own original timestamp. No new source observation or amendment is invented.
    payload = {**prior, 'generated_at': audit_at, 'events': result}
    return payload, event_proof


def projection(parent_root, audit_at):
    from scripts.sources.merge import load_catalog
    from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.build_feeds import build_feeds
    from scripts.build_changes import build_atom
    parent = Path(parent_root)
    evidence = policy()
    manifest = parent.parent / 'candidate.json'
    require(c.digest(manifest.read_bytes()) == evidence['candidate_manifest_sha256']
            and c.read_json(manifest)['candidate_id'] == evidence['candidate_id'], 'exact_parent')
    require(all(c.digest((parent / name).read_bytes()) == expected
                for name, expected in evidence['input_hashes'].items()), 'exact_inputs')
    before = load_catalog(parent / 'data/opportunities.js')
    after, record_proof = corrected_catalog(before, evidence, audit_at)
    cache = c.read_json(parent / 'data/source_records.json')
    require(not any(str(row.get('opportunity_id')) in CHANGED for source in cache['sources'].values()
                    for row in source.get('records', [])), 'unexpected_cached_record')
    changes, event_proof = corrected_changes(c.read_json(parent / 'feeds/changes.json'),
                                             before, after, evidence, audit_at)
    outputs = {'data/opportunities.js': catalog_javascript_bytes(after),
               'data/catalog-metadata.js': catalog_metadata_javascript_bytes(after),
               'feeds/changes.json': (json.dumps(changes, ensure_ascii=False, indent=2) + '\n').encode(),
               'feeds/changes.xml': build_atom(changes['events'], datetime.fromisoformat(audit_at.replace('Z', '+00:00'))).encode()}
    with tempfile.TemporaryDirectory(prefix='catalog-access-feeds-') as temporary:
        root = Path(temporary)
        feeds = root / 'feeds'
        feeds.mkdir()
        (feeds / 'changes.xml').write_bytes(outputs['feeds/changes.xml'])
        build_feeds(after, feeds, as_of=datetime.fromisoformat(before['generated_at'].replace('Z', '+00:00')).date())
        outputs.update({path.relative_to(root).as_posix(): path.read_text(encoding='utf8').encode()
                        for path in feeds.rglob('*') if path.is_file()})
    return outputs, {'policy_sha256': c.digest((c.ROOT / POLICY).read_bytes()),
                     'parent_candidate_id': evidence['candidate_id'],
                     'parent_manifest_sha256': evidence['candidate_manifest_sha256'],
                     'changed_ids': sorted(CHANGED), 'records': record_proof, 'events': event_proof,
                     'retained_record_count': len(after['opportunities']),
                     'original_generated_at': before['generated_at'], 'audited_at': audit_at,
                     'unchanged_record_hashes': {str(row['opportunity_id']): value_hash(row)
                         for row in before['opportunities'] if str(row['opportunity_id']) not in CHANGED},
                     'unchanged_source_cache_sha256': evidence['input_hashes']['data/source_records.json'],
                     'output_hashes': {name: c.digest(data) for name, data in sorted(outputs.items())},
                     'source_requests': 0, 'provider_requests': 0}
