"""Developer-only coverage evidence from current safe generated records."""
from collections import Counter
import argparse
import json
import os
from pathlib import Path

from scripts.faculty_match import _load_catalog
from tools import release_candidate as c


def report(root, previous=None):
    root = Path(root)
    records = _load_catalog(root / 'data/opportunities.js')
    cache = c.read_json(root / 'data/document_evidence.json')['records']
    teams = c.read_json(root / 'evaluation/opportunity_team_generation.json')
    source = Counter()
    affected, fields = set(), Counter()
    states = {}
    for record in records:
        key = str(record['opportunity_id'])
        entry = cache.get(key, {})
        state = record.get('document_evidence_status', 'unknown')
        states[key] = state
        source['document_status:' + state] += 1
        pending = entry.get('parser_pending') or {}
        if pending:
            source['parser_pending'] += 1
            source['parser_pending_reason:' + str(pending.get('reason', 'unknown'))] += 1
            affected.add(key)
            for name in pending.get('changed_families', []):
                fields[name] += 1
            for kind in ('withheld_count', 'retained_count', 'corrected_count'):
                if type(pending.get(kind)) is int:
                    source['retained_migration_receipt_fields:' + kind] += pending[kind]
        if entry.get('structure_identity'):
            source['retained_structure_identity'] += 1
        if state in ('failed', 'source_changed', 'pending'):
            affected.add(key)
    prior_states = (previous or {}).get('source_states')
    transitions = Counter(f'{prior_states.get(k, "new")}->{v}' for k, v in states.items()
                          if prior_states and prior_states.get(k) != v)
    return {'version': 1, 'catalog_records': len(records), 'source_counts': dict(source),
        'unique_affected_records': len(affected), 'overlapping_field_categories': dict(fields),
        'source_states': states, 'source_transitions': dict(transitions) if prior_states is not None else None,
        'safe_reparseable_from_available_structure': None,
        'structure_availability_reason': 'Public structure identity does not prove a private performance cache is still available; team-only work does not restore private notices',
        'oldest_pending_age_days': None, 'pending_age_reason': 'First-pending timestamps are not retained by the existing evidence contract',
        'unsupported_source_count': None, 'unsupported_source_reason': 'No complete explicit unsupported-source classification is retained',
        'teams': {key: teams.get(key) for key in ('mode', 'queue_counts', 'coverage_before', 'coverage_after',
             'source_invalidations', 'assessment_invalidations', 'assessed_scopes', 'outcomes', 'provider_requests_by_surface', 'llm_usage')},
        'generated_at': c.timestamp()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-before', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    output = c.ROOT / 'evaluation/release_coverage.json'
    if args.snapshot_before:
        c.write_json(args.snapshot_before, report(c.ROOT))
        return
    previous_path = args.previous or output
    previous = c.read_json(previous_path) if previous_path.exists() else None
    value = report(c.ROOT, previous)
    value['source_count_deltas'] = ({key: value['source_counts'].get(key, 0) - previous['source_counts'].get(key, 0)
        for key in sorted(set(value['source_counts']) | set(previous['source_counts']))} if previous else None)
    c.write_json(output, value)
    summary = {key: v for key, v in value.items() if key != 'source_states'}
    print(json.dumps(summary))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('\n### Current source and team coverage\n\n```json\n' + json.dumps(summary, indent=2) + '\n```\n')


if __name__ == '__main__':
    main()
