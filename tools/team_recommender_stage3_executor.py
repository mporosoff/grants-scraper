"""Fixed E2 validation data contract; no credentials, network, or ranking."""
import copy
import json
import re
from tools.offline_spend import encoded, identity, Deferred
from tools.team_recommender_evidence_projection import request_body
from tools.team_recommender_judge_d1 import labels

PROTOCOL = 'S3-E2-complete-v1'
REPRESENTATION = 'S3-E2-query-v1'
INPUTS_SHA256 = 'baefc5461e1a50354ec9fc2bfe34ec12e8d00d591715f0845ae2ddffc2b11472'
PURPOSES = {'s3-primary':134, 's3-alternative':12, 's3-explanation':6, 's3-swap':6, 's3-control':6}
KINDS = {'call_person','aspect_person','group_usefulness','comparison','source_suitability','explanation_audit'}

def inputs(settings):
    from tools import team_recommender_executor as e
    raw=(e.CONFIG/'inputs-stage3.json').read_bytes()
    if settings.get('stage3_inputs_sha256')!=INPUTS_SHA256 or e.sha(raw)!=INPUTS_SHA256:
        raise ValueError('S3_unapproved_input_snapshot')
    value=json.loads(raw)
    if value['registry_generation']!=settings['registry_generation'] or value['version']!='S3-E2-frozen-inputs-v1':
        raise ValueError('S3_registry_or_schema_mismatch')
    return value

def is_stage3(request):
    return request.get('protocol')==PROTOCOL or request.get('representation')==REPRESENTATION

def embedding_contract(request, settings):
    from tools import team_recommender_executor as e
    e.exact_keys(request,['representation','model','input_role','rows'])
    if request['representation']!=REPRESENTATION or request['model']!='voyage-4-large' or request['input_role']!='query':
        raise ValueError('S3_only_frozen_E2_query_preparation')
    rows=request['rows']; allowed=inputs(settings)['query_rows']
    if not isinstance(rows,list) or not 1<=len(rows)<=64:
        raise ValueError('S3_bounded_query_rows_required')
    ids=set()
    for row in rows:
        e.exact_keys(row,['id','owner','text'])
        if allowed.get(row['id'])!=row or e.sha(row['text'].encode())!=row['id'] or row['id'] in ids:
            raise ValueError('S3_query_not_exact_owned_frozen_input')
        ids.add(row['id'])
    body={'model':'voyage-4-large','input_type':'query','output_dimension':1024,
          'output_dtype':'float','input':[r['text'] for r in rows],'truncation':False}
    bound=len(encoded(body))+1024
    if bound>20000:raise Deferred('S3_complete_query_exceeds_bound')
    return body,bound

def judge_contract(request,settings):
    from tools import team_recommender_executor as e
    e.exact_keys(request,['protocol','scope_id','purpose','source_evidence','aspects','items'])
    frozen=inputs(settings);sid=request['scope_id'];purpose=request['purpose']
    if request['protocol']!=PROTOCOL or sid not in frozen['heldout_ids'] or purpose not in PURPOSES:
        raise ValueError('S3_outside_frozen_validation_authority')
    ctx=frozen['contexts'][sid]
    if request['source_evidence']!=ctx['source_evidence'] or request['aspects']!=ctx['aspects']:
        raise ValueError('S3_source_or_child_context_changed')
    source_refs=e.source_evidence(request['source_evidence'])
    if any(not re.fullmatch(r's[0-9]',ref) for ref in source_refs):raise ValueError('S3_source_alias')
    aspects={a['id']:a for a in request['aspects']}
    items=request['items'];aliases={};people_by_item={}
    if not isinstance(items,list) or not 1<=len(items)<=3:raise ValueError('S3_bounded_items')
    for i,item in enumerate(items,1):
        e.exact_keys(item,['item_id','task_type','candidates','profile_documents'],['target_aspect','explanation'])
        alias,kind=item['item_id'],item['task_type']
        if alias!='i%02d'%i or kind not in KINDS:raise ValueError('S3_item_identity')
        if ((purpose=='s3-explanation') != (kind=='explanation_audit')
                or purpose=='s3-swap' and kind!='comparison'
                or purpose=='s3-alternative' and kind not in {'group_usefulness','call_person','comparison'}
                or purpose=='s3-control' and kind not in {'source_suitability','call_person'}):
            raise ValueError('S3_purpose_kind_mismatch')
        if kind=='aspect_person':
            if item.get('target_aspect') not in aspects:raise ValueError('S3_aspect_ownership')
        elif 'target_aspect' in item:raise ValueError('S3_unexpected_target_aspect')
        if kind!='source_suitability' and not aspects:raise ValueError('S3_missing_scientific_context')
        candidates=item['candidates']
        if kind=='comparison':
            e.exact_keys(candidates,['A','B'])
            if len(candidates['A'])!=len(candidates['B']):raise ValueError('S3_matched_size_required')
            groups=list(candidates.values())
        else:groups=[candidates]
        for group in groups:
            lo,hi=(0,0) if kind=='source_suitability' else (1,1) if kind in {'call_person','aspect_person'} else (2,4)
            if not isinstance(group,list) or not lo<=len(group)<=hi or len(set(group))!=len(group):
                raise ValueError('S3_candidate_size_or_duplicate')
        people=set().union(*map(set,groups))
        expected=[frozen['profile_documents'].get(pid) for pid in sorted(people)]
        if None in expected or item['profile_documents']!=expected:
            raise ValueError('S3_complete_unchanged_candidate_documents_required')
        if kind=='explanation_audit':
            explanation=e.text(item.get('explanation'),3500)
            quotes=re.findall('The public passage “(.*?)”',explanation)
            if len(quotes)!=len(people) or any(not any(s['text']==q for p in expected for s in p['statements']) for q in quotes):
                raise ValueError('S3_exact_explanation_quote_missing')
        elif 'explanation' in item:raise ValueError('S3_explanation_must_be_separate')
        aliases[alias]=kind;people_by_item[alias]=people
    prompt=(e.CONFIG/'judge-d1.md').read_text(encoding='utf-8')
    prompt=prompt[:prompt.index('Return exactly one verdict')]+'Return one verdict, one evidence reference and the most specific allowed reason code per item.'
    body=request_body(request['source_evidence'],request['aspects'],items,prompt)
    bound=len(encoded(body))+1024
    if bound>12000:raise Deferred('complete_evidence_exceeds_packet_bound')
    data=json.loads(body['messages'][0]['content']);docs={p['person_id']:p for p in data['profile_documents']}
    refs={alias:source_refs|{ref for pid in people for ref in [docs[pid]['id'],*[s['id'] for s in docs[pid]['statements']]]}
          for alias,people in people_by_item.items()}
    return body,bound,aliases,refs,body['output_config']['format']['schema']

def judge_items(request):
    # Same complete scientific question keeps its paid claim across batching,
    # display aliases, purpose names and restarts. A/B order remains substantive.
    context={k:request[k] for k in ('scope_id','source_evidence','aspects')}
    result=[]
    for item in request['items']:
        value=copy.deepcopy({k:v for k,v in item.items() if k!='item_id'})
        candidates=value['candidates']
        value['candidates']={k:sorted(v) for k,v in candidates.items()} if isinstance(candidates,dict) else sorted(candidates)
        result.append(identity([PROTOCOL,context,value]))
    if len(set(result))!=len(result):raise ValueError('S3_duplicate_scientific_item')
    return result
