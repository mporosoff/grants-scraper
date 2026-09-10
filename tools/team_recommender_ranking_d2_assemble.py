"""Adopt only exact trusted context vectors; preserve all D1 ingredient evidence."""
import array
import copy
import json
import math
from pathlib import Path
import sys
from tools.team_recommender_ranking_d2_prepare import ROOT,DOC,sha,write
from tools.team_recommender_context_d2 import canonical

def assemble(cloud):
    checkpoint=json.loads((cloud/'checkpoint.json').read_bytes())
    assert checkpoint['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=json.loads((cloud/'ledger.json').read_bytes());paid={r['id']:r for r in ledger['requests']}
    old=json.loads((DOC/'prepared/d1/bundle.json').read_bytes());directory=json.loads((DOC/'prepared/d1/directory.json').read_bytes())
    bundle=copy.deepcopy(old);bundle['representation']='D2-context-v1';raw=(DOC/'prepared/d1/vectors.f32').read_bytes()
    packet=json.loads((DOC/'packets/78c8502060cd478752dd526aa4477a7d5d1c94eefb9ad64e8c616ec9f01a7248.json').read_bytes())
    wanted={r['id'] for q in packet['requests'] for r in q['rows']};found={}
    for p in (cloud/'cache').glob('*.json'):
        cache=json.loads(p.read_bytes());r=paid[cache['request_id']]
        if r.get('purpose')!='d2-context':continue
        assert r['status']=='valid' and r['key']==cache['key'] and r['body_sha256']==cache['body_sha256']
        assert cache['model']=='voyage-4-lite' and cache['value']['input_role']=='document'
        for row in cache['value']['rows']:
            assert row['id'] in wanted and 'document:'+row['id'] in r['row_inputs']
            norm=math.sqrt(sum(v*v for v in row['embedding']));assert norm>0 and math.isfinite(norm) and len(row['embedding'])==1024
            a=array.array('f',(v/norm for v in row['embedding']))
            if sys.byteorder!='little':a.byteswap()
            assert row['id'] not in found;found[row['id']]=a.tobytes()
    assert set(found)==wanted
    indices={}
    for h in sorted(found):
        indices[h]=len(bundle['vector_rows']);bundle['vector_rows'].append({'id':'v'+str(indices[h]),'text_sha256':h,'input_role':'document','space':old['space']['fingerprint']});raw+=found[h]
    profiles={p['id']:p for p in directory['researchers']}
    for person in bundle['people']:
        profile=profiles[person['id']]
        for passage in person['passages']:
            claims=[c for c in profile['claims'] if c['status']=='active' and c['evidence']==passage['text']]
            labels=sorted({canonical({'claim_type':c['type'],'label':c['label']}) for c in claims})
            text=canonical({'claims':[json.loads(c) for c in labels],'evidence':passage['text']})
            passage['context_vector']=indices[sha(text.encode())]
        if profile.get('research_summary'):
            person['summary_vector']=indices[sha(canonical({'research_summary':profile['research_summary']}).encode())]
    restored=copy.deepcopy(bundle);restored.pop('representation');restored['vector_rows']=restored['vector_rows'][:len(old['vector_rows'])]
    for person in restored['people']:
        person.pop('summary_vector',None)
        for p in person['passages']:p.pop('context_vector')
    assert restored==old and raw[:len(old['vector_rows'])*4096]==(DOC/'prepared/d1/vectors.f32').read_bytes()
    dest=ROOT/'outputs/team-recommender-d2/assembled-r1';dest.mkdir(exist_ok=True)
    write(dest/'bundle.json',bundle)
    for name in ('directory.json','context.json','validations.json'):
        target=dest/name;data=(DOC/'prepared/d1'/name).read_bytes();assert not target.exists() or target.read_bytes()==data;target.write_bytes(data)
    target=dest/'vectors.f32';assert not target.exists() or target.read_bytes()==raw;target.write_bytes(raw)
    result={'trusted_run':checkpoint['run_id'],'trusted_main_sha':checkpoint['code_sha'],'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),
      'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'original_vector_rows':len(old['vector_rows']),'new_vector_rows':len(found),'total_vector_rows':len(bundle['vector_rows']),
      'new_context_requests':sum(r.get('purpose')=='d2-context' for r in paid.values()),'new_context_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in paid.values() if r.get('purpose')=='d2-context'),
      'new_context_charged_microusd':sum(r['charged_microusd'] for r in paid.values() if r.get('purpose')=='d2-context'),
      'cumulative_charged_microusd':sum(r['charged_microusd'] for r in paid.values()),'bundle_sha256':sha((dest/'bundle.json').read_bytes()),'bundle_bytes':(dest/'bundle.json').stat().st_size,
      'vector_sha256':sha(raw),'vector_bytes':len(raw),'directory_sha256':sha((dest/'directory.json').read_bytes()),'unchanged_original_ingredient_projection':True,
      'new_sources':0,'changed_researchers':0,'enrichment':False,'holdout_scored':False}
    write(DOC/'receipts/d2-context-vector-adoption.json',result);print(json.dumps(result))
if __name__=='__main__':assemble(Path(sys.argv[1]))
