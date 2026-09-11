"""Apply individually authored source audits with stable identities and history.

No model, retrieval, eligibility change or generated-asset edit occurs here.
The current canonical registry is the only editable production profile source.
"""
from __future__ import annotations
import argparse, copy, datetime, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.researcher_registry import load_registry,content_hash,material_claim_hash,registry_generation,validate_registry,_write_json,pool_state
from tools.researcher_source_audit import sha
OUT=ROOT/'outputs/researcher-profile-repair'

def evidence(person,support,reviewed_on):
    result=[]
    for ref in support:
        source_index,*numbers=ref;url=person['source_urls'][source_index]
        p=OUT/'sources'/(sha(url.encode())+'.json');source=json.loads(p.read_bytes())
        if not source.get('fetched_at') or not numbers or any(not isinstance(n,int) or n<1 or n>len(source['lines']) for n in numbers):
            raise ValueError(f'Invalid source locator for {person["researcher_id"]}: {ref}')
        kind='official_profile' if source_index==0 or ('rochester.edu/' in url and any(x in url for x in ['/people/','/about/faculty/'])) else 'attributed_publication' if any(x in url.lower() for x in ['publication','paper','journals.','doi.org']) else 'researcher_group'
        if any(part in url for part in ['/newscenter/','/news-events/colloquia/','/news-events/events/','/education/graduate/news/']) and 'rochester.edu/' in url:kind='institutional_research_report'
        if ('www.lle.rochester.edu/news/' in url or 'www.lle.rochester.edu/publications/lle-in-focus/' in url or '/industrial-associates/' in url):kind='institutional_research_report'
        result.append({'url':url,'form':'paraphrase','source_type':kind,'response_sha256':source['response_sha256'],'text_sha256':source['text_sha256'],
            'retrieved_at':source['fetched_at'],'reviewed_on':reviewed_on,'locator':f'text-extraction-v{source["text_extraction_version"]} lines '+','.join(map(str,numbers))})
    return result

def apply_audit(old,item,reviewed_on):
    p=copy.deepcopy(old);claims={c['claim_id']:copy.deepcopy(c) for c in old['claims']};used=set();highest=max((int(c['claim_id'][-3:]) for c in old['claims']),default=0)
    if pool_state(old) in {'main','standby'}:p['pool_assignment']=pool_state(old)
    if item.get('disposition')=='unresolved' and 'summary' not in item:return p
    p['source_urls']=list(dict.fromkeys([*old['source_urls'],*item.get('new_source_urls',[])]))
    p['research_summary']=item['summary'];p['summary_evidence']=evidence(p,item['summary_support'],reviewed_on)
    if 'official_interests' in item:p['official_interests']=item['official_interests']
    for entry in item['claims']:
        num,label,text,category,kind,support,*optional_level=entry
        if num is None:highest+=1;num=highest
        cid=f'{p["researcher_id"]}-c{num:03d}'
        if cid in used:raise ValueError('Duplicate authored claim')
        used.add(cid);prior=claims.get(cid);records=evidence(p,support,reviewed_on)
        level=optional_level[0] if optional_level else ('corroborated' if any(r['source_type'] in {'attributed_publication','institutional_research_report'} for r in records) else 'direct')
        claim={'claim_id':cid,'revision':(prior['revision']+1 if prior else 1),'status':'active','label':label,'evidence':text,'category':category,'categories':[category],'type':kind,
            'source_urls':list(dict.fromkeys(r['url'] for r in records)),'evidence_level':level,'verified_on':reviewed_on,'legacy_claim_ids':prior.get('legacy_claim_ids',[]) if prior else [],'evidence_records':records}
        if prior:claim['history']=[*prior.get('history',[]),{k:v for k,v in prior.items() if k!='history'}]
        claim['material_hash']=material_claim_hash(claim);claims[cid]=claim
    for cid,prior in list(claims.items()):
        if cid in used or prior['status']=='retired':continue
        reason=item.get('retire_reasons',{}).get(str(int(cid[-3:])))
        if not reason:raise ValueError(f'Explicit disposition required for omitted active claim {cid}')
        c=copy.deepcopy(prior);c['history']=[*prior.get('history',[]),{k:v for k,v in prior.items() if k!='history'}];c.update(status='retired',revision=prior['revision']+1,retired_on=reviewed_on,retirement_reason=reason);c['material_hash']=material_claim_hash(c);claims[cid]=c
    p['claims']=list(claims.values());p['source_checked_date']=reviewed_on
    p['source_audit']={'version':'full-profile-repair-v1','reviewed_on':reviewed_on,'disposition':item.get('disposition','corrected'),'baseline_material':content_hash(old),'issues':item['issues'],'limitations':item.get('limitations','')}
    return p

def main():
    args=argparse.ArgumentParser();args.add_argument('--complete',action='store_true');parsed=args.parse_args()
    base=load_registry(OUT/'baseline-registry.json');current=load_registry(ROOT/'config/researcher_registry.json');by_id={p['researcher_id']:p for p in base['researchers']};current_ids={p['researcher_id'] for p in current['researchers']}
    if set(by_id)!=current_ids:raise ValueError('Roster changed during audit; explicitly incorporate every new identity before applying')
    items=[i for file in sorted(OUT.glob('review_batch_*.json')) for i in json.loads(file.read_bytes())]
    if len({i['id'] for i in items})!=len(items):raise ValueError('Duplicate authored person audit')
    if parsed.complete and {i['id'] for i in items}!=set(by_id):raise ValueError('Every canonical record needs an individual audit disposition')
    date_path=OUT/'review-date.json'
    if not date_path.exists():_write_json(date_path,{'date':datetime.datetime.now(datetime.timezone.utc).date().isoformat()})
    day=json.loads(date_path.read_bytes())['date'];updates={i['id']:apply_audit(by_id[i['id']],i,day) for i in items}
    for p in current['researchers']:
        original=by_id[p['researcher_id']]
        if p!=original and not p.get('source_audit',{}).get('baseline_material')==content_hash(original):raise ValueError('Unrelated concurrent researcher edits must be preserved')
    changed=copy.deepcopy(current);changed['researchers']=[updates.get(p['researcher_id'],p) for p in current['researchers']];changed['registry_generation']=registry_generation(changed);validate_registry(changed)
    _write_json(ROOT/'config/researcher_registry.json',changed)
    _write_json(OUT/'review-progress.json',{'population':len(by_id),'authored_audits':len(items),'remaining_ids':sorted(set(by_id)-set(updates)),'registry_generation':changed['registry_generation'],'paid_calls':0})
    print(json.dumps({'population':len(by_id),'authored_audits':len(items),'remaining':len(by_id)-len(items),'registry_generation':changed['registry_generation']}))

if __name__=='__main__':main()
