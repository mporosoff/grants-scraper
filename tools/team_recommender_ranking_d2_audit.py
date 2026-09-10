"""Audit exact D1 question/evidence mapping and numerical failure boundaries. No dispatch."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from tools.team_recommender_evaluation_d1 import item_identity

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender'
OUT=ROOT/'outputs/team-recommender-d2'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):
    assert not p.exists()
    p.write_bytes((json.dumps(d,sort_keys=True,indent=2)+'\n').encode())
def dist(values):
    v=sorted(values)
    return {'n':len(v),'minimum':v[0] if v else None,'p25':v[int((len(v)-1)*.25)] if v else None,'median':v[len(v)//2] if v else None,'p75':v[int((len(v)-1)*.75)] if v else None,'maximum':v[-1] if v else None}

def main():
    old=ROOT/'outputs/team-recommender-d1'
    mapping=read(old/'judge-item-map-d1.json');analysis=read(old/'analysis-34497056168.json');labels=analysis['labels']
    packet=read(DOC/'packets'/(mapping['packet_sha256']+'.json'))
    contexts={};checked=0
    for request,rm in zip(packet['requests'],mapping['request_maps']):
        context=(request['source_evidence'],request['aspects'])
        if request['scope_id'] in contexts:assert contexts[request['scope_id']]==context
        contexts[request['scope_id']]=context
        by={item['item_id']:item for item in request['items']}
        for x in rm['items']:
            item={k:v for k,v in by[x['alias']].items() if k!='item_id'}
            assert item==mapping['unique'][x['key']]['value']
            assert item_identity(request['scope_id'],*context,item)==x['key']
            checked+=1
    cp={(u['scope_id'],u['value']['candidates'][0]):k for k,u in mapping['unique'].items() if u['value']['task_type']=='call_person'}
    results=read(OUT/'D1-reproduction.json');scopes={s['id']:s for s in results['scopes']}
    disagreements=[]
    for o in mapping['occurrences']:
        if o['kind']!='alternative' or o.get('arm')!='B' or labels.get(o['key'],{}).get('label') not in {'strong','plausible'}:continue
        item=mapping['unique'][o['key']]['value'];members=item['candidates'];individual=[labels.get(cp.get((o['scope_id'],p)),{}).get('label') for p in members]
        if 'unrelated' not in individual:continue
        normalized=lambda rows,p:sorted([{k:v for k,v in r.items() if k!='id'} for r in rows if r['person_id']==p],key=lambda r:r['claim_id'])
        evidence_equal=all(normalized(item['profile_evidence'],p)==normalized(mapping['unique'][cp[o['scope_id'],p]]['value']['profile_evidence'],p) for p in members)
        assert evidence_equal
        grade=labels[o['key']];ref=next((r for r in item['profile_evidence'] if r['id']==grade['evidence_ref']),None)
        ref_label=labels.get(cp.get((o['scope_id'],ref['person_id'])),{}).get('label') if ref else None
        category=('group judgment plausibly driven by one strong member' if 'strong' in individual and ref_label=='strong'
                  else 'unresolved semantic disagreement on comparable evidence')
        team=scopes[o['scope_id']]['alternatives'][o['position']-1]
        disagreements.append({'scope_id':o['scope_id'],'rank':o['position'],'group_item_key':o['key'],'group_label':grade['label'],
            'group_reason':grade['reason'],'group_evidence_ref':grade['evidence_ref'],'group_referenced_person':ref['person_id'] if ref else None,
            'individual_labels':dict(zip(members,individual)),'same_person_claim_source_identity':True,'same_per_person_passages_labels_summary':evidence_equal,
            'same_call_source_aspects':True,'different_question':'group usefulness vs call-person relevance, both exploratory; no explicit target aspect',
            'mapping_defect':False,'disposition':category,'certainty':'Plausible mechanism only; private model reasoning unavailable. Unrelated individual grade remains unrelated.',
            'coverage':team['score'],'weakest_member':team['min_strength'],'mean_member':team['mean_strength'],
            'marginals':{m['id']:m['marginal'] for m in team['members']}})
    assert len(disagreements)==9
    cutoff=[];member_occurrences=[]
    for s in scopes.values():
        if s['status']=='unprepared':continue
        if len(s['admitted'])>=2 and s['has_anchor'] and s['upper_coverage']<.45:
            graded=[labels[cp[s['id'],p]]['label'] for p in s['admitted'] if (s['id'],p) in cp and cp[s['id'],p] in labels]
            top=[]
            for row in sorted(s['rows'],key=lambda r:-r['strength'])[:5]:
                e=max(row['edges'],key=lambda e:e['score']);f=e['features']
                top.append({'person_id':row['id'],'score':row['strength'],'aspect_cosine':f[0],'core_cosine':f[1],'lexical':f[4],
                    'label':labels.get(cp.get((s['id'],row['id'])),{}).get('label','missing')})
            cutoff.append({'scope_id':s['id'],'admitted':len(s['admitted']),'coverage_upper_bound':s['upper_coverage'],'judged_admitted':dict(Counter(graded)),
                'top_people':top,'confirmed':'Universal .45 floor alone excludes all group sizes after pool/anchor checks; does not establish member usefulness.'})
        for t in s['alternatives']:
            for m in t['members']:
                member_occurrences.append({'scope_id':s['id'],'rank':t['rank'],'person_id':m['id'],'label':labels.get(cp.get((s['id'],m['id'])),{}).get('label','missing'),
                    'score':m['strength'],'coverage':t['score'],'marginal':m['marginal'],'zero_marginal':abs(m['marginal'])<1e-9,
                    'min_strength':t['min_strength'],'mean_strength':t['mean_strength']})
    assert len(cutoff)==17
    distributions={label:{'member_score':dist([m['score'] for m in member_occurrences if m['label']==label]),
       'zero_marginal':sum(m['zero_marginal'] for m in member_occurrences if m['label']==label)} for label in ['strong','plausible','unrelated','insufficient-information','missing']}
    evidence_proof={'engine_path':'assets/team-recommender.js: edge reads passage.text/vector, optional operation/context; matrix uses evidence vectors only',
      'adapter_path':'assets/team-ingredients.js: existing labels/types/research_summary retained in hydrated context and identity but not used by D1 edge scoring',
      'judge_path':'tools/team_recommender_revision_judge_packets.py: strongest whole-call passage plus admitted-aspect passages, exact associated label/type and full unchanged summary for every supplied claim',
      'finding':'confirmed numerical/evaluator context mismatch; not an identity mismatch or enrichment requirement',
      'engine_sha256':sha(ROOT/'assets/team-recommender.js'),'adapter_sha256':sha(ROOT/'assets/team-ingredients.js'),
      'packet_builder_sha256':sha(ROOT/'tools/team_recommender_revision_judge_packets.py')}
    report={'protocol':'D2 diagnosis before editing','D1_exact_reproduction':True,'reproduction_sha256':sha(OUT/'D1-reproduction.json'),
      'prepared':35,'scientific':90,'controls':30,'mapped_submitted_items':checked,'mapping_defects_found':0,
      'cutoff_only_scopes':cutoff,'cutoff_scope_count':17,'cutoff_scopes_with_judged_reasonable_admitted':sum(bool(s['judged_admitted'].get('strong',0)+s['judged_admitted'].get('plausible',0)) for s in cutoff),
      'alternative_member_occurrences':len(member_occurrences),'alternative_member_distributions':distributions,
      'unrelated_zero_marginal_occurrences':sum(m['label']=='unrelated' and m['zero_marginal'] for m in member_occurrences),
      'unrelated_positive_marginal_occurrences':sum(m['label']=='unrelated' and not m['zero_marginal'] for m in member_occurrences),
      'strong_member_carrying':'confirmed numerical degeneracy: F ignores below-max contributors; quality only breaks 1e-6 ties. A semantic cause remains inferential, not every zero marginal is bad.',
      'existing_context':evidence_proof,'nine_disagreements':disagreements,'disagreement_counts':dict(Counter(d['disposition'] for d in disagreements)),
      'judge_rubric_change_required':False,'human_judgments':0,'provider_calls':0,'holdout_scored':False}
    write(DOC/'receipts/d2-before-edit-diagnosis.json',report)
    write(OUT/'D1-judgment-audit.json',{'report':report,'member_occurrences':member_occurrences,'call_person_keys':[{'scope_id':s,'person_id':p,'key':k,'label':labels.get(k,{}).get('label')} for (s,p),k in cp.items()]})
    print(json.dumps({k:report[k] for k in ['mapped_submitted_items','cutoff_scope_count','cutoff_scopes_with_judged_reasonable_admitted','alternative_member_distributions','unrelated_zero_marginal_occurrences','unrelated_positive_marginal_occurrences','disagreement_counts','judge_rubric_change_required']},indent=2))

if __name__=='__main__':main()
