"""Read-only, network-free deadline projection audit of maintained source receipts.

Run as ``python -m tools.audit_deadline_corpus --baseline <verified-sha> --output <report>``.
The normal shared enrichment entrypoint is used with a zero retrieval budget.
Neither catalog nor cache inputs are written. Quotes are existing receipts, not
new source verification. The report records withdrawals as changes, never as
silent coverage successes.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from scripts.enrich_catalog import read_catalog, CATALOG_GLOBAL
from scripts.extract_document_evidence import enrich_document_evidence, qualify_deadline_sequence


def source_deadlines(record):
    return [{k: v for k, v in deadline.items()
             if k not in {'document_evidence_id', 'document_confidence', 'citation'}}
            for deadline in record.get('deadlines', []) if not deadline.get('evidence_id')]


def signature(deadline):
    return (deadline.get('kind'), deadline.get('date'), deadline.get('time'), deadline.get('timezone'))


def audit(catalog, cache, baseline, now):
    current = {str(r['opportunity_id']): r for r in catalog['opportunities']}
    prior = {str(r['opportunity_id']): r for r in baseline['opportunities']}
    working = deepcopy(cache)

    def no_fetch(*args, **kwargs):
        raise AssertionError('Corpus audit must not retrieve sources')

    projected, _ = enrich_document_evidence(deepcopy(catalog), working, max_documents=0,
        max_subtopic_documents=0, request_delay=0, fetcher=no_fetch, now=now)
    counts = Counter(records=len(current))
    accepted, withheld, changes, violations = [], [], [], []
    for record in projected['opportunities']:
        identifier = str(record['opportunity_id'])
        original = current[identifier]
        source_before, source_after = source_deadlines(original), source_deadlines(record)
        counts['source_provided_deadlines_unchanged'] += len(source_before) if source_before == source_after else 0
        counts['official_structured_deadlines_unchanged'] += sum(d.get('confidence') == 'official_structured'
            for d in source_before) if source_before == source_after else 0
        if source_before != source_after or record.get('close_date') != original.get('close_date'):
            violations.append({'opportunity_id': identifier, 'type': 'structured_override'})
        entry = (cache.get('records') or {}).get(identifier, {})
        after_entry = (working.get('records') or {}).get(identifier, {})
        facts = ((record.get('document_evidence') or {}).get('facts') or [])
        deadline_facts = [f for f in facts if f.get('type') == 'deadline']
        surviving = {f['id']: f for f in deadline_facts}
        for fact in [f for f in entry.get('facts', []) if f.get('type') == 'deadline']:
            row = {'opportunity_id': identifier, 'fact_id': fact['id'], 'date': fact.get('date'),
                   'kind': fact.get('deadline_kind'), 'time': fact.get('time'), 'timezone': fact.get('timezone'),
                   'source_url': (fact.get('citation') or {}).get('url') or (entry.get('document') or {}).get('url'),
                   'quote': (fact.get('citation') or {}).get('quote'),
                   'checked_at': entry.get('checked_at'), 'document_sha256': (entry.get('document') or {}).get('sha256')}
            if fact['id'] in surviving:
                row['decision'] = 'existing_citation_proves_local_field_and_cached_components'
                accepted.append(row)
            else:
                row['decision'] = ('source_requires_revalidation' if after_entry.get('status') != 'current'
                                   else 'ambiguous_or_unsupported_cached_field_or_component')
                withheld.append(row)
        if entry and (entry.get('checked_at') != after_entry.get('checked_at') or
                      entry.get('document') != after_entry.get('document')):
            violations.append({'opportunity_id': identifier, 'type': 'source_receipt_changed_without_fetch'})
        if qualify_deadline_sequence(deadline_facts) != deadline_facts:
            violations.append({'opportunity_id': identifier, 'type': 'impossible_stage_order'})
        for fact in deadline_facts:
            # Historical source dates are reported for inspection, never assumed
            # wrong solely because they precede this audit or a source check.
            if fact.get('date', '9999') < now.date().isoformat():
                counts['accepted_historical_dates_for_source_inspection'] += 1
        old = prior.get(identifier)
        if old is None:
            counts['records_added_since_verified_generation'] += 1
            continue
        before_set = {signature(d) for d in old.get('deadlines', [])}
        after_set = {signature(d) for d in record.get('deadlines', [])}
        if before_set != after_set:
            dates_changed = {(s[0], s[1]) for s in before_set} != {(s[0], s[1]) for s in after_set}
            common_dates = {(s[0], s[1]) for s in before_set} & {(s[0], s[1]) for s in after_set}
            time_changed = any({s[2:] for s in before_set if s[:2] == key} !=
                               {s[2:] for s in after_set if s[:2] == key} for key in common_dates)
            counts['records_with_date_set_changes_vs_verified'] += dates_changed
            counts['records_with_time_zone_changes_on_retained_dates_vs_verified'] += time_changed
            changes.append({'opportunity_id': identifier, 'before': sorted(before_set, key=str),
                            'after': sorted(after_set, key=str),
                            'structured_inputs_changed_since_verified': source_deadlines(old) != source_before,
                            'withdrawn_evidence': [r for r in withheld if r['opportunity_id'] == identifier],
                            'accepted_evidence': [r for r in accepted if r['opportunity_id'] == identifier]})
    counts.update(narrative_deadlines_accepted=len(accepted), narrative_deadlines_withheld=len(withheld),
                  structured_overrides=sum(v['type'] == 'structured_override' for v in violations),
                  impossible_stage_order=sum(v['type'] == 'impossible_stage_order' for v in violations),
                  source_receipt_mutations=sum(v['type'] == 'source_receipt_changed_without_fetch' for v in violations))
    return {'audited_at': now.isoformat(), 'network_requests': 0, 'counts': dict(counts),
            'accepted': accepted, 'withheld': withheld, 'changes_vs_verified': changes, 'violations': violations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = subprocess.check_output(['git', 'show', f'{args.baseline}:data/opportunities.js']).decode('utf-8')
    baseline = json.loads(raw.split(f'globalThis.{CATALOG_GLOBAL}=', 1)[1].strip().removesuffix(';'))
    report = audit(read_catalog('data/opportunities.js'),
        json.loads(Path('data/document_evidence.json').read_text(encoding='utf-8')),
        baseline, datetime.now(timezone.utc))
    report['baseline_sha'] = subprocess.check_output(['git', 'rev-parse', args.baseline], text=True).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['counts'], indent=2))
    if report['violations']:
        raise SystemExit('Deadline corpus invariant violations: inspect report')


if __name__ == '__main__':
    main()
