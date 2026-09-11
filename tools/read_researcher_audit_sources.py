"""Display complete retained public source text for an individual manual audit."""
import hashlib, json, pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/researcher-profile-repair'
roster=json.loads((OUT/'baseline-registry.json').read_bytes())['researchers']
start=int(sys.argv[1]);end=int(sys.argv[2]) if len(sys.argv)>2 else start+1
for i in range(start,end):
    r=roster[i]
    print('\nPERSON',i,r['researcher_id'],r['display_name'],r.get('primary_unit'))
    print('BEFORE',r['research_summary'])
    print('CLAIMS',[(c['claim_id'][-3:],c['label'],c['evidence']) for c in r['claims'] if c['status']=='active'])
    print('SOURCES',list(enumerate(r['source_urls'])))
    source_indices=list(map(int,sys.argv[3:])) or [0]
    for index in source_indices:
        url=r['source_urls'][index];path=OUT/'sources'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if not path.exists():print('NOT RETRIEVED',index,url);continue
        doc=json.loads(path.read_bytes());print('SOURCE',index,url,doc.get('status'),doc.get('error',''))
        for n,line in enumerate(doc.get('lines',[]),1):print(f'{n}: {line}')
