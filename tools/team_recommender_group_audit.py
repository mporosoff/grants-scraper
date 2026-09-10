"""Source-only correction overlay. Never imports or computes recommendations."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT/'docs/team-recommender'

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def catalog():
    text=(ROOT/'data/opportunities.js').read_text(encoding='utf-8')
    return json.loads(text[text.index('{'):text.rfind('}')+1])['opportunities']

def audit():
    original={n:json.loads((DOC/'manifests'/n).read_bytes()) for n in ['source-groups.json','development.json','holdout.json','rollout.json']}
    records=original['source-groups.json']['records']; parents={r['opportunity_id']:r for r in catalog()}
    uf={p:p for p in parents}; links=[]
    def root(x):
        while uf[x]!=x:x=uf[x]
        return x
    def union(a,b,reason):
        if a not in uf or b not in uf:return
        x,y=root(a),root(b)
        if x!=y:uf[max(x,y)]=min(x,y);links.append({'a':a,'b':b,'reason':reason})
    for r in records:union(r['parent_id'],r['group_id'],'preserved-original-group')
    seen={}
    def key(k,p):
        if k in seen:union(p,seen[k],k)
        else:seen[k]=p
    for pid,r in parents.items():
        number=r.get('opportunity_number') or ''
        agency=(r.get('agency') or '').lower()
        if 'science foundation' in agency or r.get('agency_code')=='NSF' or pid.startswith('nsf-funding:'):
            match=re.fullmatch(r'(?:NSF[- ]?)?(\d{2})-(\d{3})',number,re.I)
            if match:key('NSF-solicitation:'+''.join(match.groups()),pid)
        # ROSES/SpaceTech appendices share an explicit omnibus parent.
        match=re.match(r'(NNH\d{2}Z(?:DA|TR)\d{3}N)',number,re.I)
        if not match and pid.startswith('nasa-roses:'):
            match=re.match(r'nasa-roses:(\d{2})-',pid)
            if match:key('NASA-omnibus:NNH'+match[1]+'ZDA001N',pid)
        elif match:key('NASA-omnibus:'+match[1].upper(),pid)
        # Conservatively group same-cycle CDMRP award mechanisms within the
        # explicitly named disease program, without merging different diseases.
        match=re.match(r'(HT9425\d{2}[A-Z]+?RP)',number)
        if match:key('CDMRP-program-cycle:'+match[1],pid)
        url=r.get('funding_opportunity_url') or ''
        parsed=urlsplit(url)
        if parsed.hostname in ('www.nsf.gov','nsf.gov'):
            match=re.search(r'/funding/opportunities/([^/]+)',parsed.path)
            if match:key('NSF-program:'+match[1],pid)
            old=parse_qs(parsed.query).get('ods_key',[''])[0]
            if re.fullmatch(r'nsf\d{5}',old):key('NSF-solicitation:'+old[3:],pid)
    # Source descriptions explicitly identify the same doctorate-training
    # population/purpose; retain forecast as a successor, not an unseen call.
    union('358114','362597','NIDCD-audiologist-research-doctorate-successor-source-audit')
    union('361207','361208','same-NIDCD-Human-Ear-Resource-Network-components')
    numbers={r.get('opportunity_number'):pid for pid,r in parents.items() if r.get('opportunity_number')}
    for pid,r in parents.items():
        description=r.get('description') or ''
        for match in re.finditer(r'(?:PAR|PA|RFA)-[A-Z0-9-]{5,12}',description):
            if match[0] in numbers and re.search(r'companion|parallel|collaborating|reissuance|replaces',description[max(0,match.start()-180):match.end()+180],re.I):
                union(pid,numbers[match[0]],'explicit-companion-or-successor:'+match[0])
    dev=original['development.json']['scopes']; hold=original['holdout.json']['scopes']
    devgroups={root(s['parent_id']) for s in dev}
    exposed={root(s['parent_id']) for s in records if s['historically_exposed']}
    keep=[];removed=[];used=set(devgroups)|exposed
    for s in hold:
        group=root(s['parent_id'])
        if group in used:removed.append({'original':s,'reason':'development/exposed/source-related-group' if group in devgroups|exposed else 'duplicate-within-holdout','corrected_group':group})
        else:keep.append({**s,'group_id':group});used.add(group)
    # Original candidate eligibility and original split assignment are preserved.
    # Replacements are same-family first, then original SHA order; no outputs.
    pool=sorted([r for r in records if r['source_candidate'] and not r['historically_exposed'] and int(sha('team-stage1-split-v2|'+r['group_id'])[:8],16)%2],key=lambda r:sha('team-stage1-v2|'+r['id']))
    for disposition in removed:
        old=disposition['original']
        available=[r for r in pool if root(r['parent_id']) not in used]
        available.sort(key=lambda r:(r['family']!=old['family'],sha('team-stage1-v2|'+r['id'])))
        replacement=available[0] if available else None
        if replacement:
            replacement={**replacement,'group_id':root(replacement['parent_id'])};keep.append(replacement);used.add(replacement['group_id'])
        disposition['replacement']=replacement
    mapped={x['original']['id']:x['replacement'] for x in removed}
    effective=[]
    for s in hold:
        replacement=mapped.get(s['id'],s)
        if replacement:effective.append({**replacement,'group_id':root(replacement['parent_id'])})
    assert not devgroups & {s['group_id'] for s in effective}
    assert len({s['group_id'] for s in effective})==len(effective)
    controls=[]
    for control in original['holdout.json']['controls']:
        s=mapped.get(control['origin_scope_id'])
        controls.append({**control,**({'case_id':s['id']+'#control-'+control['kind'],'origin_scope_id':s['id'],'parent_id':s['parent_id'],'group_id':s['group_id'],'original_case_id':control['case_id']} if s else {'group_id':root(control['parent_id'])})})
    return {'version':'C2-source-group-overlay-1','selection_uses_recommendations':False,'recommendation_outputs_exist':False,
        'original_hashes':{n:sha((DOC/'manifests'/n).read_bytes()) for n in original},
        'audit_parent_count':len(parents),'cross_split_pairs_screened':len(dev)*len(hold),
        'rules':['preserve original groups','canonical NSF solicitation/program','NASA omnibus ownership','same-cycle CDMRP program conservatively grouped','explicit NIH companions','audited NIDCD successor/network'],
        'links':links,'dispositions':removed,'replacement_rule':'original source_candidate and original holdout hash assignment; exclude corrected development/exposed/selected groups; same family then SHA256(team-stage1-v2|id)',
        'development_scopes':[{**s,'group_id':root(s['parent_id'])} for s in dev],
        'development_controls':[{**s,'group_id':root(s['parent_id'])} for s in original['development.json']['controls']],
        'holdout_scopes':effective,'holdout_controls':controls,'development_groups':len(devgroups),
        'holdout_groups':len(effective),'remaining_group_overlap':0,
        'source_group_map':{pid:root(pid) for pid in parents},'limitations':'Source metadata, original synopses and explicit program relationships; not a proof against every semantic similarity. No recommendation/label-driven substitution.'}

if __name__=='__main__':
    value=audit();raw=(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
    output=DOC/'manifests'/('source-group-amendment-c2-'+sha(raw)[:16]+'.json')
    if output.exists() and output.read_bytes()!=raw:raise ValueError('immutable_overlay_conflict')
    output.write_bytes(raw)
    print(json.dumps({'path':str(output),'sha256':sha(raw),'development':len(value['development_scopes']),'development_groups':value['development_groups'],'holdout':len(value['holdout_scopes']),'replaced':len(value['dispositions']),'pairs_screened':value['cross_split_pairs_screened']}))
