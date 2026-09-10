"""Adopt exact trusted offline vectors into a public static ingredient recipe."""
import array
import json
import math
import sys
from tools.team_recommender_real_prep import OUT,DOC,ROOT,write,sha,canonical

def assemble(cloud):
    checkpoint=json.loads((cloud/'checkpoint.json').read_bytes())
    actual={f.relative_to(cloud).as_posix():sha(f.read_bytes()) for f in cloud.rglob('*.json') if f.name!='checkpoint.json'}
    if actual!=checkpoint['files']:raise ValueError('untrusted_checkpoint_content')
    ledger=json.loads((cloud/'ledger.json').read_bytes());paid={r['id']:r for r in ledger['requests']}
    vectors={}
    for path in (cloud/'cache').glob('*.json'):
        c=json.loads(path.read_bytes());r=paid[c['request_id']]
        if r['status']!='valid' or c['body_sha256']!=r['body_sha256'] or c['key']!=r['key']:raise ValueError('unlinked_result')
        if c['model']!='voyage-4-lite':continue
        role=c['value']['input_role']
        for row in c['value']['rows']:
            if role+':'+row['id'] not in r['row_inputs']:raise ValueError('unowned_result_row')
            raw=row['embedding'];norm=math.sqrt(sum(v*v for v in raw))
            if len(raw)!=1024 or not math.isfinite(norm) or norm<=0:raise ValueError('invalid_embedding')
            f=array.array('f',(v/norm for v in raw))
            if sys.byteorder!='little':f.byteswap()
            key=role+':'+row['id'];b=f.tobytes()
            if key in vectors and vectors[key]!=b:raise ValueError('conflicting_exact_vectors')
            vectors[key]=b
    inp=json.loads((OUT/'real-inputs-v2.json').read_bytes());owned=sorted([('query',r['id']) for r in inp['query_rows']]+[('document',r['id']) for r in inp['document_rows']])
    space={'provider':'voyage','model':'voyage-4-lite','dimension':1024,'preprocessing':'exact-utf8-text-v1','normalization':'l2-v1','serialization':'f32le-v1','truncation':False,'source_output_dtype':'float','chunking':'one-input-per-item','input_encoding':'utf8','roles':{'scope':'query','passage':'document'},'canaries':{role:sha(vectors[role+':'+next(h for r,h in owned if r==role)]) for role in ['query','document']}}
    space['fingerprint']=sha(canonical(space));rows=[];bytes_out=b'';indices={}
    for role,h in owned:
        key=role+':'+h;indices[key]=len(rows);rows.append({'id':'v'+str(len(rows)),'text_sha256':h,'input_role':role,'space':space['fingerprint']});bytes_out+=vectors[key]
    for p in inp['people']:
        for passage in p['passages']:passage['vector']=indices['document:'+passage.pop('input_hash')]
    for scope in inp['scopes']:
        if scope['prepared']:
            for item in [scope['core'],scope['whole_call'],*scope['aspects']]:item['vector']=indices['query:'+item.pop('input_hash')]
    bundle={'schema_version':2,'registry_generation':inp['directory']['registry_generation'],'sources':inp['sources'],'scopes':inp['scopes'],'people':inp['people'],'vector_rows':rows,'space':space}
    dest=OUT/'assembled-v2';dest.mkdir(exist_ok=True)
    write(dest/'bundle.json',bundle);write(dest/'directory.json',inp['directory']);write(dest/'validations.json',inp['validations']);(dest/'vectors.f32').write_bytes(bytes_out)
    write(DOC/'receipts/c2-vector-adoption.json',{'trusted_run':cloud.name,'vectors':len(rows),'bytes':len(bytes_out),'space':space,'vector_sha256':sha(bytes_out),'input_recipe_sha256':sha((OUT/'real-inputs-v2.json').read_bytes()),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'provider_requests':len(ledger['requests']),'tokens':sum(r.get('usage',{}).get('total_tokens',0) for r in ledger['requests']),'charged_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'historical_search_vector_reuse':0,'canary_rows_reused':6})
    print(json.dumps({'directory':str(dest),'rows':len(rows),'bytes':len(bytes_out)}))
if __name__=='__main__':
    from pathlib import Path
    assemble(Path(sys.argv[1]))
