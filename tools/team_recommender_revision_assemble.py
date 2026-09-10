"""Adopt only compatible exact cached vectors into D1; no provider operations."""
import array
import copy
import json
import math
from pathlib import Path
import sys
from tools.team_recommender_real_prep import ROOT,DOC,sha,write


def assemble(cloud):
    checkpoint=json.loads((cloud/'checkpoint.json').read_bytes())
    actual={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    if actual!=checkpoint['files']:raise ValueError('incomplete_trusted_checkpoint')
    ledger=json.loads((cloud/'ledger.json').read_bytes());paid={r['id']:r for r in ledger['requests']}
    old=json.loads((DOC/'prepared/c2/bundle.json').read_bytes());old_bytes=(DOC/'prepared/c2/vectors.f32').read_bytes()
    vectors={r['input_role']+':'+r['text_sha256']:old_bytes[i*4096:(i+1)*4096] for i,r in enumerate(old['vector_rows'])}
    old_keys=set(vectors)
    for p in (cloud/'cache').glob('*.json'):
        c=json.loads(p.read_bytes())
        if c['model']!='voyage-4-lite':continue
        r=paid[c['request_id']]
        if r['status']!='valid' or r['key']!=c['key'] or r['body_sha256']!=c['body_sha256']:raise ValueError('unreconciled_vector')
        for row in c['value']['rows']:
            key=c['value']['input_role']+':'+row['id']
            if key not in r['row_inputs']:raise ValueError('unowned_vector_row')
            norm=math.sqrt(sum(x*x for x in row['embedding']))
            if len(row['embedding'])!=1024 or not math.isfinite(norm) or norm<=0:raise ValueError('invalid_vector')
            a=array.array('f',(x/norm for x in row['embedding']))
            if sys.byteorder!='little':a.byteswap()
            raw=a.tobytes()
            if key in vectors and vectors[key]!=raw:raise ValueError('incompatible_exact_vector')
            vectors[key]=raw
    out=ROOT/'outputs/team-recommender-d1';inp=json.loads((out/'real-inputs-d1.json').read_bytes())
    owned=sorted([('query',r['id']) for r in inp['query_rows']]+[('document',r['id']) for r in inp['document_rows']])
    rows=[];indices={};raw=b''
    for role,h in owned:
        key=role+':'+h;indices[key]=len(rows);raw+=vectors[key]
        rows.append({'id':'v'+str(len(rows)),'text_sha256':h,'input_role':role,'space':old['space']['fingerprint']})
    for p in inp['people']:
        for item in p['passages']:item['vector']=indices['document:'+item.pop('input_hash')]
    for s in inp['scopes']:
        if s['prepared']:
            for item in [s['core'],s['whole_call'],*s['aspects']]:item['vector']=indices['query:'+item.pop('input_hash')]
    bundle={'schema_version':2,'registry_generation':old['registry_generation'],'space':copy.deepcopy(old['space']),
        'sources':inp['sources'],'scopes':inp['scopes'],'people':inp['people'],'vector_rows':rows}
    dest=out/'assembled-d1';dest.mkdir(exist_ok=True)
    write(dest/'bundle.json',bundle);write(dest/'directory.json',inp['directory']);write(dest/'validations.json',inp['validations'])
    if (dest/'vectors.f32').exists() and (dest/'vectors.f32').read_bytes()!=raw:raise ValueError('preserve_existing_vector_package')
    (dest/'vectors.f32').write_bytes(raw)
    context=json.loads((DOC/'prepared/c2/context.json').read_bytes());context['dispositions']=inp['dispositions'];write(dest/'context.json',context)
    summary={'trusted_run':int(cloud.name.split('-')[-1]),'trusted_code':checkpoint['code_sha'],'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),
        'cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'requests':len(ledger['requests']),
        'new_embedding_requests':sum(r.get('packet_sha256')=='f4302af4481ebf74a085950abbb639f36bc599212d216f304b5dfe09c41d7049' for r in ledger['requests']),
        'new_embedding_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in ledger['requests'] if r.get('packet_sha256')=='f4302af4481ebf74a085950abbb639f36bc599212d216f304b5dfe09c41d7049'),
        'vector_rows':len(rows),'reused_rows':sum(role+':'+h in old_keys for role,h in owned),'new_rows':sum(role+':'+h not in old_keys for role,h in owned),
        'new_researcher_rows':0,'space':old['space']['fingerprint'],'vector_bytes':len(raw),'vector_sha256':sha(raw),
        'bundle_bytes':(dest/'bundle.json').stat().st_size,'bundle_sha256':sha((dest/'bundle.json').read_bytes()),'profile_enrichment':False}
    write(DOC/'receipts/d1-vector-adoption.json',summary);print(json.dumps(summary))


if __name__=='__main__':assemble(Path(sys.argv[1]))
