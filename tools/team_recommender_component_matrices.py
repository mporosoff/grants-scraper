"""Apply grouped out-of-fold C/D fits to the identical complete development rows."""
import json,sys
import numpy as np
from scipy.special import expit,roots_hermite
from tools.team_recommender_real_prep import OUT,DOC,write

def prepare(run):
    learned=json.loads((OUT/'analysis-private'/f'c2-learning-{run}.json').read_bytes())
    original=json.loads((OUT/'development-corrected-v2.json').read_bytes())
    base=next(c for c in original['results'] if c['id']=='bounded-middle')
    grouping=json.loads((DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json').read_bytes())['source_group_map']
    bundle=json.loads((DOC/'prepared/c2/bundle.json').read_bytes());scopes={s['id']:s for s in bundle['scopes']}
    nodes,weights=roots_hermite(20);output=[]
    for model in learned['models']:
        entry={'kind':model['kind'],'value':model.get('C',model.get('prior_sd')),'scopes':[]};folds={m['fold']:m for m in model['fold_models']}
        for scope in base['scopes']:
            sid=scope['id'];group=grouping.get(sid,sid)
            if scope['status']=='unprepared':entry['scopes'].append({'id':sid,'status':'unprepared'});continue
            if group not in learned['fold_assignment']:entry['scopes'].append({'id':sid,'status':'unmeasured-no-grouped-fold'});continue
            fit=folds[learned['fold_assignment'][group]]
            matrix=np.asarray([edge['features'] for row in scope['rows'] for edge in row['edges']],float)
            design=np.column_stack([np.ones(len(matrix)),(matrix-np.asarray(fit['mean']))/np.asarray(fit['scale'])])
            mu=np.einsum('ij,j->i',design,np.asarray(fit['coefficients']),optimize=False);prob=expit(mu)
            if model['kind']=='bayesian':
                variance=np.maximum(0,np.einsum('ij,jk,ik->i',design,np.asarray(fit['covariance']),design,optimize=False))
                prob=np.sum(weights*expit(mu[:,None]+np.sqrt(2*variance)[:,None]*nodes),axis=1)/np.sqrt(np.pi)
            at=0;rows=[]
            for row in scope['rows']:
                edges=[]
                for edge in row['edges']:
                    edges.append({'score':float(prob[at]) if edge['admitted'] else 0,'admitted':edge['admitted'],'core':edge['features'][1]});at+=1
                rows.append({'id':row['id'],'baseline':row['baseline'],'core':row['core'],'edges':edges})
            entry['scopes'].append({'id':sid,'status':'scored','fold':fit['fold'],'weights':[a['weight'] for a in sorted(scopes[sid]['aspects'],key=lambda a:a['id'])],'rows':rows})
        output.append(entry)
    write(OUT/f'component-matrices-{run}.json',{'models':output,'provider_calls':0,'scopes':90,'controls':30,'limits':'Same absolute admission/core gates and frozen B-middle group parameters. Fold predictions never train on that source group. These machine-label scores are not proven expertise probabilities; novel groups lack semantic judgments.'})
    print(json.dumps({'models':len(output),'scopes_each':90,'provider_calls':0}))
if __name__=='__main__':prepare(int(sys.argv[1]))
