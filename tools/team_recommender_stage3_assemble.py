"""Adopt trusted exact E2 vectors and materialize frozen source-only packages."""
import copy
import json
from pathlib import Path
import numpy as np
from tools.team_recommender_real_prep import ROOT, DOC, write, sha
from tools.team_recommender_executor import policy
from tools.team_recommender_stage3_executor import embedding_contract
from tools.team_recommender_embeddings_d3 import validate_value
from tools.offline_spend import identity

OUT=ROOT/'outputs/team-recommender-stage3'
OLD=ROOT/'outputs/team-recommender-d3/assembled-E2'
def read(p): return json.loads(p.read_bytes())

def main():
    cloud=OUT/'cloud-embeddings';cp=read(cloud/'checkpoint.json')
    assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=read(cloud/'ledger.json');prior=read(OUT/'cloud-start/ledger.json')
    assert ledger['requests'][:len(prior['requests'])]==prior['requests']
    paid={r['key']:r for r in ledger['requests']};found={};receipts=[]
    for r in read(OUT/'embedding-packet.json')['requests']:
        body,bound=embedding_contract(r,policy());key=identity([policy()['authorization_id'],'embeddings',body])
        charge=paid[key];assert charge['status']=='valid'
        cache=read(cloud/'cache'/(key+'.json'))
        assert cache['request_id']==charge['id'] and cache['key']==key and cache['body_sha256']==charge['body_sha256']==identity(body)
        validate_value(cache['value'],r)
        for v in cache['value']['rows']:
            a=np.asarray(v['embedding'],dtype=np.float64);a/=np.linalg.norm(a)
            assert v['id'] not in found;found[v['id']]=a.astype('<f4')
        receipts.append({k:charge[k] for k in ['id','key','usage','charged_microusd','reserved_input_tokens','status']})
    assert len(found)==190
    keys=read(ROOT/'outputs/team-recommender-d3/adopted-vector-keys.json')
    oldvectors=np.load(ROOT/'outputs/team-recommender-d3/adopted-vectors.npz')['vectors']
    for key,vector in zip(keys,oldvectors):
        if key[:2]==['voyage-4-large','query']:
            assert key[2] not in found;found[key[2]]=vector
    recipe=read(OUT/'source-inputs-v1.json');original=read(OLD/'bundle.json')
    originalbytes=(OLD/'vectors.f32').read_bytes();packages={}
    for cohort in ['holdout_effective','rollout50','rollout150']:
        ids=set(recipe['cohorts'][cohort]);b=copy.deepcopy(original)
        b['scopes']=[copy.deepcopy(s) for s in recipe['scopes'] if s['id'] in ids]
        b['sources']=[s for s in recipe['sources'] if s['id'] in ids]
        b['vector_rows']=copy.deepcopy(original['vector_rows'][:155]);vectors=[originalbytes[i*4096:(i+1)*4096] for i in range(155)]
        byhash={}
        for scope in b['scopes']:
            if not scope['prepared']:continue
            for item in [scope['core'],scope['whole_call'],*scope['aspects']]:
                h=sha(item['text'])
                if h not in byhash:
                    byhash[h]=len(vectors);vectors.append(found[h].astype('<f4').tobytes())
                    b['vector_rows'].append({'id':'v'+str(byhash[h]),'input_role':'query','space':b['space']['fingerprint'],'text_sha256':h})
                item['vector']=byhash[h]
        dest=OUT/('assembled-'+cohort);dest.mkdir(exist_ok=False)
        validations=[v for v in recipe['validations'] if v['scope_id'] in ids]
        context={k:recipe[k] for k in ['parents','records','snapshot_at','controls','dispositions','scope_denominator','control_denominator']}
        hashes={n:write(dest/(n+'.json'),v) for n,v in [('bundle',b),('validations',validations),('context',context)]}
        (dest/'directory.json').write_bytes((OLD/'directory.json').read_bytes());hashes['directory']=sha((dest/'directory.json').read_bytes())
        raw=b''.join(vectors);(dest/'vectors.f32').write_bytes(raw);hashes['vectors']=sha(raw)
        packages[cohort]={'scopes':len(ids),'prepared':sum(s['prepared'] for s in b['scopes']),'people':155,'vector_rows':len(vectors),'source_excerpts':sum(len(s['excerpts']) for s in b['sources']),'aspects':sum(len(s['aspects']) for s in b['scopes']),'input_hashes':hashes,'raw_vector_bytes':len(raw)}
    receipt={'version':'S3-E2-vector-adoption-v1','cloud_run':cp['run_id'],'trusted_code':cp['code_sha'],'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'requests':receipts,'new_rows':190,'reused_query_rows':48,'reused_profile_rows':155,'profile_changes':0,'requests_cumulative':len(ledger['requests']),'charged_cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'charged_stage3_microusd':sum(r['charged_microusd'] for r in receipts),'outstanding_microusd':sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown'),'packages':packages,'holdout_scored':False}
    write(DOC/'receipts/stage3-vector-adoption-v1.json',receipt)
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
