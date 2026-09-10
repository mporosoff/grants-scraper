"""Offline aggregate closeout; never publishes per-item verdicts or provider text."""
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

DOC = Path('docs/team-recommender')
OUT = Path('outputs/team-recommender-c2')
RUN = '34472949357'


def read(p):
    return json.loads(p.read_bytes())


def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def grouped_interval(values, group_map, seed=20260910):
    """Cluster bootstrap of scope means; missing scopes are never imputed."""
    groups = defaultdict(list)
    for sid, value in values.items():
        groups[group_map.get(sid, sid)].append(value)
    if not groups:
        return None
    blocks = list(groups.values())
    rng = random.Random(seed)
    samples = []
    for _ in range(2000):
        selected = [v for _ in blocks for v in rng.choice(blocks)]
        samples.append(sum(selected) / len(selected))
    samples.sort()
    return {'mean': sum(values.values()) / len(values), 'scopes': len(values),
            'source_groups': len(groups), 'percentile_95': [samples[49], samples[1949]],
            'replicates': 2000, 'seed': seed,
            'limits': 'Conditional on observed selected machine judgments; excludes missing scopes. Not independent validation.'}


def main():
    private = OUT / 'analysis-private'
    private.mkdir(exist_ok=True)
    retained = []
    # Preserve exact originals before removing untracked copies from release documents.
    for pattern in ['c2-judge-results-*.json', 'c2-learning-*.json', 'c2-component-groups-*.json']:
        for p in sorted((DOC / 'receipts').glob(pattern)):
            dest = private / p.name
            if dest.exists() and dest.read_bytes() != p.read_bytes():
                raise RuntimeError('Refusing to overwrite retained analysis: ' + str(dest))
            dest.write_bytes(p.read_bytes())
            p.unlink()
    for p in sorted(private.glob('c2-*.json')):
        retained.append({'name': p.name, 'sha256': digest(p), 'bytes': p.stat().st_size,
                         'storage': 'local private analysis and trusted cloud receipts; not public release inputs'})
    judge = read(private / f'c2-judge-results-{RUN}.json')
    learning = read(private / f'c2-learning-{RUN}.json')
    components = read(private / f'c2-component-groups-{RUN}.json')
    mapping = read(OUT / 'judge-item-map-v3.json')
    outputs = read(OUT / 'development-corrected-v2.json')
    groups = read(DOC / 'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map']
    labels = judge['labels']
    summaries, means = [], {}
    for candidate in judge['candidates']:
        cid = candidate['candidate']
        result = {k: candidate[k] for k in ['candidate', 'scientific_reservations', 'prepared', 'unprepared', 'groups', 'no_group_prepared', 'arms']}
        numerical = next(c for c in outputs['results'] if c['id'] == cid)
        for arm in ['whole-call', 'coverage']:
            rows = defaultdict(list)
            for occurrence in mapping['occurrences']:
                if occurrence['kind'] == 'top5-individual' and occurrence.get('candidate') == cid and occurrence.get('arm') == arm:
                    rows[occurrence['scope_id']].append(labels.get(occurrence['key'], {}).get('label'))
            observed = {sid: sum(v in ['strong', 'plausible'] for v in values) / sum(v is not None for v in values)
                        for sid, values in rows.items() if any(v is not None for v in values)}
            means[cid, arm] = observed
            low = {sid: sum(v in ['strong', 'plausible'] for v in values) / len(values) for sid, values in rows.items()}
            high = {sid: sum(v in ['strong', 'plausible', None] for v in values) / len(values) for sid, values in rows.items()}
            counts = [len(s['A5' if arm == 'whole-call' else 'B5']) for s in numerical['scopes'] if s['status'] != 'unprepared']
            result['arms'][arm].update({'macro_observed': grouped_interval(observed, groups),
                                       'macro_missing_label_bounds': [sum(low.values())/len(low), sum(high.values())/len(high)] if low else None,
                                       'empty_lists': counts.count(0), 'short_nonempty_lists': sum(0 < n < 5 for n in counts),
                                       'nonempty_lists': sum(n > 0 for n in counts)})
        a, b = means[cid, 'whole-call'], means[cid, 'coverage']
        result['paired_macro_B_minus_A'] = grouped_interval({sid: b[sid]-a[sid] for sid in set(a)&set(b)}, groups)
        result['matched_AB'] = candidate['matched-AB']['interpreted_with_order_audit']
        result['MMR_comparison'] = candidate['MMR-comparison']['interpreted_with_order_audit']
        for mode in ['B', 'MMR']:
            occurrences = [o for o in mapping['occurrences'] if o['kind'] == 'automatic-member' and o.get('candidate') == cid and o.get('mode') == mode]
            grades = Counter(labels.get(o['key'], {}).get('label', 'missing') for o in occurrences)
            result['automatic_member_' + mode] = {'occurrences': len(occurrences), 'unique_people': len({o['person_id'] for o in occurrences}),
                                                  'labels': dict(grades), 'limits': 'Repeated option occurrences from one scientific source; not independent trials.'}
        summaries.append(result)
    pairs = {tuple(sorted([s['original_key'], s['swapped_key']])): s['status'] for s in judge['order_swap']}
    ledger_path = OUT / f'cloud-{RUN}/ledger.json'
    ledger = read(ledger_path)
    requests = ledger['requests']
    assert ledger['logical_id'] == 'on-demand-team-offline-v2-20260909'
    assert len({r['key'] for r in requests}) == len(requests)
    assert all(r['attempt'] == 1 and r['status'] in ['valid', 'failed'] for r in requests)
    by_provider = []
    for provider in ['voyage', 'anthropic']:
        rows = [r for r in requests if r['provider'] == provider]
        by_provider.append({'provider': provider, 'requests': len(rows), 'statuses': dict(Counter(r['status'] for r in rows)),
                            'input_tokens': sum(r['usage'].get('input_tokens', r['usage'].get('total_tokens', 0)) for r in rows),
                            'output_tokens': sum(r['usage'].get('output_tokens', 0) for r in rows),
                            'actual_microusd': sum(r['charged_microusd'] for r in rows)})
    total = sum(r['charged_microusd'] for r in requests)
    assert total <= 6000000 and 10000000-total >= 4000000
    budget = {'authorization_id': ledger['logical_id'], 'authoritative_run': int(RUN), 'checkpoint_sha256': digest(OUT/f'cloud-{RUN}/checkpoint.json'),
              'ledger_sha256': digest(ledger_path), 'local_copy_role': 'read-only mirror; never a second dispatch owner',
              'prior_stage1_spend_microusd': 0, 'stage2_actual_microusd': total, 'cumulative_actual_microusd': total,
              'outstanding_reserved_microusd': 0, 'unknown_dispatches': 0, 'remaining_total_microusd': 10000000-total,
              'stage2_ceiling_microusd': 6000000, 'later_stages_minimum_preserved_microusd': 4000000,
              'providers': by_provider, 'total_requests': len(requests), 'duplicate_keys': 0, 'attempts_above_one': 0,
              'exact_cache_hit_events': sum(e['kind'] == 'exact_cache_hit' for e in ledger['events']),
              'failed_requests_are_terminal_not_replayed': 13,
              'historical_other_task_spend_usd': 11.971342, 'historical_other_task_requests': 543, 'historical_spend_budget_credit': 0}
    (DOC/'budget-ledger.json').write_bytes(ledger_path.read_bytes())
    learning_public = {k:v for k,v in learning.items() if k not in ['models','fold_assignment']}
    learning_public['models'] = [{k:v for k,v in model.items() if k not in ['oof_predictions','coefficients_by_fold','fold_models']} for model in learning['models']]
    learning_public['retained'] = False
    learning_public['decision'] = 'Machine-label Brier improves but ranking does not; new group usefulness mostly unjudged and unrelated known members occur. Complexity not earned.'
    component_public = {k:v for k,v in components.items() if k != 'results'}
    component_public['results'] = [{k:v for k,v in r.items() if k != 'rows'} for r in components['results']]
    report = {'run': int(RUN), 'original_unique_items': 408, 'original_occurrences': 1665,
              'valid_unique_items': len(labels), 'paid_failed_unresolved_items': len(judge['new_failed_items'])+len(judge['prior_failed_items']),
              'optional_source_only_omitted_items': judge['omitted_optional_source_items'], 'missing_original_source_items': 3,
              'unattempted_remaining_eligible_requests': len(judge['unattempted']), 'labels_by_task': judge['labels_by_task'],
              'candidates': summaries, 'order_swap_occurrences': len(judge['order_swap']), 'distinct_order_pairs': len(pairs),
              'order_pair_results': dict(Counter(pairs.values())), 'learning': learning_public, 'learned_groups': component_public,
              'budget': budget, 'retained_private_analyses': retained, 'human_requested_at_delivery': 20, 'human_returned': 0,
              'final_human_reserved': 20, 'individual_human_packet_verdicts_in_this_receipt': False,
              'profile_evidence_limit': 'Actual inputs are retained registry claim evidence strings and URLs. Verbatim correspondence to original faculty-page passages was not established; do not describe these as newly verified original quotations.',
              'human_blinding_limit': 'Packet contains no judge answers. Some task tool diagnostics printed selected-item labels; if inspected by the reviewer, those items are potentially exposed. Do not replace them or claim guaranteed independent blinding.',
              'decision': 'REVISE; automated Stage 2 evidence collection complete, quality readiness not established'}
    write(DOC/'receipts/c2-final-analysis.json', report)
    write(DOC/'receipts/c2-final-budget.json', budget)
    print(json.dumps({'budget':budget,'candidates':[{k:v for k,v in c.items() if k in ['candidate','arms','paired_macro_B_minus_A','automatic_member_B']} for c in summaries], 'order_pair_results':report['order_pair_results']}))


if __name__ == '__main__':
    main()
