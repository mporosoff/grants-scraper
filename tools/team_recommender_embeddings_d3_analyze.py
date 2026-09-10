"""Adopt exact offline vectors and calibrate on existing grouped development labels."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path
import numpy as np
from tools.team_recommender_embeddings_d3 import *
from tools.team_recommender_real_prep import ROOT,DOC,write,sha
from tools.team_recommender_executor import policy
from tools.team_recommender_ranking_d2_fit import groups_fold,choose,selected
from tools.team_recommender_learning import metrics
from tools.offline_spend import identity

OUT=ROOT/'outputs/team-recommender-d3'
def read(p):return json.loads(p.read_bytes())

def adopt(cloud):
    cp=read(cloud/'checkpoint.json');assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=read(cloud/'ledger.json');old=read(ROOT/'outputs/team-recommender-d2/cloud-34510982749/ledger.json')
    assert ledger['requests'][:len(old['requests'])]==old['requests']
    paid={r['key']:r for r in ledger['requests']};found={};requests=[];missing=[]
    plan=read(DOC/'receipts/d3-input-plan.json');settings=policy()
    for packet in plan['plans']:
        for r in read(DOC/'packets'/(packet['sha256']+'.json'))['requests']:
            body,bound=contract(r,settings);key=identity([settings['authorization_id'],'embeddings',body]);row=paid.get(key);path=cloud/'cache'/(key+'.json')
            if not row or row['status']!='valid' or not path.exists():
                missing.append({'key':key,'representation':r['representation'],'role':r['input_role'],'status':row['status'] if row else 'unattempted','rows':len(expected_rows(r))});continue
            value=read(path);assert value['request_id']==row['id'] and value['key']==key and value['body_sha256']==row['body_sha256']==identity(body) and value['model']==r['model']
            validate_value(value['value'],r)
            for info,v in zip(expected_rows(r),value['value']['rows']):
                k=(r['model'],r['input_role'],v['id']);assert k not in found
                a=np.asarray(v['embedding'],dtype=np.float64);a/=np.linalg.norm(a)
                found[k]=a.astype('<f4')
            requests.append({'key':key,'request_id':row['id'],'representation':r['representation'],'input_role':r['input_role'],'output_rows':len(value['value']['rows']),'usage':row['usage'],'charged_microusd':row['charged_microusd']})
    receipt={'cloud_run':cp['run_id'],'trusted_code':cp['code_sha'],'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'requests':requests,'missing':missing,
      'new_rows':len(found),'new_tokens':sum(r['usage']['total_tokens'] for r in requests),'new_charged_microusd':sum(r['charged_microusd'] for r in requests),'cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),
      'reserved_microusd':sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown'),'no_enrichment':True,'holdout_scored':False}
    return found,receipt

def calibrate(rows,labels,feature,assignments):
    known=[{**r,'label':labels[r['scope_id'],r['id']]} for r in rows if (r['scope_id'],r['id']) in labels]
    usable=[r for r in known if r['label'] in {'strong','plausible','unrelated'}]
    y=np.array([r['label']!='unrelated' for r in usable],float);g=np.array([r['group'] for r in usable]);q=np.array([r[feature] for r in usable]);fold=np.array([assignments[v] for v in g])
    assert len(set(y))==2
    def thresholds(train):
        positive=train&(y==1);assert positive.any()
        qfloor=float(np.quantile(q[positive],.05));aspect=float(np.quantile([usable[i]['max_aspect'] for i in np.flatnonzero(positive)],.05));anchor=float(np.quantile([usable[i]['core'] for i in np.flatnonzero(positive)],.10))
        admitted=np.array([r['max_aspect']>=aspect and r[feature]>=qfloor for r in usable]) if feature=='quality' else np.ones(len(y),bool)
        options=[{'quantile':v,'operating':selected(y[train],q[train],float(np.quantile(q[positive],v)),admitted[train],g[train]),'log_loss':0} for v in [.10,.25,.50]]
        choice=choose(options)
        return {'member':choice['operating']['threshold'],'broad':qfloor,'aspect':aspect,'anchor':anchor,'choice':choice,'settings':options},admitted
    gates=np.zeros(len(y),bool);details=[]
    for f in range(5):
        train=fold!=f;test=~train;p,admitted=thresholds(train);gates[test]=(q[test]>=p['member'])&admitted[test]
        details.append({'fold':f,'train':int(train.sum()),'test':int(test.sum()),'group_overlap':len(set(g[train])&set(g[test])),'parameters':p,'test_operating':selected(y[test],q[test],p['member'],admitted[test],g[test])})
    params,admitted=thresholds(np.ones(len(y),bool));tp=int(np.sum(gates&(y==1)));fp=int(np.sum(gates&(y==0)))
    return {'feature':feature,'labels':dict(Counter(r['label'] for r in known)),'binary_n':len(y),'binary_groups':len(set(g)),'folds':details,'final':params,
      'outer':{'selected':tp+fp,'reasonable':tp,'unrelated':fp,'unrelated_fraction':fp/(tp+fp) if tp+fp else None},'raw_score_descriptive_metrics':metrics(y,q),
      'probability':False,'human_labels':0,'sampling_limit':'Previously selected machine call-person labels; not representative human or aspect-level ground truth.'}

def analyze(cloud):
    found,receipt=adopt(cloud);write(DOC/'receipts'/('d3-vectors-'+str(receipt['cloud_run'])+'.json'),receipt)
    if receipt['missing']:print(json.dumps(receipt));return
    bundle=read(DOC/'prepared/d1/bundle.json');people=profiles(policy());sources={s['id']:s for s in bundle['scopes'] if s['prepared']}
    original=np.frombuffer((DOC/'prepared/d1/vectors.f32').read_bytes(),dtype='<f4').reshape(-1,1024).astype(np.float64)
    mappings=read(ROOT/'outputs/team-recommender-d2/judge-item-map-d2.json');grades=read(ROOT/'outputs/team-recommender-d2/analysis-34510982749.json')['labels']
    labels={(u['scope_id'],u['value']['candidates'][0]):grades.get(k,{}).get('label','missing') for k,u in mappings['unique'].items() if u['value']['task_type']=='call_person'}
    groupmap=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map'];assignments=groups_fold([groupmap.get(s,s) for s in sources],'D3-outer',5)
    arms={};owned={p['id']:p for p in bundle['people']}
    for arm in ['E0-C','E1','E2','E3']:
        model=CONTEXT_MODEL if arm=='E3' else STANDARD_MODEL
        def query(item):return original[item['vector']] if arm=='E0-C' else found[model,'query',digest(item['text'])].astype(np.float64)
        docs={}
        for pid,p in owned.items():
            if arm=='E0-C':docs[pid]=np.array([original[v['vector']] for v in p['passages']])
            elif arm=='E1':docs[pid]=np.array([found[model,'document',digest(v['text'])] for v in p['passages']],dtype=np.float64)
            elif arm=='E2':docs[pid]=np.array([found[model,'document',digest(people[pid]['combined'])]],dtype=np.float64)
            else:
                v=people[pid];did=digest(canonical(v['chunks']));lookup={a['text']:i for i,a in enumerate(v['attribution']) if a['field']=='claims'}
                docs[pid]=np.array([found[model,'document',digest(canonical([did,lookup[v['text']],people[pid]['chunks'][lookup[v['text']]]]))] for v in p['passages']],dtype=np.float64)
        scopes=[];allrows=[]
        for source in bundle['scopes']:
            if not source['prepared']:scopes.append({'id':source['id'],'status':'unprepared'});continue
            aspects=sorted(source['aspects'],key=lambda a:a['id']);qs=np.array([query(source['core']),query(source['whole_call']),*[query(a) for a in aspects]])
            rows=[]
            for pid,p in sorted(owned.items()):
                scores=np.clip(np.einsum('ik,jk->ij',qs,docs[pid],optimize=False),0,1);core=float(scores[0].max());baseline=float(scores[1].max());aspect=scores[2:];maximum=float(aspect.max())
                # Repeat a global vector across original passage attribution, never synthesize a claim.
                if arm=='E2':aspect=np.repeat(aspect,len(p['passages']),axis=1);c=np.repeat(scores[0],len(p['passages']))
                else:c=scores[0]
                row={'id':pid,'scope_id':source['id'],'group':groupmap.get(source['id'],source['id']),'core':core,'baseline':baseline,'max_aspect':maximum,'quality':.7*maximum+.3*baseline,
                  'passage_core':c.tolist(),'aspect_passages':aspect.tolist(),'global_representation':arm=='E2'}
                rows.append(row);allrows.append(row)
            scopes.append({'id':source['id'],'status':'prepared','rows':rows})
        fit=calibrate(allrows,labels,'quality',assignments);basefit=calibrate(allrows,labels,'baseline',assignments)
        arms[arm]={'fit':fit,'baseline_fit':basefit,'scopes':scopes}
        print(json.dumps({'arm':arm,'outer':fit['outer'],'parameters':{k:v for k,v in fit['final'].items() if k not in {'choice','settings'}},'baseline_outer':basefit['outer']}))
    write(OUT/'matrices-calibration.json',{'version':'D3-common-calibration-v1','arms':arms,'fold_assignments':assignments,'provider_calls':0,'holdout_scored':False})
    write(DOC/'receipts/d3-calibration.json',{'arms':{arm:{'fit':a['fit'],'baseline_fit':a['baseline_fit']} for arm,a in arms.items()},'fold_assignments':assignments,'provider_calls':0,'holdout_scored':False})
    # Exact adopted numeric inputs stay private until one representation earns a public package.
    keys=sorted(found);np.savez(OUT/'adopted-vectors.npz',vectors=np.stack([found[k] for k in keys]));write(OUT/'adopted-vector-keys.json',keys)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cloud',type=Path);a=p.parse_args();analyze(a.cloud)
