"""Read-only, zero-network/provider audit of the actual shared projection.

Source retrieval is a separate, explicitly bounded operation. This report
distinguishes the verified baseline, maintained inputs, and candidate projection.
Changed decisive fields require a source review; disappearance alone is not a
quality success. Reports contain bounded public citations, never full documents.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from scripts import extract_document_evidence as evidence, submission_schedule
from scripts.enrich_catalog import read_catalog, CATALOG_GLOBAL
from scripts.notice_structure_cache import StructureCache


DECISIVE = ('next_submission', 'next_submission_metadata', 'prerequisites', 'award_ceiling', 'award_ranges',
            'limited_submission', 'document_status_signals', 'cost_share_required')
FACT_KEYS = ('type', 'value', 'date', 'deadline_kind', 'time', 'timezone', 'subject',
             'stage', 'application_class', 'cycle', 'track', 'window_start', 'estimated', 'basis', 'cost_basis',
             'obligation', 'required', 'invitation_required', 'prerequisite', 'rolling', 'exclusions', 'funding_basis', 'estimate_kind', 'applicant_condition', 'date_qualifier')


def stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def fact_value(fact):
    # Existing canonical deadlines already default estimated to false. Preserve
    # the meaningful true qualifier without making its omitted default a new
    # source assertion on every unchanged prerequisite and money comparison.
    return {key: fact[key] for key in FACT_KEYS if fact.get(key) is not None
            and (key != 'estimated' or fact[key] is True)}


def facts(record):
    return (record.get('document_evidence') or {}).get('facts') or []


def receipt(fact):
    citation = fact.get('citation') or {}
    return {'fact_id': fact.get('id'), 'claim': fact_value(fact),
            'citation': {key: citation[key] for key in ('document_url', 'citation_url', 'location',
                'quote', 'sha256', 'document_sha256', 'page', 'section', 'extracted_at', 'structural_reference') if key in citation},
            **{key: fact[key] for key in ('track_citation', 'requirement_citation', 'prerequisite_citation',
                'clock_citation', 'cycle_citation', 'rolling_citation', 'date_qualifier_citation') if fact.get(key)}}


def decision_fields(record, as_of):
    selected = submission_schedule.next_submission(record, as_of)
    return {'next_submission': {key: selected[key] for key in ('date', 'access')},
        # A retained date can still have a corrected clock or submission scope.
        # These need their own source disposition, not a passing unchanged-date
        # result. Normalize absent/unspecified metadata, never clock aliases.
        'next_submission_metadata': {key: ((selected.get('event') or {}).get(key)
            if (selected.get('event') or {}).get(key) not in ('', 'unspecified') else None)
            for key in ('kind', 'time', 'timezone', 'application_class', 'cycle', 'track', 'date_qualifier')},
        'prerequisites': [fact_value({**event, 'type': event.get('kind')})
                         for event in submission_schedule.events(record)
                         if (event.get('kind') in submission_schedule.PRELIMINARY and event.get('required') is True)
                         or event.get('invitation_required') is True],
        'award_ceiling': record.get('award_ceiling'),
        'award_ranges': [fact_value(f) for f in facts(record) if f.get('type') == 'award_range'],
        'limited_submission': record.get('limited_submission'),
        'document_status_signals': record.get('document_status_signals') or [],
        'cost_share_required': record.get('cost_share_required')}


def owned_deadlines(record):
    """Remove reversible enrichment metadata before comparing source authority."""
    result = []
    for item in record.get('deadlines') or []:
        if item.get('evidence_id'):
            continue
        item = deepcopy(item)
        for key, original in item.pop('document_source_fields', {}).items():
            if original['present']:
                item[key] = original['value']
            else:
                item.pop(key, None)
        for key in ('document_evidence_id', 'document_confidence', 'citation'):
            item.pop(key, None)
        result.append(item)
    return result


def audit(catalog, cache, baseline, now, *, reviews=None):
    before = {str(r['opportunity_id']): r for r in catalog['opportunities']}
    verified = {str(r['opportunity_id']): r for r in baseline['opportunities']}
    working = deepcopy(cache)
    def no_fetch(*args, **kwargs):
        raise AssertionError('Read-only parsing audit attempted source retrieval')
    # The normal builder may quarantine obsolete facts. Its writes stay in an
    # ephemeral private directory; maintained caches and catalog are immutable.
    with tempfile.TemporaryDirectory(prefix='parsing-audit-') as directory:
        projected, working = evidence.enrich_document_evidence(deepcopy(catalog), working,
            max_documents=0, max_subtopic_documents=0, fetcher=no_fetch, request_delay=0,
            now=now, structure_cache=StructureCache(directory))
    counts = Counter(records=len(before))
    families = defaultdict(Counter)
    family_records = defaultdict(lambda: defaultdict(set))
    dispositions, ledger, violations = [], [], []
    reviews = reviews or {}
    for record in projected['opportunities']:
        identifier = str(record['opportunity_id'])
        original, previous = before[identifier], verified.get(identifier)
        entry = (cache.get('records') or {}).get(identifier, {})
        after_entry = (working.get('records') or {}).get(identifier, {})
        if entry.get('checked_at') != after_entry.get('checked_at'):
            violations.append({'opportunity_id': identifier, 'type': 'source_timestamp_changed_without_fetch'})
        if owned_deadlines(original) != owned_deadlines(record) or original.get('close_date') != record.get('close_date'):
            violations.append({'opportunity_id': identifier, 'type': 'structured_deadline_override'})
        else:
            counts['structured_deadlines_unchanged'] += len(owned_deadlines(record))
        for key in ('award_ceiling', 'award_floor', 'cost_share_required'):
            if original.get(key) != record.get(key):
                violations.append({'opportunity_id': identifier, 'type': 'structured_override', 'field': key})
        old_facts = facts(original)
        new_by_value = {stable(fact_value(f)): f for f in facts(record)}
        matched_new_values = set()
        seen = set()
        rows = []
        for fact in old_facts:
            key = stable(fact_value(fact))
            # Added typed qualifiers do not make an unchanged, source-proved
            # assertion disappear. Compare every qualifier previously asserted;
            # a changed date/stage/clock/obligation still requires disposition.
            after = new_by_value.get(key) or next((candidate for candidate in facts(record)
                if candidate.get('id') == fact.get('id')
                and all(candidate.get(k) == v for k, v in fact_value(fact).items())), None)
            if after:
                matched_new_values.add(stable(fact_value(after)))
            if key in seen:
                disposition = 'redundant_fact_consolidated'
            elif after:
                disposition = 'correct_fact_retained'
            else:
                # A short legacy quotation cannot establish full-source absence.
                disposition = 'unresolved_source_recovery' if after_entry.get('parser_pending') else 'changed_fact_requires_source_review'
            seen.add(key)
            rows.append({'disposition': disposition, 'before': receipt(fact),
                         'after': receipt(after) if after else None})
        for key, fact in new_by_value.items():
            if key not in matched_new_values:
                rows.append({'disposition': 'recovered_fact_requires_source_review', 'before': None, 'after': receipt(fact)})
        for row in rows:
            kind = ((row.get('after') or row['before'])['claim']).get('type', 'unknown')
            families[kind][row['disposition']] += 1
            family_records[kind][row['disposition']].add(identifier)
        dispositions.append({'opportunity_id': identifier, 'parser_pending': after_entry.get('parser_pending'), 'facts': rows})
        for comparison, other in [('maintained_inputs', original), ('verified_generation', previous)]:
            if other is None:
                continue
            old_fields, new_fields = decision_fields(other, now.date()), decision_fields(record, now.date())
            changes = {key: {'before': old_fields[key], 'after': new_fields[key]} for key in DECISIVE
                       if old_fields[key] != new_fields[key]}
            if not changes:
                continue
            review_key = hashlib.sha256(stable({'id': identifier, 'comparison': comparison, 'changes': changes}).encode()).hexdigest()
            review = reviews.get(review_key)
            if review and (not review.get('rationale') or not review.get('source_receipts') or
                           review.get('disposition') not in {'correct_fact_retained', 'corrected_wrong_fact', 'recovered_valid_fact',
                               'consolidated', 'source_amendment', 'retained_with_explicit_uncertainty'}):
                raise ValueError('Decisive field review needs a disposition, rationale, and source receipts')
            ledger.append({'opportunity_id': identifier, 'comparison': comparison, 'review_key': review_key,
                'changes': changes, 'review': review, 'source_evidence': [receipt(f) for f in facts(record)
                    if f.get('type') in {'deadline', 'submission_requirement', 'award_range', 'limited_submission',
                        'institutional_submission_policy', 'cost_share', 'status_signal'}]})
        old_next, new_next = submission_schedule.next_submission(original, now.date()), submission_schedule.next_submission(record, now.date())
        counts['next_submission_available_before'] += bool(old_next['date'])
        counts['next_submission_available_after'] += bool(new_next['date'])
        counts['lost_all_upcoming_dates'] += bool(old_next['date'] and not new_next['date'])
        counts['required_preliminary_records_after'] += any(d.get('required') is True and d.get('kind') in submission_schedule.PRELIMINARY
                                                         for d in submission_schedule.events(record))
    counts['decisive_changes_reviewed'] = sum(bool(row['review']) for row in ledger)
    counts['decisive_changes_unreviewed'] = sum(not row['review'] for row in ledger)
    return {'schema_version': 1, 'as_of': now.isoformat(), 'source_requests': 0, 'provider_requests': 0,
        'counts': dict(counts), 'fact_families': {kind: {'facts': dict(values), 'distinct_opportunities':
            {key: len(ids) for key, ids in family_records[kind].items()}} for kind, values in families.items()},
        'parser_counters': projected.get('diagnostics', {}).get('document_evidence', {}).get('parser_recovery'),
        'dispositions': dispositions, 'decisive_change_ledger': ledger, 'violations': violations,
        'publication_ready': not violations and all(row['review'] for row in ledger)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--catalog', type=Path, default=Path('data/opportunities.js'))
    parser.add_argument('--cache', type=Path, default=Path('data/document_evidence.json'))
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline_sha = subprocess.check_output(['git', 'rev-parse', args.baseline], text=True).strip()
    raw = subprocess.check_output(['git', 'show', f'{baseline_sha}:data/opportunities.js']).decode('utf-8')
    baseline = json.loads(raw.split(f'globalThis.{CATALOG_GLOBAL}=', 1)[1].strip().removesuffix(';'))
    now = datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cache_bytes = args.cache.read_bytes()
    report = audit(read_catalog(args.catalog), json.loads(cache_bytes), baseline, now,
        reviews=json.loads(args.reviews.read_text(encoding='utf-8')) if args.reviews else None)
    report['inputs'] = {'verified_baseline_sha': baseline_sha, 'catalog_sha256': hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
                        'cache_sha256': hashlib.sha256(cache_bytes).hexdigest(), 'cache_path': str(args.cache)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report['counts'], sort_keys=True))
    if report['violations']:
        raise SystemExit('Parsing projection invariant violations; inspect the report')


if __name__ == '__main__':
    main()
