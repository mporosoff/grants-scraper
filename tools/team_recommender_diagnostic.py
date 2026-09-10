"""D1 fixed historical-development trace, before any combined correction. No I/O providers."""
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/team-recommender'
OLD = ROOT / 'outputs/team-recommender-c2'
OUT = ROOT / 'outputs/team-recommender-d1'
CASES = [
    ('nasa-roses:25-D.9-d22059cf9f', 'specific-looking-unprepared: bounded source gap'),
    ('243973', 'specific-looking-unprepared: mechanism versus coherent science'),
    ('362868', 'specific-looking-unprepared: linked focus areas'),
    ('363622', 'one-aspect no-group'),
    ('361208', 'one-aspect no-group'),
    ('344592:ab-0009', 'few-aspect no-group: native child'),
    ('362218', 'few-aspect no-group: hearing'),
    ('359696', 'large admitted pool with no-group'),
    ('361207', 'existing group-producing source'),
    ('363292', 'historical unrelated admission'),
    ('357002', 'plausible imaging method transfer'),
    ('363489', 'method transfer versus generic sensor similarity'),
]


def read(p):
    return json.loads(p.read_bytes())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def immutable(p, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_bytes() != raw:
        raise ValueError('Preserve prior diagnostic result: '+str(p))
    p.write_bytes(raw)


def correlation(x, y):
    mx, my = sum(x)/len(x), sum(y)/len(y)
    xx, yy = sum((a-mx)**2 for a in x), sum((b-my)**2 for b in y)
    return sum((a-mx)*(b-my) for a,b in zip(x,y))/math.sqrt(xx*yy) if xx*yy else None


def coverage(rows, weights):
    return sum(w*max((r['edges'][i]['score'] for r in rows), default=0) for i,w in enumerate(weights))


def pair_waterfall(scope, numerical):
    rows = [r for r in numerical['rows'] if any(e['admitted'] and e['score']>0 for e in r['edges'])]
    weights = [a['weight'] for a in sorted(scope['aspects'], key=lambda a:a['id'])]
    counts = Counter(admitted_people=len(rows), possible_pairs=len(rows)*(len(rows)-1)//2)
    max_coverage = 0
    for pair in itertools.combinations(rows, 2):
        if not any(e['admitted'] and e['features'][1]>=.4 for r in pair for e in r['edges']):
            counts['first_fail_anchor']+=1; continue
        counts['passed_anchor']+=1
        value=coverage(pair,weights);max_coverage=max(max_coverage,value)
        if round(value*1e6)<450000:
            counts['first_fail_group_floor']+=1;continue
        counts['passed_group_floor']+=1
        marginal=[value-coverage([pair[1-i]],weights) for i in range(2)]
        if any(round(v*1e6)<30000 for v in marginal):
            counts['first_fail_universal_marginal']+=1;continue
        counts['passed_all_old_pair_rules']+=1
    return {'counts':dict(counts),'maximum_anchor_pair_coverage':max_coverage,
            'limits':'Exact pairs, not all size-three/four combinations. Existing optimizer output/work is separately retained.'}


def run():
    dev=read(DOC/'manifests/development.json')
    allowed={s['id'] for s in dev['scopes']}
    assert {s for s,_ in CASES}<=allowed and len(CASES)==12
    manifest={'version':'D1-diagnostic-selection-1','source_checkpoint':'f2b047e3ebe283b09b46f12c8a3189ddce984292',
              'rule':'Twelve explicit existing source/failure strata from C2 records, selected before D1 changes or new judgments. Historical failures are exposed development, never holdout. No score-based replacement.',
              'cases':[{'scope_id':sid,'stratum':stratum} for sid,stratum in CASES],
              'broader_denominator':{'scientific':90,'derived_controls':30},'replacement_benchmark':False}
    immutable(DOC/'manifests/diagnostic-cases-d1.json',manifest)
    bundle=read(DOC/'prepared/c2/bundle.json');context=read(DOC/'prepared/c2/context.json')
    directory=read(DOC/'prepared/c2/directory.json')
    original=read(OLD/'development-corrected-v2.json');candidate=next(c for c in original['results'] if c['id']=='bounded-middle')
    old= {s['id']:s for s in candidate['scopes']};source={s['id']:s for s in bundle['sources']}
    scopes={s['id']:s for s in bundle['scopes']};dispositions={d['scope_id']:d for d in context['dispositions']}
    rows={p['id']:p for p in directory['researchers']};people={p['id']:p for p in bundle['people']}
    mapping=read(OLD/'judge-item-map-v3.json');judgments=read(OLD/'analysis-private/c2-judge-results-34472949357.json')
    human={i['key'] for i in read(DOC/'manifests/human-development-c2-selection.json')['items']}
    measurements={r['scope_id']:r for r in read(DOC/'receipts/c2-real-measurements-final.json')['rows']}
    traces=[];summary=[]
    for sid,stratum in CASES:
        s=scopes[sid];n=old[sid]
        trace={'scope_id':sid,'stratum':stratum,'source':source[sid],'scope':s,'disposition':dispositions[sid],
               'action_observation':measurements[sid],'old_numerical':n,
               'judge_items':[{'key':k,'packet_item':v,'verdict':judgments['labels'].get(k),'in_existing_human_packet':k in human}
                              for k,v in mapping['unique'].items() if v['scope_id']==sid]}
        if s['prepared']:
            trace['pair_waterfall']=pair_waterfall(s,n)
            aspects=sorted(s['aspects'],key=lambda a:a['id']);correlations=[]
            for i,j in itertools.combinations(range(len(aspects)),2):
                correlations.append({'aspects':[aspects[i]['id'],aspects[j]['id']],
                     'fixed_score':correlation([r['edges'][i]['score'] for r in n['rows']],[r['edges'][j]['score'] for r in n['rows']]),
                     'aspect_cosine':correlation([r['edges'][i]['features'][0] for r in n['rows']],[r['edges'][j]['features'][0] for r in n['rows']])})
            trace['aspect_correlations']=correlations
            trace['dominant_people']=[{'aspect_id':a['id'],'top':sorted([{'id':r['id'],'score':r['edges'][i]['score'],'claim_id':r['edges'][i].get('claim_id')} for r in n['rows']],key=lambda r:(-r['score'],r['id']))[:3]} for i,a in enumerate(aspects)]
            trace['registry_records_supplied']=[{'record':rows[p['id']],'scorer_projection':p,
               'omitted_existing_fields':sorted(set(rows[p['id']])-{'id','claims'}),'judge_claim_projection':'claim_id,revision,evidence,one source URL; claim labels/types and research_summary omitted'} for p in bundle['people']]
            trace['descriptor_counts']={'source_aspects':len(aspects),'source_operation':sum(bool(a.get('operation')) for a in aspects),'source_context':sum(bool(a.get('context')) for a in aspects),
                'profile_passages':sum(len(p['passages']) for p in people.values()),'profile_operation':sum(bool(v.get('operation')) for p in people.values() for v in p['passages']),
                'profile_context':sum(bool(v.get('context')) for p in people.values() for v in p['passages'])}
        traces.append(trace)
        summary.append({'scope_id':sid,'stratum':stratum,'prepared':s['prepared'],'aspects':len(s['aspects']),
             'action_allowed':measurements[sid].get('action_allowed',False),'historical_action_reason':measurements[sid].get('action_reason',measurements[sid].get('action')),
             'admitted':n.get('admitted'),'group_size':len(n.get('B',{}).get('defaultIds',[])),
             'optimizer_work':n.get('B',{}).get('examinedCoverage'),'pair_waterfall':trace.get('pair_waterfall'),
             'aspect_correlations':trace.get('aspect_correlations'),'dominant_people':trace.get('dominant_people'),
             'descriptor_counts':trace.get('descriptor_counts'),'judge_valid':sum(i['verdict'] is not None for i in trace['judge_items']),
             'judge_missing':sum(i['verdict'] is None for i in trace['judge_items']),
             'source_disposition':dispositions[sid]['reason']})
    immutable(OUT/'diagnostic-traces-before.json',{'traces':traces,'provider_calls':0,'human_answers_public':False})
    immutable(DOC/'receipts/d1-diagnostic-before.json',{'selection_sha256':digest(manifest),'provider_calls':0,'cases':summary,
       'trace_sha256':hashlib.sha256((OUT/'diagnostic-traces-before.json').read_bytes()).hexdigest(),
       'trace_storage':'outputs/team-recommender-d1/diagnostic-traces-before.json, includes private judge mapping; not public release',
       'known_mathematical_limit':'With one aspect and max coverage, at least one member of any size>=2 team has zero removal marginal. A universal positive marginal makes every such group impossible.',
       'hypotheses_before_correction':['Few correlated aspects and repeated core scoring suppress useful overlap','Coarse title-only source aspects may drive unrelated similarity','Missing optional method/context disables the explicit method branch','Existing labels and research summaries omitted from judge may alter scientific interpretation'],
       'not_claimed':'Pair waterfall is not all-size feasibility; no-group does not establish directory incapability.'})
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':run()
