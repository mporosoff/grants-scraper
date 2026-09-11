"""Export the completed authored audit, without unrestricted cached page text."""
import collections
import json
import pathlib
import statistics
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.researcher_registry import _write_json, dependency_report, load_registry, pool_state, registry_counts
from tools.researcher_source_audit import sha

def export():
    private = ROOT / 'outputs/researcher-profile-repair'
    out = ROOT / 'docs/team-recommender/profile-repair'
    before = load_registry(private / 'baseline-registry.json')
    after = load_registry(ROOT / 'config/researcher_registry.json')
    items = {i['id']: i for f in sorted(private.glob('review_batch_*.json')) for i in json.loads(f.read_bytes())}
    rows = []
    for old, new in zip(before['researchers'], after['researchers']):
        assert old['researcher_id'] == new['researcher_id']
        item = items[new['researcher_id']]
        sources = []
        for i in item['read_sources']:
            url = new['source_urls'][i]
            receipt = json.loads((private / 'sources' / (sha(url.encode()) + '.json')).read_bytes())
            sources.append({k: receipt[k] for k in ['url', 'final_url', 'fetched_at', 'response_sha256', 'text_sha256', 'text_extraction_version'] if k in receipt})
            # Failed fetches are attempts, never pages read.
            sources[-1]['read_status'] = 'read' if receipt.get('fetched_at') else 'unavailable'
        old_claims = {c['claim_id']: c for c in old['claims']}
        actions = []
        for c in new['claims']:
            previous = old_claims.get(c['claim_id'])
            if previous == c: continue
            actions.append({'claim_id': c['claim_id'], 'action': 'retired' if c['status'] == 'retired' else 'added' if previous is None else 'reactivated' if previous['status'] == 'retired' else 'revised',
                'previous_revision': previous['revision'] if previous else None, 'revision': c['revision'],
                'before_label': previous['label'] if previous else '', 'after_label': c['label'],
                'before_evidence': previous['evidence'] if previous else '', 'after_evidence': c['evidence'],
                'evidence_level': c['evidence_level'], 'evidence_records': c.get('evidence_records', []), 'retirement_reason': c.get('retirement_reason', '')})
        rows.append({'researcher_id': new['researcher_id'], 'name': new['display_name'], 'department': new['home_unit'],
            'before_pool_state': pool_state(old), 'after_pool_state': pool_state(new), 'auto_proposable_unchanged': old['auto_proposable'] == new['auto_proposable'],
            'source_pages': sources, 'before_summary': old['research_summary'], 'after_summary': new['research_summary'],
            'summary_evidence': new.get('summary_evidence', []), 'claim_actions': actions, **new['source_audit']})
    _write_json(out / 'person-audit.json', {'version': 'full-profile-repair-v1', 'author_type': 'in-task source review; not a human expert judgment or separate model judge',
        'baseline_commit': '16ed8ff1ca6e7e57199d3d4fafabeebb07f7cdb2', 'before_generation': before['registry_generation'], 'after_generation': after['registry_generation'], 'population': len(rows), 'people': rows})
    def indicators(people):
        def stats(values): return {'min': min(values), 'median': statistics.median(values), 'max': max(values)}
        return {'population': len(people), 'summary_characters': stats([len(p['research_summary']) for p in people]),
            'active_claims': stats([sum(c['status'] == 'active' for c in p['claims']) for p in people]),
            'supporting_sources': stats([len({u for c in p['claims'] if c['status'] == 'active' for u in c['source_urls']}) for p in people]),
            'legacy_template_summaries': sum(p['research_summary'].startswith('Research interests include ') or p['research_summary'] == 'Published research capabilities are listed below.' for p in people),
            'unresolved': sum(p.get('source_audit', {}).get('disposition') == 'unresolved' for p in people)}
    departments = {d: {'before': indicators([p for p in before['researchers'] if p['home_unit'] == d]), 'after': indicators([p for p in after['researchers'] if p['home_unit'] == d])} for d in sorted({p['home_unit'] for p in after['researchers']})}
    _write_json(out / 'department-parity.json', {'indicators_are_not_quality_scores': True, 'baseline_unresolved_not_previously_audited': True, 'departments': departments})
    receipts = [json.loads(p.read_bytes()) for p in (private / 'sources').glob('*.json')]
    _write_json(out / 'audit-summary.json', {'population': len(rows), 'dispositions': dict(collections.Counter(r['disposition'] for r in rows)),
        'before_counts': registry_counts(before), 'after_counts': registry_counts(after),
        'claim_actions': dict(collections.Counter(c['action'] for r in rows for c in r['claim_actions'])),
        'unique_cached_source_attempts': len(receipts), 'successful_retrievals': sum(bool(r.get('fetched_at')) for r in receipts),
        'read_source_urls': len({s['url'] for r in rows for s in r['source_pages'] if s['read_status'] == 'read'}),
        'paid_calls': 0, 'cost_usd': 0, 'after_generation': after['registry_generation']})
    model = json.loads((ROOT / 'config/opportunity_team_model.json').read_bytes())
    _write_json(out / 'dependency-report.json', dependency_report(before, after, model))
    lines = ['# Researcher source audit', '', 'All canonical records are listed in `person-audit.json`; source dates and hashes identify the actual retained retrieval. Claims are paraphrases unless explicitly marked otherwise. This is an in-task source audit, not returned human expert review.', '', '| Department | People | Median summary characters before → after | Median active claims before → after | Template summaries before → after | Unresolved after |', '|---|---:|---:|---:|---:|---:|']
    for name, d in departments.items():
        a, b = d['before'], d['after']
        lines.append(f"| {name} | {b['population']} | {a['summary_characters']['median']} → {b['summary_characters']['median']} | {a['active_claims']['median']} → {b['active_claims']['median']} | {a['legacy_template_summaries']} → {b['legacy_template_summaries']} | {b['unresolved']} |")
    lines += ['', 'These distributions diagnose curation differences; they are not scientific-quality scores. Longer overview-backed summaries replace the six-interest templates across departments. Claim consolidation can reduce counts while retaining scientific relationships. Remaining differences reflect documented breadth and source availability; no word or claim quotas were used.', '', 'Unresolved records:']
    for row in rows:
        if row['disposition'] == 'unresolved': lines.append(f"- {row['name']} ({row['researcher_id']}): {row['limitations']}")
    lines += ['', 'The three reference-only researchers received the same source review and remain excluded from automatic selection. No affiliation, visibility, ownership, stable identity or admission status was promoted to improve a count.', '', 'Historical-source limitations remain in each person row. PDF evidence refers to the identified researcher section rather than a claim that an entire conference program was reviewed. Official seminar abstracts/biographies and institution reports are corroborating evidence; they do not establish all current activity.']
    (out / 'AUDIT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'people': len(rows), 'departments': len(departments)}))

if __name__ == '__main__': export()
