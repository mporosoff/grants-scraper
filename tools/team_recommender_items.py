"""Stable paid work claims, independent of batching and local display aliases."""
import json
from pathlib import Path
from tools.offline_spend import identity, Deferred


def judge_items(request):
    if request.get('protocol') not in {'D1', 'D1F'}:
        return []  # Older C2 scientific questions are deliberately incompatible.
    source = request['source_evidence']
    passages = {p['id']: {k:v for k,v in p.items() if k != 'id'} for p in source['passages']}
    aspects = {a['id']: {'text':a['text'], 'source':passages[a['source_ref']]} for a in request['aspects']}
    ordered = lambda values: sorted(values, key=identity)
    context = {'scope_id':request['scope_id'], 'limitations':source['limitations'],
               'source':ordered(passages.values()), 'aspects':ordered(aspects.values())}
    result = []
    for item in request['items']:
        value = {k:v for k,v in item.items() if k not in {'item_id','profile_evidence','target_aspect','candidates'}}
        value['profiles'] = ordered([{k:v for k,v in p.items() if k != 'id'} for p in item['profile_evidence']])
        candidates = item['candidates']
        value['candidates'] = {k:sorted(v) for k,v in candidates.items()} if isinstance(candidates,dict) else sorted(candidates)
        if 'target_aspect' in item:
            value['target_aspect'] = aspects[item['target_aspect']]
        result.append(identity(['D1-scientific-item-v1', context, value]))
    if len(result) != len(set(result)):
        raise ValueError('duplicate_scientific_item_in_batch')
    return result


def historical_index():
    path = Path(__file__).resolve().parents[1]/'config/team_recommender_executor/prior-items-d2.json'
    return json.loads(path.read_bytes())['requests']


def rebuild_historical_index(ledger_bytes, packet_directory):
    """Read-only reproduction from public packets and the original ledger mirror.

    This is an offline audit helper, never a source of dispatch authority.
    """
    import hashlib
    from tools import team_recommender_executor as e
    from tools.team_recommender_judge_d1 import contract
    digest = hashlib.sha256(ledger_bytes).hexdigest()
    if digest != '23ea6c322f9d555212dec88cebaf0a1f5dd438be27a502c17b5f7acca87f537d':
        raise ValueError('original_D1_checkpoint_required')
    settings=e.policy(); packets={}; indexed={}; result={}
    for row in json.loads(ledger_bytes)['requests']:
        if not row.get('purpose','').startswith('d1-'):continue
        h=row['packet_sha256']
        if h not in indexed:
            raw=(Path(packet_directory)/(h+'.json')).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=h:raise ValueError('historical_packet_hash_mismatch')
            requests=json.loads(raw)['requests'];packets[h]=len(requests);indexed[h]={}
            for request in requests:
                body=contract(request,settings,enforce_dispatch_bound=False)[0]
                indexed[h][identity([e.AUTHORIZATION_ID,'development-judge',body])]={'body_sha256':identity(body),'packet_sha256':h,'judge_items':judge_items(request)}
        found=indexed[h].get(row['key'])
        if found is None or found['body_sha256']!=row['body_sha256']:raise ValueError('historical_body_identity_mismatch')
        result[row['key']]=found
    if len(result)!=162:raise ValueError('historical_D1_inventory_mismatch')
    return result


def claimed_judge_items(row, historical=None):
    if not row.get('purpose','').startswith(('d1-','d2-','d3-')):
        return []
    if 'judge_items' in row:
        return row['judge_items']
    prior = (historical if historical is not None else historical_index()).get(row['key'])
    if prior is None or any(prior[k] != row[k] for k in ('body_sha256','packet_sha256')):
        raise Deferred('historical_scientific_item_identity_requires_recovery')
    return prior['judge_items']


def preflight(packet, settings, ledger):
    from tools import team_recommender_executor as e
    operation = packet['operation']; historical = historical_index()
    rows = ledger.read()['requests']; pending = {}
    for request in packet['requests']:
        contract = (e.embedding_contract if operation == 'embeddings' else e.judge_contract)(request,settings)
        key = identity([e.AUTHORIZATION_ID,operation,contract[0]])
        items = (e.embedding_items(request) if operation == 'embeddings' else judge_items(request))
        # Compare the entire packet before dispatch, including a conflict at its end.
        for prior in rows:
            old = prior.get('row_inputs',[]) if operation == 'embeddings' else claimed_judge_items(prior,historical)
            if key != prior['key'] and set(items).intersection(old):
                raise Deferred('paid_item_already_claimed_no_rebatch')
        for item in items:
            if item in pending and pending[item] != key:
                raise Deferred('overlapping_paid_packet_items')
            pending[item] = key
