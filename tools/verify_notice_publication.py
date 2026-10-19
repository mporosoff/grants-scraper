"""Read-only publication boundary for interpreted notice data.

A code merge may precede its coordinated generated package. Compare the
committed public projection with the normal, zero-request writer before any
Pages/search publication. This does not regenerate data or authorize a merge.
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import tempfile

from scripts import extract_document_evidence as evidence, notice_schedule, subtopic_structured
from scripts.build_catalog import compact_catalog_payload
from scripts.enrich_catalog import read_catalog
from scripts.notice_structure_cache import StructureCache

PUBLIC_FIELDS = ('document_evidence_status', 'document_evidence', 'document_search_text',
    'topic_areas', 'document_program_areas',
    'deadlines', 'submission_requirements', 'document_status_signals',
    'limited_submission', 'limited_submission_review', 'has_preliminary_stage',
    'preliminary_stage_type', 'preliminary_required', 'next_submission')


VALIDATOR_VERSION = 'notice-publication-6'


def bounded_public_value(value, limit=2048):
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(serialized) <= limit:
        return value
    return {'preview': serialized[:limit], 'truncated': True,
            'sha256': hashlib.sha256(serialized.encode()).hexdigest(), 'characters': len(serialized)}


def comparable_public_field(record, field):
    value = record.get(field)
    # Topic facets are an unordered tag collection. Preserve membership and
    # duplicate/type differences without rewriting unrelated published order.
    if field == 'topic_areas' and isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(value)
    return value


def administrative_close_contract(record, as_of):
    """Check the source explanation independently of document replay.

    A generic closing field cannot override an explicitly earlier, owned actual
    application field. Do not classify an ordinary portal window, a same-day
    date, or a date from another document/application scope this way.
    """
    from scripts.submission_schedule import events, next_submission
    from scripts.currentness import record_is_current

    full = {'application', 'full_application', 'estimated_application', 'proposal'}

    def scope(value):
        return (value.get('application_class') or 'unspecified', value.get('cycle') or None,
                value.get('track') or None)

    document = (record.get('document_evidence') or {}).get('document') or {}
    # The current public document owns its resolved URL; the requested Grants
    # URL may have redirected to its attested attachment-serving hostname.
    if (record.get('document_evidence_status') != 'current' or not document.get('url')
            or not re.fullmatch('[a-f0-9]{64}', str(document.get('sha256') or ''))):
        return []
    facts = (record.get('document_evidence') or {}).get('facts') or []

    def owned(fact):
        citation = fact.get('citation') or {}
        field = citation.get('structural_reference') or {}
        return (fact.get('type') == 'deadline' and fact.get('field_authority') == 'official_notice_field'
                and citation.get('document_url') == document['url']
                and citation.get('sha256') == document['sha256']
                and field.get('field_id') and field.get('field_label'))

    structured_rows = [row for row in record.get('deadlines') or []
                       if row.get('source_field') == 'CloseDate' and row.get('confidence') == 'official_structured'
                       and not row.get('evidence_id') and row.get('source_url')
                       and row.get('kind') in {'application', 'submission'}
                       and row.get('date') == record.get('close_date')
                       and notice_schedule.explicit_submission_window_end(evidence, row.get('note') or '')]
    findings = []
    for structured in structured_rows:
        if sum(scope(row) == scope(structured) for row in structured_rows) != 1:
            continue
        note = structured.get('note') or ''
        window = notice_schedule.explicit_submission_window_end(evidence, note)
        if not window or window[0] != structured.get('date'):
            continue
        end, actual = window
        proofs = [fact for fact in facts if owned(fact)
                  and fact.get('deadline_kind') in {'application', 'full_application', 'proposal'}
                  and fact.get('date') == actual and scope(fact) == scope(structured)
                  and fact.get('estimated') is not True and fact.get('date_qualifier') != 'administrative'
                  and not fact.get('conflicts') and (fact.get('reconciliation') or {}).get('status') != 'conflict']
        if len(proofs) != 1 or not proofs[0].get('id'):
            continue
        proof = {'basis': 'explicit_closing_date_explanation', 'source_field': 'CloseDate',
                 'source_url': structured.get('source_url'), 'quote': note,
                 'actual_application_date': actual, 'application_evidence_id': proofs[0]['id']}
        expected = deepcopy(record)
        fields = []
        native_end = {fact['id'] for fact in facts if owned(fact) and fact.get('id')
                      and fact.get('date') == end and scope(fact) == scope(structured)
                      and fact.get('deadline_kind') in {'application', 'submission'}
                      and ' '.join(fact['citation']['structural_reference']['field_label'].split()).rstrip(':').casefold()
                          == 'closing date for applications'}

        def administrative_event(row):
            return (row.get('date') == end and scope(row) == scope(structured)
                    and ((row.get('source_field') == 'CloseDate' and row.get('confidence') == 'official_structured')
                         or (row.get('evidence_id') or row.get('document_evidence_id')) in native_end
                         and row.get('source_url') == document['url']))

        for field in ('deadlines', 'submission_requirements'):
            for row in expected.get(field) or []:
                if administrative_event(row) and row.get('kind') in full | {'submission'}:
                    row.update(kind='submission', stage='submission', date_qualifier='administrative',
                               date_qualifier_citation=deepcopy(proof))
            if expected.get(field) != record.get(field):
                fields.append(field)
        expected_facts = (expected.get('document_evidence') or {}).get('facts') or []
        for fact in expected_facts:
            if fact.get('id') in native_end:
                fact.update(deadline_kind='submission', stage='submission', label='Administrative close',
                            date_qualifier='administrative', date_qualifier_citation=deepcopy(proof))
        if expected.get('document_evidence') != record.get('document_evidence'):
            fields.append('document_evidence')

        # This expected selection deliberately removes the processing date and
        # its scalar fallback before consulting the shared submission selector.
        actionable = deepcopy(expected)
        for field in ('deadlines', 'submission_requirements'):
            actionable[field] = [row for row in actionable.get(field) or []
                                 if row.get('date_qualifier') != 'administrative']
        actionable['close_date'] = None
        selected = next_submission(actionable, as_of)
        declared = record.get('next_submission') or {}
        computed = next_submission(record, as_of)
        if any(selected.get('date') == end and administrative_event(selected.get('event') or {})
               for selected in (declared, computed)):
            expected['next_submission'] = selected
            fields.append('next_submission')
        if any(administrative_event(row) for row in events(record)):
            fields.append('submission_events')
        # Prove closure from the independently stripped processing date, rather
        # than trusting the record's cached next_submission or refinement code.
        # Another application's future/rolling scope keeps the overall call
        # eligible for currentness; this check is not a new-applicant filter.
        classes = {'new'} | {row['application_class'] for row in events(actionable)
                            if row.get('application_class') not in (None, '', 'unspecified')}
        definitely_closed = (not record.get('rolling') and all(
            next_submission(actionable, as_of, application_class=value)['access'] == 'closed'
            for value in classes))
        current, current_reason = record_is_current(record, date.fromisoformat(as_of))
        if definitely_closed and current:
            fields.append('currentness')
            expected['currentness'] = {'current': False, 'submission_access': 'closed',
                'actual_application_date': actual, 'source_close_date': end}
        if fields:
            findings.append({'opportunity_id': str(record['opportunity_id']),
                'reason': 'administrative_close_is_not_an_application_deadline', 'fields': fields,
                'differences': [{'field': field,
                    'before': bounded_public_value(events(record) if field == 'submission_events'
                        else {'current': current, 'reason': current_reason, 'source_close_date': end}
                        if field == 'currentness' else record.get(field)),
                    'after': bounded_public_value(events(actionable) if field == 'submission_events' else expected.get(field))}
                    for field in fields]})
    return findings


def retained_retrieval_failure(before, after, catalog, cache, stamp):
    """A zero-request replay cannot repeat an attested generation-time fetch failure.

    Source invalidation runs before acquisition. A failed acquisition keeps its
    old cache signature (never relabel old evidence as the new source), so replay
    stops at source_changed. Both projections must still withhold all evidence.
    """
    if (before.get('document_evidence_status') != 'failed'
            or after.get('document_evidence_status') != 'source_changed'
            or any(row.get(key) is not None for row in (before, after)
                   for key in ('document_evidence', 'document_search_text'))):
        return False
    identifier = str(before['opportunity_id'])
    entry = (cache.get('records') or {}).get(identifier) or {}
    source = evidence.source_for_record(before)
    if (not source or entry.get('status') != 'failed' or not entry.get('last_error')
            or entry.get('last_attempt_at') != stamp):
        return False
    failures = ((catalog.get('diagnostics') or {}).get('document_evidence') or {}).get('failures') or []
    return any(str(failure.get('opportunity_id')) == identifier
               and failure.get('url') == source['url']
               and failure.get('error') == entry['last_error'] for failure in failures)


def verify(catalog, cache, children=None, *, candidate_id='committed-working-copy'):
    from scripts.document_work_budget import require_document_publication
    require_document_publication(catalog)
    stamp = catalog.get('document_evidence_generated_at') or catalog.get('generated_at')
    if not stamp:
        raise ValueError('Missing generated notice projection timestamp')
    now = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('Notice projection timestamp must include its timezone')
    def no_fetch(*_):
        raise AssertionError('Publication verification attempted source retrieval')
    with tempfile.TemporaryDirectory(prefix='notice-publication-') as directory:
        projected, _ = evidence.enrich_document_evidence(deepcopy(catalog), deepcopy(cache),
            now=now, max_documents=0, max_subtopic_documents=0, request_delay=0,
            fetcher=no_fetch, structure_cache=StructureCache(directory))
    # The catalog writer removes duplicate citations only when their exact
    # evidence reference resolves in the same record. Compare that actual
    # published representation, not the richer in-memory intermediate.
    def published_records(value):
        # Source positions may be tuples internally and JSON arrays on disk.
        return json.loads(json.dumps(compact_catalog_payload(value), default=str))['opportunities']
    published = published_records(catalog)
    rebuilt = published_records(projected)
    if [row['opportunity_id'] for row in published] != [row['opportunity_id'] for row in rebuilt]:
        raise ValueError('Notice projection changed canonical membership or order')
    changes, replay_observations = [], []
    for before, after in zip(published, rebuilt):
        fields = [key for key in PUBLIC_FIELDS
                  if comparable_public_field(before, key) != comparable_public_field(after, key)]
        if retained_retrieval_failure(before, after, catalog, cache, stamp):
            fields.remove('document_evidence_status')
            replay_observations.append({'opportunity_id': str(before['opportunity_id']),
                'field': 'document_evidence_status', 'before': before['document_evidence_status'],
                'after': after['document_evidence_status'],
                'reason': 'generation_retrieval_failure_not_replayed', 'generation_attempt_at': stamp})
        if fields:
            changes.append({'opportunity_id': str(before['opportunity_id']), 'fields': fields,
                'differences': [{'field': key, 'before': bounded_public_value(before.get(key)),
                                 'after': bounded_public_value(after.get(key))} for key in fields]})
        changes.extend(administrative_close_contract(before, now.date().isoformat()))
    entries = {**(cache.get('subtopic_only') or {}), **(cache.get('records') or {})}
    for identifier, child_entry in (children or {}).get('records', {}).items():
        entry = entries.get(identifier) or {}
        hgeo = (entry.get('subtopic_method') == 'hgeo_declared_topics'
                or child_entry.get('segmentation_method') == 'hgeo_declared_topics'
                or any(child.get('segmentation_method') == 'hgeo_declared_topics' for child in child_entry.get('subtopics') or []))
        if hgeo and child_entry.get('subtopics') and (entry.get('subtopic_structured') or {}).get('body_parser_version') != subtopic_structured.HGEO_BODY_VERSION:
            changes.append({'opportunity_id': identifier, 'fields': ['scientific_topic_bodies'],
                'differences': [{'field': 'scientific_topic_bodies',
                    'before': (entry.get('subtopic_structured') or {}).get('body_parser_version'),
                    'after': subtopic_structured.HGEO_BODY_VERSION}]})
    return {'schema_version': 2, 'candidate_id': candidate_id,
            'validator': 'notice-projection-idempotence', 'validator_version': VALIDATOR_VERSION,
            'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source_requests': 0, 'provider_requests': 0,
            'publication_ready': not changes, 'changed_records': len({row['opportunity_id'] for row in changes}),
            'changes': changes, 'replay_observations': replay_observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path('data/opportunities.js'))
    parser.add_argument('--cache', type=Path, default=Path('data/document_evidence.json'))
    parser.add_argument('--subtopics', type=Path, default=Path('data/subtopics.js'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--candidate-id', default='committed-working-copy')
    parser.add_argument('--detect', action='store_true', help='Report whether a coordinated manual checkpoint is needed; never authorize publication')
    args = parser.parse_args()
    from scripts.subtopic_records import read_cache
    report = verify(read_catalog(args.catalog), json.loads(args.cache.read_bytes()), read_cache(args.subtopics), candidate_id=args.candidate_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    if not report['publication_ready'] and not args.detect:
        raise SystemExit('Notice projection needs a coordinated generated package; retain the current release')


if __name__ == '__main__':
    main()
