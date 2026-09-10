"""Continue only never-claimed requests from the finite frozen judge inventory."""
import json,sys
from pathlib import Path
from tools.team_recommender_real_prep import DOC,OUT,sha,write,packet
from tools.team_recommender_executor import judge_contract,policy,legacy_judge_key
from tools.team_recommender_budget import AUTHORIZATION_ID
from tools.offline_spend import identity

def pending(run):
    cloud=OUT/('cloud-'+str(run)); cp=json.loads((cloud/'checkpoint.json').read_bytes())
    assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=json.loads((cloud/'ledger.json').read_bytes()); rows={r['key']:r for r in ledger['requests']}
    assert ledger['logical_id']==AUTHORIZATION_ID and all(r['status'] in ('valid','failed') for r in rows.values())
    original=json.loads((DOC/'packets/4ec714fa898d362930b80c7a1139550f45f77427733abbd7649d1aca7abba2c3.json').read_bytes());settings=policy(); todo=[];indices=[]
    for i,r in enumerate(original['requests']):
        key=identity([AUTHORIZATION_ID,'development-judge',judge_contract(r,settings)[0]])
        if key in rows or legacy_judge_key(r,settings) in rows:continue
        todo.append(r);indices.append(i)
    if not todo:print(json.dumps({'remaining':0}));return
    actual=sum(r['charged_microusd'] for r in rows.values())
    maximum=sum((judge_contract(r,settings)[1]*5+1)//2+5120 for r in todo)
    assert not ledger['blocked_providers'] and not ledger.get('reservation_overrun')
    assert actual+maximum<=6_000_000 and 10_000_000-actual-maximum>=4_000_000
    result=packet(todo,'development-judge');result.update(prior_run=run,prior_ledger_sha256=sha((cloud/'ledger.json').read_bytes()),prior_actual_usd=actual/1e6,original_request_indices=indices,
      policy='Only exact original unclaimed requests. Every valid, failed or uncertain claimed logical request is excluded; failed items remain unresolved. No rebatching, new items, prompt changes or automatic paid retry.')
    write(DOC/'receipts'/('c2-pending-after-'+str(run)+'.json'),result)
    print(json.dumps({'remaining':len(todo),'packet':result['sha256'],'prior_actual_usd':result['prior_actual_usd'],'maximum_next_packet_usd':maximum/1e6,'worst_cumulative_usd':(actual+maximum)/1e6,'later_preserved_usd':(10_000_000-actual-maximum)/1e6,'receipt':'docs/team-recommender/receipts/c2-pending-after-'+str(run)+'.json'}))
if __name__=='__main__':pending(int(sys.argv[1]))
