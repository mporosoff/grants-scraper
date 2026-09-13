"""Ordinary cold-demand wire contract; the existing scientific rules are unchanged.

The wire owns reference relationships, not copied text or provider-selected IDs.
Normalization resolves exact server-owned source/claim/proposed-edge identities.
Legacy recovery contracts and their caches remain independently reproducible.
"""
from copy import deepcopy
from tools import contextual_team_references as references
from tools import contextual_team_contract as scientific
from tools.offline_ai import validate_schema
from tools.offline_spend import identity

VERSION = 'contextual-cold-demand-references-v1'


def claim_table(data):
    return {c['claim_id']+'@'+str(c['revision']):
            {'person_id':p['person_id'],'claim_id':c['claim_id'],'claim_revision':c['revision']}
            for p in data.get('people',[]) for c in p['claims']}


def edge_table(data):
    return {e['role_id']+'|'+e['claim_id']+'@'+str(e['claim_revision']):deepcopy(e) for e in data.get('proposed_edges',[])}


def contract(stage, data):
    c=references.contract(stage)
    if stage=='decomposition':
        refs=references.source_references(data)
        if not refs:raise ValueError('cold_scope_has_no_source_references')
        c['schema']['properties']['roles']['items']['properties']['source_ref']=scientific.enum(*(r['source_ref'] for r in refs))
    else:
        original=c['schema']['properties']
        outcome=deepcopy(original['people']['items']);del outcome['properties']['person_id'];outcome['required'].remove('person_id')
        # Per-person keyed outcomes cannot omit, invent, or repeat a person.
        people=scientific.obj(**{p['person_id']:deepcopy(outcome) for p in data['people']})
        role_fields={}
        table=claim_table(data) if stage=='adjudication' else edge_table(data)
        for role in data['interpretation']['roles']:
            allowed=table if stage=='adjudication' else {k:v for k,v in table.items() if v['role_id']==role['id']}
            edge=deepcopy(original['edges']['items'])
            for key in ('person_id','claim_id','claim_revision','role_id'):
                del edge['properties'][key];edge['required'].remove(key)
            name='claim_ref' if stage=='adjudication' else 'edge_ref'
            edge['properties'][name]=scientific.enum(*allowed) if allowed else scientific.enum('NO_REFERENCES')
            edge['required'].append(name)
            role_fields[role['id']]=scientific.array(edge,4 if allowed else 0)
        schema={'people':people,'edges_by_contribution':scientific.obj(**role_fields)}
        if stage=='verification':schema={'state':deepcopy(original['state']),**schema}
        c['schema']=scientific.obj(**schema)
    c['prompt']+='\nORDINARY DEMAND WIRE FORMAT: Follow the exact supplied schema. For assessment/verification, return people as the object keyed by every supplied person_id. Return edges_by_contribution keyed by every interpreted role_id, at most four entries per contribution; empty arrays mean no retained relationships. Assessment claim_ref selects a supplied claim_references key binding its exact owner and revision. Verification edge_ref selects an existing proposed_edge_references key for that contribution; do not invent or change the relationship. The server resolves IDs and exact text. Existing scientific applicability, support-category, downgrade-only verification and uncertainty rules still govern each decision. Reference validity alone establishes no scientific support.\n'
    c['version']=VERSION
    c['settings']|={'prompt_version':VERSION+'-'+stage,'schema_version':VERSION}
    return c


def projected_inputs(stage,data):
    result=references.projected_inputs(data)
    if stage=='adjudication':result['claim_references']=claim_table(data)
    elif stage=='verification':result['proposed_edge_references']=edge_table(data)
    return result


def resolve(stage,value,data):
    validate_schema(value,contract(stage,data)['schema'])
    if stage=='decomposition':return references.resolve(stage,value,data)
    result={'people':[{'person_id':p['person_id'],**value['people'][p['person_id']]} for p in data['people']], 'edges':[]}
    if stage=='verification':result['state']=value['state']
    table=claim_table(data) if stage=='adjudication' else edge_table(data)
    for role in data['interpretation']['roles']:
        for row in value['edges_by_contribution'][role['id']]:
            edge=deepcopy(row);key=edge.pop('claim_ref' if stage=='adjudication' else 'edge_ref')
            owned=table[key]
            edge={**owned,**edge,'role_id':role['id']}
            result['edges'].append(edge)
    return references.resolve(stage,result,data)


def validate_resolved(stage,value,data):
    # Recreate the exact wire value; accept only lossless server resolution.
    if stage=='decomposition':
        wire=deepcopy(value)
        for role in wire['roles']:
            role.pop('quote');role.pop('source_field')
    else:
        wire={'people':{},'edges_by_contribution':{r['id']:[] for r in data['interpretation']['roles']}}
        if stage=='verification':wire['state']=value['state']
        for person in value['people']:
            p=deepcopy(person);pid=p.pop('person_id')
            if pid in wire['people']:raise ValueError('duplicate_cached_person')
            wire['people'][pid]=p
        refs=claim_table(data) if stage=='adjudication' else edge_table(data)
        for edge in value['edges']:
            owned={k:edge[k] for k in ('person_id','claim_id','claim_revision')}
            if stage=='verification':owned|={'role_id':edge['role_id']}
            matches=[key for key,row in refs.items() if all(row[k]==v for k,v in owned.items())]
            if len(matches)!=1:raise ValueError('cached_edge_reference_not_unique')
            row={k:v for k,v in edge.items() if k not in ('person_id','claim_id','claim_revision','role_id','evidence_quote')}
            row['claim_ref' if stage=='adjudication' else 'edge_ref']=matches[0]
            wire['edges_by_contribution'][edge['role_id']].append(row)
    if resolve(stage,wire,data)!=value:raise ValueError('cold_cached_resolution_conflict')
    return value
