"""One zero-provider audit of retained development evidence; no holdout outputs."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from tools.team_recommender_evidence_projection import encoded, identity, person_document, project_item, pack

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/team-recommender'
OUT = ROOT / 'outputs/team-recommender-closeout'
D3 = ROOT / 'outputs/team-recommender-d3'


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    mapping = read(D3 / 'judge-item-map-d3-v2.json')
    analysis = read(D3 / 'analysis-34538646232.json')
    labels = analysis['labels']
    registry = {p['id']: p for p in read(D3 / 'assembled-E2/directory.json')['researchers']}
    ledger = read(DOC / 'budget-ledger.json')
    assert (DOC / 'budget-ledger.json').read_bytes() == (D3 / 'cloud-34538646232/ledger.json').read_bytes()
    requests = {r['id']: r for r in ledger['requests']}
    assert len(requests) == len(ledger['requests']) == 475
    assert len({r['key'] for r in requests.values()}) == 475
    assert all(r['attempt'] == 1 for r in requests.values())
    charged = sum(r.get('charged_microusd', 0) for r in requests.values())
    unresolved = [r for r in requests.values() if r['status'] not in {'valid', 'failed'}]
    assert charged == 3135333 and not unresolved
    packets = {}
    def packet(h):
        if h not in packets:
            path = DOC / 'packets' / (h + '.json')
            assert digest(path) == h
            packets[h] = read(path)
        return packets[h]
    d1map = read(ROOT / 'outputs/team-recommender-d1/judge-item-map-d1.json')
    contexts = {}
    for r in packet(d1map['packet_sha256'])['requests']:
        contexts[r['scope_id']] = {'source_evidence': r['source_evidence'], 'aspects': r['aspects']}
    occurrences = [o for o in mapping['occurrences'] if o.get('arm') in {'E1', 'E2', 'A-E1', 'A-E2'} and 'key' in o]
    bykey = defaultdict(list)
    for o in occurrences:
        bykey[o['key']].append(o)
    result, complete_packets, oversize = [], [], []
    batches = defaultdict(list)
    for key, occ in sorted(bykey.items()):
        entry = mapping['unique'][key]; item = entry['value']; sid = entry['scope_id']
        label = labels.get(key)
        actual = None; packet_hash = None; result_verified = False
        if label:
            row = requests[label['request_id']]
            assert row['key'] == label['request_key'] and row['status'] == 'valid'
            packet_hash = row['packet_sha256']
            for req in packet(packet_hash)['requests']:
                if req.get('scope_id') != sid:
                    continue
                for candidate in req.get('items', []):
                    if {k: v for k, v in candidate.items() if k != 'item_id'} == item:
                        actual = req
                        cache = read(D3 / 'cloud-34538646232/cache' / (row['key'] + '.json'))
                        assert cache['body_sha256'] == row['body_sha256']
                        result_verified = any(v['item_id'] == candidate['item_id'] and v['verdict'] == label['label'] for v in cache['value']['verdicts'])
                        if result_verified:
                            break
                if result_verified:
                    break
            assert actual is not None and result_verified, ('unreconstructed_judgment', key)
            assert contexts[sid] == {'source_evidence': actual['source_evidence'], 'aspects': actual['aspects']}
        full = project_item(item, registry)
        profiles = full['profile_documents']; seen = item['profile_evidence'] if label else []
        people = []
        contradictory = False
        for p in profiles:
            supplied = [r for r in seen if r['person_id'] == p['person_id']]
            current = {c['claim_id']: c for c in registry[p['person_id']]['claims'] if c['status'] == 'active'}
            for row in supplied:
                c = current.get(row['claim_id'])
                contradictory |= c is None or any([row['text'] != c['evidence'], row['revision'] != c['revision'], row['label'] != c['label'], row['claim_type'] != c['type'], row['research_summary'] != p['research_summary']]) if c else True
            missing = sorted(set(current) - {r['claim_id'] for r in supplied})
            people.append({'person_id': p['person_id'], 'available_document_sha256': identity(p),
                           'available_claim_ids': sorted(current), 'supplied_claim_ids': [r['claim_id'] for r in supplied],
                           'missing_claim_ids': missing, 'full_summary_supplied': bool(supplied) and all(r['research_summary'] == p['research_summary'] for r in supplied),
                           'supplied_evidence_sha256': identity(supplied) if supplied else None})
        quotes = []
        if 'explanation' in item:
            for q in re.findall('The public passage “(.*?)”', item['explanation']):
                quotes.append({'text': q, 'exists_in_frozen_people': any(s['text'] == q for p in profiles for s in p['statements']),
                               'present_in_actual_judge_packet': any(r['text'] == q for r in seen)})
        incomplete = any(p['missing_claim_ids'] or not p['full_summary_supplied'] for p in people)
        # Structural completeness is a conservative task-adequacy boundary. We
        # cannot infer that an omitted statement would change the semantic grade.
        status = 'missing' if not label else 'contradictory' if contradictory else 'incomplete' if incomplete else 'adequate-for-recorded-task'
        result.append({'key': key, 'scope_id': sid, 'task': item['task_type'], 'target_aspect': item.get('target_aspect'),
                       'context_sha256': identity(contexts[sid]), 'actual_packet_sha256': packet_hash,
                       'actual_request_id': label.get('request_id') if label else None,
                       'actual_cache_and_result_verified': result_verified, 'people': people,
                       'explanation': item.get('explanation'), 'quoted_evidence': quotes,
                       'original_verdict': label, 'evidence_status': status, 'occurrences': occ})
        batches[sid].append((key, full))
    prompt = (ROOT / 'config/team_recommender_executor/judge-d1.md').read_text(encoding='utf8')
    prompt = prompt[:prompt.index('Return exactly one verdict')] + 'Return one verdict, one evidence reference and the most specific allowed reason code per item.'
    for sid, items in sorted(batches.items()):
        ctx = contexts[sid]
        p, o = pack(ctx['source_evidence'], ctx['aspects'], items, prompt)
        complete_packets.extend([{'scope_id': sid, **r} for r in p]); oversize.extend([{'scope_id': sid, **r} for r in o])
    index = {r['key']: r for r in result}
    def summary(occ):
        graded = [o for o in occ if o['key'] in labels]
        fixed = [o for o in occ if index[o['key']]['evidence_status'] == 'adequate-for-recorded-task']
        limited = len(occ) - len(fixed)
        positive = sum(labels[o['key']]['label'] in {'strong', 'plausible', 'faithful'} for o in fixed)
        unrelated = sum(labels[o['key']]['label'] == 'unrelated' for o in fixed)
        return {'occurrences': len(occ), 'unique_questions': len({o['key'] for o in occ}),
                'observed': len(graded), 'missing': len(occ)-len(graded),
                'recorded_labels': dict(Counter(labels[o['key']]['label'] for o in graded)),
                'evidence_status_occurrences': dict(Counter(index[o['key']]['evidence_status'] for o in occ)),
                'evidence_limited_occurrences': limited,
                'reasonable_best_worst_counts': [positive, positive + limited],
                'unrelated_best_worst_counts': [unrelated, unrelated + limited],
                'bounds_denominator': len(occ), 'bounds_are_not_corrected_grades': True}
    metrics = {}
    for arm in ['E1', 'E2', 'A-E1', 'A-E2']:
        own = [o for o in occurrences if o['arm'] == arm]
        groups = {}
        for name, select in [('top5', lambda o: o['kind']=='top5'),
                             ('primary_groups', lambda o: o['kind'] in {'option-group', 'primary-A-matched'} and o.get('rank',1)==1),
                             ('primary_members', lambda o: o['kind'] in {'option-member', 'primary-A-member'} and o.get('rank',1)==1),
                             ('additional_alternative_groups', lambda o: o['kind']=='option-group' and o['rank']>1),
                             ('additional_alternative_members', lambda o: o['kind']=='option-member' and o['rank']>1),
                             ('explanation', lambda o: o['kind']=='explanation')]:
            groups[name] = summary([o for o in own if select(o)])
        metrics[arm] = groups
    all_member = {}
    for arm in analysis['summary']:
        own = [o for o in mapping['occurrences'] if o.get('arm')==arm and o['kind']=='option-member' and o['rank']==1]
        rows = defaultdict(list)
        for o in own: rows[o['scope_id']].append(labels.get(o['key'], {}).get('label'))
        all_member[arm] = {'primary_groups':len(rows), 'all_members_graded_reasonable':sum(all(v in {'strong','plausible'} for v in vs) for vs in rows.values()),
                           'missing_member_groups':sum(None in vs for vs in rows.values()),
                           'at_least_one_unrelated':sum('unrelated' in vs for vs in rows.values())}
    write(OUT / 'complete-projection-dry-run.json', complete_packets)
    normalized = {'version':'decision-closeout-evidence-audit-v1', 'method':'All E1/E2 and their A comparators; all original positive/negative/missing items. Completeness is structural; omitted relevance cannot be adjudicated locally.',
                  'contexts':{identity(v):v for v in contexts.values()}, 'people':{p:person_document(registry[p]) for p in sorted({p['person_id'] for r in result for p in r['people']})},
                  'items':result, 'metrics':metrics, 'all_member_primary':all_member,
                  'status_counts':dict(Counter(r['evidence_status'] for r in result)),
                  'new_model_judgments':0, 'holdout_scored':False}
    write(DOC / 'receipts/closeout-evidence-coverage.json', normalized)
    bounds = sorted(p['input_bound'] for p in complete_packets)
    # Measure a finite E2/A-E2 validation-shaped subset separately, without
    # creating any held-out recommendations or silently shrinking evaluation.
    selected = {o['key'] for o in occurrences if o['arm'] in {'E2','A-E2'} and (o['kind']=='top5' or o['kind'] in {'primary-A-matched','primary-A-member','matched-AB'} or o['kind'] in {'option-group','option-member'} and o['rank']==1)}
    primary_packets, primary_oversize = [], []
    for sid, items in sorted(batches.items()):
        items = [(k,v) for k,v in items if k in selected]
        if not items: continue
        ctx=contexts[sid]; p,o=pack(ctx['source_evidence'],ctx['aspects'],items,prompt)
        primary_packets.extend(p); primary_oversize.extend([{'scope_id':sid,**v} for v in o])
    dry = {'projection_version':'complete-retained-registry-v1', 'semantic_protocol':'unchanged D1F', 'trusted_route_enabled':False,
           'unique_items':len(result), 'packets':len(complete_packets), 'items_in_packets':sum(len(p['keys']) for p in complete_packets),
           'oversized_indivisible_items':oversize, 'input_bound':{'min':min(bounds),'median':bounds[len(bounds)//2],'p95':bounds[int(len(bounds)*.95)],'max':max(bounds),'sum':sum(bounds)},
           'request_limit':12000,'output_limit':512,'private_dry_run_sha256':digest(OUT/'complete-projection-dry-run.json'),
           'E2_A_E2_primary_top5_comparison':{'unique_items':len(selected),'packets':len(primary_packets),'oversized':primary_oversize,
              'source_denominator':35,'prepared_only':True,'summed_input_bound':sum(p['input_bound'] for p in primary_packets),
              'conservative_usd':sum(p['input_bound']*2.5/1e6+512*10/1e6 for p in primary_packets)},
           'provider_calls':0, 'no_evidence_cropped':True,'no_development_rejudging':True}
    write(DOC / 'receipts/closeout-projection-dry-run.json',dry)
    budget={'authorization_id':ledger['logical_id'],'ledger_sha256':digest(DOC/'budget-ledger.json'),'cloud_checkpoint_sha256':digest(D3/'cloud-34538646232/checkpoint.json'),
            'authority':'Last restored main-only cloud checkpoint 34538646232; identical local read-only mirror. No new cloud dispatch or second spending copy.',
            'charged_microusd':charged,'reserved_microusd':0,'used_requests':475,'remaining_requests':215,'remaining_microusd':10000000-charged,
            'new_closeout_requests':0,'new_closeout_spend_microusd':0,'old_other_task_spend_credit':0,'historical_other_task_reused_spend_usd':11.971342,
            'exact_ledger_cache_hit_events':sum(e['kind']=='exact_cache_hit' for e in ledger['events'])}
    write(DOC/'receipts/closeout-ledger-reconciliation.json',budget)
    print(json.dumps({'items':len(result),'status':normalized['status_counts'],'dry':{k:v for k,v in dry.items() if k not in {'oversized_indivisible_items'}},'all_member':all_member}))


if __name__ == '__main__':
    audit()
