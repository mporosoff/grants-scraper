"""Compact, grouped development comparisons on the same noisy judge event.

No provider calls. No holdout scores. No fitted asset is implicitly deployed.
"""
import json,time,hashlib
import numpy as np
from scipy.special import expit,roots_hermite
from scipy.linalg import solve,cholesky

def fit_logistic(a,target,penalty):
    """Bounded Newton/IRLS for this convex nine-parameter objective.

    Explicit contractions avoid a stalled local dense-BLAS matrix-product path.
    The objective, Gaussian/ridge prior and convergence test are unchanged.
    """
    beta=np.zeros(a.shape[1]);converged=False
    def loss(b):
        z=np.einsum('ij,j->i',a,b,optimize=False)
        return float(np.sum(np.logaddexp(0,z)-target*z)+.5*np.sum(penalty*b*b))
    for iteration in range(80):
        q=expit(np.einsum('ij,j->i',a,beta,optimize=False))
        gradient=np.sum(a*(q-target)[:,None],axis=0)+penalty*beta
        h=np.einsum('ni,n,nj->ij',a,q*(1-q),a,optimize=False)+np.diag(penalty)
        if np.max(np.abs(gradient))<1e-7:converged=True;break
        step=solve(h,gradient,assume_a='pos');old=loss(beta)
        for power in range(25):
            trial=beta-step*2.**(-power)
            if loss(trial)<=old-1e-4*2.**(-power)*float(np.sum(gradient*step)):
                beta=trial;break
        else:break
    q=expit(np.einsum('ij,j->i',a,beta,optimize=False))
    gradient=np.sum(a*(q-target)[:,None],axis=0)+penalty*beta
    h=np.einsum('ni,n,nj->ij',a,q*(1-q),a,optimize=False)+np.diag(penalty)
    return beta,h,float(np.max(np.abs(gradient))),converged,iteration+1

def metrics(y,p):
    p=np.clip(p,1e-8,1-1e-8);pos=p[y==1];neg=p[y==0]
    auc=float(np.mean([(a>b)+.5*(a==b) for a in pos for b in neg])) if len(pos) and len(neg) else None
    return {'n':len(y),'positive':int(y.sum()),'negative':int(len(y)-y.sum()),'brier':float(np.mean((p-y)**2)),
            'log_loss':float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),'auc':auc,
            'unrelated_among_p_ge_half':int(np.sum((p>=.5)&(y==0))),'p_ge_half_denominator':int(np.sum(p>=.5))}

def compare(examples):
    usable=[r for r in examples if r['label'] in ('strong','plausible','unrelated')]
    base={'event':'Worth discussing for this scoped contribution using the available public evidence',
      'label_provenance':'claude-sonnet-5 noisy development judgments; not human or capability probabilities',
      'all_individual_labels':len(examples),'insufficient_information':sum(r['label']=='insufficient-information' for r in examples),
      'binary_usable':len(usable),'groups':len({r['group_id'] for r in usable}),
      'feature_order':['aspect_cosine','core_cosine','operation_overlap','context_overlap','lexical_overlap','missing_operation','missing_context','generic_profile'],
      'limits':'Items were selected by the frozen initial algorithms and controls. The label concerns the bounded source/profile conversation, while features summarize the best fixed aspect. Calibration is against selected machine labels only. The same grouped folds compare the compact grid; grid selection is development analysis, not independent validation. No new group-coherence judgments are inferred from person-label fitting.'}
    if len(usable)<20 or base['groups']<5 or len({r['label']=='unrelated' for r in usable})<2:
        return {**base,'status':'insufficient-groups-or-classes-for-meaningful-fit','models':[]}
    X=np.asarray([r['features'] for r in usable],float);y=np.asarray([r['label']!='unrelated' for r in usable],float)
    groups=sorted({r['group_id'] for r in usable},key=lambda g:hashlib.sha256(('C2-learning-fold|'+g).encode()).hexdigest())
    assignments={g:i%5 for i,g in enumerate(groups)};folds=np.asarray([assignments[r['group_id']] for r in usable]);base['fold_assignment']=assignments
    nodes,weights=roots_hermite(20);models=[]
    for kind,values in [('regularized',[.1,1,10]),('bayesian',[.5,1,2])]:
        for value in values:
            start=time.perf_counter();pred=np.full(len(y),np.nan);fold_details=[];parameters=[];fold_models=[]
            for fold in range(5):
                train=folds!=fold;test=~train
                if not test.any() or len(np.unique(y[train]))<2:fold_details.append({'fold':fold,'status':'missing-class-or-test'});continue
                mean=X[train].mean(0);sd=X[train].std(0);sd[sd<1e-12]=1
                a=np.column_stack([np.ones(train.sum()),(X[train]-mean)/sd]);b=np.column_stack([np.ones(test.sum()),(X[test]-mean)/sd]);target=y[train]
                strength=1/value if kind=='regularized' else 1/value**2
                penalty=np.full(a.shape[1],strength);penalty[0]=1/25 # identical weak intercept prior
                beta,h,gradient,converged,iterations=fit_logistic(a,target,penalty)
                eye=np.eye(h.shape[0]);cov=np.column_stack([solve(h,eye[:,i],assume_a='pos') for i in range(h.shape[0])]);chol=cholesky(h)
                mu=np.einsum('ij,j->i',b,beta,optimize=False);p=expit(mu)
                if kind=='bayesian':
                    variance=np.maximum(0,np.einsum('ij,jk,ik->i',b,cov,b))
                    p=np.sum(weights*expit(mu[:,None]+np.sqrt(2*variance)[:,None]*nodes),axis=1)/np.sqrt(np.pi)
                pred[test]=p;parameters.append(beta.tolist());fold_models.append({'fold':fold,'mean':mean.tolist(),'scale':sd.tolist(),'coefficients':beta.tolist(),'covariance':cov.tolist() if kind=='bayesian' else None})
                fold_details.append({'fold':fold,'train':int(train.sum()),'test':int(test.sum()),'positive_train':int(target.sum()),'gradient_max':gradient,'hessian_min_cholesky_pivot':float(chol.diagonal().min()),'inverse_residual_max':float(np.max(np.abs(np.einsum('ij,jk->ik',h,cov,optimize=False)-np.eye(h.shape[0])))),'optimizer_success':converged,'iterations':iterations})
            mask=np.isfinite(pred)
            models.append({'kind':kind,'C' if kind=='regularized' else 'prior_sd':value,'metrics':metrics(y[mask],pred[mask]),'seconds':time.perf_counter()-start,
              'folds':fold_details,'coefficients_by_fold':parameters,'fold_models':fold_models,'oof_predictions':[{ 'key':r['key'],'probability_of_judge_event':float(p)} for r,p in zip(usable,pred) if np.isfinite(p)]})
    base['fixed_score_metrics']=metrics(y,np.asarray([r['fixed_score'] for r in usable]))
    base['whole_call_metrics']=metrics(y,np.asarray([r['whole_call'] for r in usable]))
    base['constant_prevalence_description']=float(y.mean())
    return {**base,'status':'evaluated-grouped-development-only','models':models,'human_calibration':'unmeasured','production_model_asset':None}
