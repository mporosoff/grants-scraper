"""Assemble one real representation from exact purchased inputs, no provider I/O."""
import copy
import gzip
import json
import sys
from pathlib import Path
import numpy as np
from tools.team_recommender_embeddings_d3 import *
from tools.team_recommender_executor import policy
from tools.team_recommender_real_prep import ROOT,DOC,sha,write

OUT=ROOT/'outputs/team-recommender-d3'
def read(p):return json.loads(p.read_bytes())

def assemble(arm):
    assert arm in {'E1','E2','E3'}
    original=read(DOC/'prepared/d1/bundle.json');bundle=copy.deepcopy(original);profiles_by_id=profiles(policy());rep={'E1':PHRASES,'E2':COMBINED,'E3':CONTEXT}[arm];model=MODELS[rep]
    keys=read(OUT/'adopted-vector-keys.json');vectors=np.load(OUT/'adopted-vectors.npz')['vectors'];lookup={tuple(k):vectors[i] for i,k in enumerate(keys)};owned={};row_bytes=[]
    space={**original['space'],'model':model,'preprocessing':'exact-utf8-D3-v1','chunking':rep,'endpoint':CONTEXT_URL if arm=='E3' else STANDARD_URL}
    space.pop('fingerprint');space['canaries']={'query':next(k[2] for k in keys if k[:2]==[model,'query']),'document':next(k[2] for k in keys if k[:2]==[model,'document'])}
    fingerprint=sha(canonical(space));space['fingerprint']=fingerprint;bundle['space']=space;bundle['vector_rows']=[];bundle['representation']=rep
    calibration=read(OUT/'matrices-calibration.json')['arms'][arm]['fit']['final'];bundle['scorer']={'version':'D3-fixed-v1',**{k:calibration[k] for k in ['member','broad','aspect','anchor']}}
    def row(role,key):
        identity=(model,role,key)
        if identity not in owned:
            index=len(row_bytes);owned[identity]=index;raw=lookup[identity].astype('<f4').tobytes();row_bytes.append(raw)
            bundle['vector_rows'].append({'id':'v'+str(index),'text_sha256':key,'input_role':role,'space':fingerprint})
        return owned[identity]
    for person in bundle['people']:
        p=profiles_by_id[person['id']]
        if arm!='E1':person['document']={'chunks':p['chunks']}
        indices={a['text']:i for i,a in enumerate(p['attribution']) if a['field']=='claims'}
        for passage in person['passages']:
            key=digest(passage['text']) if arm=='E1' else digest(p['combined']) if arm=='E2' else digest(canonical([digest(canonical(p['chunks'])),indices[passage['text']],p['chunks'][indices[passage['text']]]]))
            passage['vector']=row('document',key)
            if arm=='E3':passage['chunk_index']=indices[passage['text']]
    for s in bundle['scopes']:
        if not s['prepared']:continue
        for item in [s['core'],s['whole_call'],*s['aspects']]:item['vector']=row('query',digest(item['text']))
    dest=OUT/('assembled-'+arm);dest.mkdir(exist_ok=True);write(dest/'bundle.json',bundle);raw=b''.join(row_bytes)
    target=dest/'vectors.f32';assert not target.exists() or target.read_bytes()==raw;target.write_bytes(raw)
    for name in ['directory.json','validations.json','context.json']:
        data=(DOC/'prepared/d1'/name).read_bytes();target=dest/name;assert not target.exists() or target.read_bytes()==data;target.write_bytes(data)
    receipt={'arm':arm,'representation':rep,'model':model,'space':fingerprint,'scorer':bundle['scorer'],'rows':len(row_bytes),'bundle_sha256':sha((dest/'bundle.json').read_bytes()),'vector_sha256':sha(raw),
      'bundle_bytes':(dest/'bundle.json').stat().st_size,'vector_bytes':len(raw),'bundle_gzip_bytes':len(gzip.compress((dest/'bundle.json').read_bytes(),mtime=0)),'vector_gzip_bytes':len(gzip.compress(raw,mtime=0)),
      'directory_sha256':sha((dest/'directory.json').read_bytes()),'source_changes':0,'researcher_changes':0,'provider_calls':0,'holdout_scored':False,'hydration':'not established by assembly; requires native loader validation'}
    write(DOC/'receipts'/('d3-assembled-'+arm+'.json'),receipt);print(json.dumps(receipt))

if __name__=='__main__':assemble(sys.argv[1])
