"""Deterministic public input preparation; never loads credentials or calls providers."""
import hashlib
import json
from pathlib import Path
from tools.team_recommender_executor import policy, validate_packet, embedding_contract
from tools.team_recommender_group_audit import catalog

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender'
OUT=ROOT/'outputs/team-recommender-c2'
def sha(b):return hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()
def jsdata(path):
    s=path.read_text(encoding='utf8');return json.loads(s[s.index('{'):s.rfind('}')+1])
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('immutable_file_exists:'+str(path))
    path.write_bytes(raw);return sha(raw)
def packet(requests,operation='embeddings'):
    p=policy();value={'schema_version':1,'authorization_id':p['authorization_id'],'registry_generation':p['registry_generation'],'operation':operation,'requests':requests}
    validate_packet(value,p)
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    target=DOC/'packets'/(sha(raw)+'.json');target.parent.mkdir(exist_ok=True)
    if target.exists() and target.read_bytes()!=raw:raise ValueError('packet_conflict')
    target.write_bytes(raw)
    return {'sha256':sha(raw),'path':target.relative_to(ROOT).as_posix(),'bytes':len(raw),'requests':len(requests),'rows':sum(len(r.get('rows',[])) for r in requests),'conservative_input_bound':sum(embedding_contract(r,p)[1] for r in requests) if operation=='embeddings' else None}
def canary():
    p=policy();parents={r['opportunity_id']:r for r in catalog()}
    ids=['359696','363489','357002']
    rows=[{'owner':i,'text':parents[i]['description'].split('. ')[0]+'.'} for i in ids]
    for row in rows:row['id']=sha(row['text'])
    claims=[(person,c[0]) for person,c in sorted(p['profile_claims'].items())][:3]
    docs=[{'owner':person,'text':c['text'],'id':sha(c['text'])} for person,c in claims]
    result=packet([{'input_role':'query','rows':rows},{'input_role':'document','rows':docs}])
    result.update({'phase':'wiring-canary','source_selection':'Three preselected coherent development sources: human olfactory imaging, inertial sensor/control co-design, molecular cancer imaging. Selected before numerical outputs. Exact first source sentences; reused later as core rows.','source_ids':ids,'profile_rows':len(docs),'new_authorization':False,'ledger_owner':'GitHub main-only executor; local ledger is a read-only mirror after dispatch','prior_experiment_spend_usd':0,'prior_reservations_usd':0,'maximum_canary_usd':result['conservative_input_bound']*.02/1_000_000,'no_recommendations_generated':True})
    write(DOC/'receipts/c2-canary-input-plan.json',result)
    print(json.dumps(result))
if __name__=='__main__':canary()
