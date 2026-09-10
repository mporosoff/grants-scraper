"""Nested grouped call-person development calibration, not a provider or judge."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.special import expit
from tools.team_recommender_learning import fit_logistic, metrics

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender';OUT=ROOT/'outputs/team-recommender-d2'
FEATURES=['maximum_aspect_cosine','core_at_best_aspect','lexical_at_best_aspect','maximum_whole_call_cosine','mean_top_two_aspect_cosines']
def read(p):return json.loads(p.read_bytes())
def write(p,d):
    assert not p.exists(),str(p)
    p.write_bytes((json.dumps(d,sort_keys=True,indent=2)+'\n').encode())
def groups_fold(groups,prefix,n):
    ordered=sorted(set(groups),key=lambda g:hashlib.sha256((prefix+'|'+g).encode()).hexdigest())
    return {g:i%n for i,g in enumerate(ordered)}
def r0_features(row):
    best=[max(edges,key=lambda e:(e['features'][0],e['features'][1],tuple(-ord(c) for c in e['claim_id']))) for edges in row['raw_aspects']]
    chosen=max(best,key=lambda e:(e['features'][0],e['features'][1],tuple(-ord(c) for c in e['claim_id'])))
    two=sorted((e['features'][0] for e in best),reverse=True)[:2]
    f=chosen['features'];return [f[0],f[1],f[4],row['baseline'],sum(two)/len(two)]
def fit(x,y,C):
    mean=x.mean(0);scale=x.std(0);scale[scale<1e-12]=1
    a=np.column_stack([np.ones(len(x)),(x-mean)/scale]);penalty=np.full(a.shape[1],1/C);penalty[0]=.04
    beta,h,g,ok,it=fit_logistic(a,y,penalty)
    assert ok and g<1e-6 and np.isfinite(beta).all(),(ok,g,it)
    return {'C':C,'mean':mean.tolist(),'scale':scale.tolist(),'coefficients':beta.tolist(),'gradient_max':g,'iterations':it}
def predict(model,x):
    a=np.column_stack([np.ones(len(x)),(x-np.asarray(model['mean']))/np.asarray(model['scale'])])
    return expit(np.einsum('ij,j->i',a,np.asarray(model['coefficients']),optimize=False))
def selected(y,p,threshold,admitted,groups):
    use=(p>=threshold)&admitted;tp=int(np.sum(use&(y==1)));fp=int(np.sum(use&(y==0)));n=tp+fp
    return {'threshold':threshold,'n':n,'positive':tp,'unrelated':fp,'unrelated_fraction':fp/n if n else None,
       'source_groups':len(set(groups[use])),'recall_of_sampled_positives':tp/int(y.sum()) if y.sum() else None}
def choose(candidates):
    qualified=[c for c in candidates if c['operating']['n']>=10 and c['operating']['source_groups']>=3 and c['operating']['unrelated_fraction']<=.05]
    def score(c):
        o=c['operating'];return (o['positive'] if qualified else o['positive']-4*o['unrelated'],-o['unrelated'],o['threshold'],-c['log_loss'],-c.get('C',0))
    result=max(qualified or candidates,key=score)
    return {**result,'selection_target_met':bool(qualified)}
def bins(y,p):
    result=[]
    for lo,hi in [(0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000000001)]:
        use=(p>=lo)&(p<hi)
        result.append({'lower':lo,'upper':min(hi,1),'n':int(use.sum()),'mean_score':float(p[use].mean()) if use.any() else None,'positive_fraction':float(y[use].mean()) if use.any() else None})
    return result
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--representation',choices=['R0','R1'],required=True);parser.add_argument('--features',type=Path);args=parser.parse_args()
    raw=read(OUT/'D1-reproduction.json');mapping=read(ROOT/'outputs/team-recommender-d1/judge-item-map-d1.json');labels=read(ROOT/'outputs/team-recommender-d1/analysis-34497056168.json')['labels']
    groupmap=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map']
    alternate=read(args.features) if args.features else None
    alternate_rows={(s['id'],r['id']):r['call_features'] for s in alternate['scopes'] if s['status']!='unprepared' for r in s['rows']} if alternate else {}
    allrows=[]
    for s in raw['scopes']:
        if s['status']=='unprepared':continue
        for r in s['rows']:
            allrows.append({'scope_id':s['id'],'person_id':r['id'],'group':groupmap.get(s['id'],s['id']),
                'features':alternate_rows[s['id'],r['id']] if alternate else r0_features(r),'admitted':r['id'] in s['admitted']})
    lookup={(r['scope_id'],r['person_id']):r for r in allrows}
    examples=[]
    for key,u in mapping['unique'].items():
        if u['value']['task_type']!='call_person':continue
        row=lookup[u['scope_id'],u['value']['candidates'][0]]
        examples.append({**row,'key':key,'label':labels.get(key,{}).get('label','missing')})
    usable=[r for r in examples if r['label'] in {'strong','plausible','unrelated'}]
    assert len(usable)>=20 and len({r['group'] for r in usable})>=5 and len({r['label']=='unrelated' for r in usable})==2
    x=np.asarray([r['features'] for r in usable]);y=np.asarray([r['label']!='unrelated' for r in usable],float)
    group=np.asarray([r['group'] for r in usable]);admitted=np.asarray([r['admitted'] for r in usable]);fixed=.7*x[:,0]+.3*x[:,3]
    assignments=groups_fold([r['group'] for r in allrows],'D2-outer',5);fold=np.asarray([assignments[g] for g in group])
    learned=np.full(len(y),np.nan);fixed_gate=np.zeros(len(y),bool);learned_gate=np.zeros(len(y),bool);details=[];models=[]
    for f in range(5):
        train=fold!=f;test=~train;gx=group[train];tx=x[train];ty=y[train];ta=admitted[train]
        inner=groups_fold(gx,'D2-inner-'+str(f),3);innerfold=np.asarray([inner[g] for g in gx]);options=[]
        for C in [.1,1.]:
            predictions=np.full(len(ty),np.nan)
            for j in range(3):
                a=innerfold!=j;b=~a;assert len(set(ty[a]))==2
                predictions[b]=predict(fit(tx[a],ty[a],C),tx[b])
            assert np.isfinite(predictions).all()
            for threshold in [.65,.8]:options.append({'C':C,'operating':selected(ty,predictions,threshold,ta,gx),'log_loss':metrics(ty,predictions)['log_loss']})
        choice=choose(options);model=fit(tx,ty,choice['C']);pred=predict(model,x[test]);learned[test]=pred
        fchoices=[{'operating':selected(ty,fixed[train],t,ta,gx),'log_loss':metrics(ty,fixed[train])['log_loss']} for t in [.45,.5]]
        fchoice=choose(fchoices)
        fixed_gate[test]=(fixed[test]>=fchoice['operating']['threshold'])&admitted[test]
        learned_gate[test]=(pred>=choice['operating']['threshold'])&admitted[test]
        details.append({'fold':f,'train':int(train.sum()),'test':int(test.sum()),'train_groups':len(set(group[train])),'test_groups':len(set(group[test])),
            'group_overlap':len(set(group[train])&set(group[test])),'learned_choice':choice,'fixed_choice':fchoice,'inner_candidates':options,
            'fixed_test':selected(y[test],fixed[test],fchoice['operating']['threshold'],admitted[test],group[test]),
            'learned_test':selected(y[test],pred,choice['operating']['threshold'],admitted[test],group[test]),'model':model})
        models.append(model)
    def operating_summary(mask):
        tp=int(np.sum(mask&(y==1)));fp=int(np.sum(mask&(y==0)))
        return {'n':int(mask.sum()),'positive':tp,'unrelated':fp,'unrelated_fraction':fp/int(mask.sum()) if mask.any() else None,'groups':len(set(group[mask]))}
    fixed_stats=metrics(y,fixed);learned_stats=metrics(y,learned);fs=operating_summary(fixed_gate);ls=operating_summary(learned_gate)
    learned_wins=learned_stats['brier']<=fixed_stats['brier']-.02 and ls['positive']>fs['positive'] and ls['unrelated_fraction'] is not None and fs['unrelated_fraction'] is not None and ls['unrelated_fraction']<=fs['unrelated_fraction']
    # The final refit choice comes from inner choices plus outer OOF operating results,
    # not from claiming full-fit predictions are independent performance.
    final_options=[]
    c_oof={}
    for C in [.1,1.]:
        p=np.full(len(y),np.nan)
        for f in range(5):
            a=fold!=f;b=~a;p[b]=predict(fit(x[a],y[a],C),x[b])
        c_oof[C]=p
        for t in [.65,.8]:final_options.append({'C':C,'operating':selected(y,p,t,admitted,group),'log_loss':metrics(y,p)['log_loss']})
    lchoice=choose(final_options);fchoice=choose([{'operating':selected(y,fixed,t,admitted,group),'log_loss':fixed_stats['log_loss']} for t in [.45,.5]])
    final_model=fit(x,y,lchoice['C']);allx=np.asarray([r['features'] for r in allrows]);pall=predict(final_model,allx)
    oof_all=np.full(len(allrows),np.nan)
    for f,model in enumerate(models):
        mask=np.asarray([assignments[r['group']]==f for r in allrows]);oof_all[mask]=predict(model,allx[mask])
    for r,p,op in zip(allrows,pall,oof_all):
        r['fixed_quality']=.7*r['features'][0]+.3*r['features'][3];r['learned_full_fit_quality']=float(p);r['learned_outer_fold_quality']=float(op);r['fold']=assignments[r['group']]
    result={'protocol':'D2-nested-call-person','representation':args.representation,'feature_order':FEATURES,
        'event':'D1 call-person worth discussing for at least one call contribution; strong/plausible vs unrelated',
        'label_provenance':'Actual cached D1 model judgments; sampled by earlier algorithms; no human labels or aspect-level truth',
        'labels':dict(Counter(r['label'] for r in examples)),'binary_n':len(y),'binary_source_groups':len(set(group)),
        'prepared_scopes':35,'all_directory_rows':len(allrows),'fold_assignments':assignments,'folds':details,
        'fixed':{'metrics':fixed_stats,'operating':fs,'bins':bins(y,fixed)},
        'regularized':{'metrics':learned_stats,'operating':ls,'bins':bins(y,learned)},
        'family_choice':'regularized' if learned_wins else 'fixed','selection_rule':'predeclared Brier improvement >=.02 plus greater positive yield and no higher unrelated rate',
        'final_fixed_operating':fchoice,'final_learned_operating':lchoice,'final_model':final_model,'final_refit_setting_comparison':final_options,
        'OOF_examples':[{**r,'fixed_score':float(fixed[i]),'learned_outer_fold_score':float(learned[i]),'fixed_automatic':bool(fixed_gate[i]),'learned_automatic':bool(learned_gate[i])} for i,r in enumerate(usable)],
        'all_rows':allrows,'limits':'Nested outer-fold estimates are selected-machine-label development only. Full refit scores are in-sample for old labels. New D2 judgments do not retune this fit. Fixed raw-score Brier is descriptive, not a calibrated probability claim.',
        'Bayesian':'Not evaluated; optional, no numerical ambiguity requiring an additional comparison.','provider_calls':0,'holdout_scored':False}
    write(OUT/('fit-'+args.representation+'.json'),result)
    public={k:v for k,v in result.items() if k not in {'OOF_examples','all_rows'}}
    write(DOC/('receipts/d2-fit-'+args.representation+'.json'),public)
    print(json.dumps({k:result[k] for k in ['representation','labels','binary_n','binary_source_groups','fixed','regularized','family_choice','final_fixed_operating','final_learned_operating']},indent=2))

if __name__=='__main__':main()
