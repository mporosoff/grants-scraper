"""Option 1 wire adapter; unchanged scientific policy and audited input ownership.

References address exact, disclosed snapshot bytes. Resolution is not verification.
Legacy contracts/results remain independently reproducible and are never rewritten.
"""
from copy import deepcopy
from tools import contextual_team_contract as legacy
from tools.offline_ai import validate_schema
from tools.offline_spend import identity

VERSION = 'contextual-reference-output-v2'
REASON_LIMIT = 700
GAP_LIMIT = 300
OUTPUT_LIMITS = {'decomposition':8000, 'adjudication':16000, 'verification':24000}


def source_references(inputs):
    scope=inputs['scope']; result=[]
    for field in ('title','description','document_search_text'):
        text=scope['science'].get(field)
        if not isinstance(text,str):continue
        start=0
        while start<len(text):
            end=min(start+300,len(text))
            if end<len(text):
                split=text.rfind(' ',start+15,end)
                if split>=0:end=split
            passage=text[start:end]
            if len(passage)>=15:
                value={'scope_id':scope['id'],'parent_id':scope['parent_id'],
                       'field':field,'start':start,'end':end,'text':passage,
                       'field_sha256':identity(text)}
                result.append({'source_ref':'src-'+identity(value),**value})
            start=end
    return result


def projected_inputs(inputs):
    # Full science/conditions/profile context is preserved verbatim. The table
    # only gives addresses into text that is already visible to the model.
    return deepcopy(inputs) if 'people' in inputs else deepcopy(inputs)|{'source_references':source_references(inputs)}


def contract(stage):
    value=deepcopy(legacy.contract(stage)); schema=value['schema']
    if stage=='decomposition':
        role=schema['properties']['roles']['items']
        for key in ('quote','source_field'):
            del role['properties'][key];role['required'].remove(key)
        role['properties']['source_ref']=legacy.string(68,68)
        role['required'].append('source_ref')
    else:
        edge=schema['properties']['edges']['items']
        del edge['properties']['evidence_quote'];edge['required'].remove('evidence_quote')
        edge['properties']['reason']=legacy.string(REASON_LIMIT,15)
        edge['properties']['gap']=legacy.string(GAP_LIMIT,0)
    replacements={
        'CONTEXTUAL V1 ADAPTATION':'CONTEXTUAL REFERENCE ADAPTATION',
        'Each quote is an exact contiguous substring of the named science field (description, title or document_search_text).':
            'Each source_ref must name one supplied source_references entry supporting that contribution. Do not regenerate source text.',
        'Each edge cites one supplied active claim with its revision and an exact substring of its evidence.':
            'Each edge cites one supplied active claim_id and claim_revision. Do not regenerate its evidence text.',
        'Begin each edge reason with its exact supporting evidence phrase.':
            'The server displays the exact referenced claim evidence beside each reason; do not repeat it in the reason.',
        'Each evidence_quote must be an exact substring of that active claim evidence.':
            'Each claim reference must identify the supplied active claim evidence actually supporting the decision.',
    }
    for old,new in replacements.items():value['prompt']=value['prompt'].replace(old,new)
    value['prompt']+='\nREFERENCE OUTPUT V2: Return decisions and the defined references only. No names, URLs or copied evidence fields. Keep each reason concise (15–700 characters) and each separate gap at most 300 characters. Use the full surrounding source and profile context; a resolvable reference alone proves no applicability.\n'
    value['version']=VERSION
    value['settings']|={'max_output_tokens':OUTPUT_LIMITS[stage],'prompt_version':VERSION+'-'+stage,'schema_version':VERSION}
    return value


def resolve(stage,value,inputs):
    validate_schema(value,contract(stage)['schema'])
    result=deepcopy(value)
    if stage=='decomposition':
        refs={r['source_ref']:r for r in source_references(inputs)}
        for role in result['roles']:
            ref=refs.get(role['source_ref'])
            if ref is None:raise ValueError('source_reference_not_in_exact_scope')
            role.update(quote=ref['text'],source_field=ref['field'])
    else:
        people={p['person_id']:p for p in inputs['people']}
        for edge in result['edges']:
            person=people.get(edge['person_id'])
            claim=next((c for c in (person or {}).get('claims',[]) if c['claim_id']==edge['claim_id'] and c['revision']==edge['claim_revision']),None)
            if claim is None:raise ValueError('claim_reference_not_in_exact_person_revision')
            # Whole stored audited evidence, not a newly verified faculty quote.
            edge['evidence_quote']=claim['evidence']
    return legacy.validate_semantics(stage,result,inputs)


def validate_resolved(stage,value,inputs):
    """Validate exact successful cache reuse; never silently repair stored data."""
    wire=deepcopy(value)
    if stage=='decomposition':
        for role in wire['roles']:
            role.pop('quote');role.pop('source_field')
    else:
        for edge in wire['edges']:edge.pop('evidence_quote')
    if resolve(stage,wire,inputs)!=value:raise ValueError('cached_reference_resolution_conflict')
    return value
