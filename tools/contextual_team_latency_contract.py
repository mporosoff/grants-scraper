"""Same complete evidence and decisions, compact provider-correct references."""
from copy import deepcopy
from tools import contextual_team_demand_contract as demand
from tools import contextual_team_requirements as requirements
from tools.contextual_team_contract import obj, enum, array
from tools.offline_ai import request_body, validate_schema
from tools.offline_spend import encoded

VERSION = 'contextual-compact-applicability-v1'
ROUTES = {'S': {'provider':'anthropic','model':'claude-sonnet-5','effort':'medium'},
          'L': {'provider':'openai','model':'gpt-5.6-luna','reasoning':'low'}}


def adapter(repaired):
    return requirements if repaired else demand


def contract(stage, data, repaired=False):
    c = adapter(repaired).contract(stage, data)
    if stage != 'decomposition':
        fields = c['schema']['properties']
        roles = fields.pop('edges_by_contribution')['properties']
        example = deepcopy(next(iter(roles.values()))['items'])
        refs = demand.claim_table(data) if stage == 'adjudication' else demand.edge_table(data)
        key = 'claim_ref' if stage == 'adjudication' else 'edge_ref'
        example['properties'][key] = enum(*refs) if refs else enum('NO_REFERENCES')
        if stage == 'adjudication':
            example['properties']['role_id'] = enum(*roles); example['required'].append('role_id')
        # Match the existing per-contribution canonical validator at the native
        # boundary too. The locked two-role ECLIPSE input permits eight, not 24.
        fields['edges'] = array(example,sum(r['maxItems'] for r in roles.values()) if refs else 0)
        c['schema'] = obj(**fields)
        old = c['prompt'].index('\nORDINARY DEMAND WIRE FORMAT:')
        tail = requirements.POLICY if repaired else ''
        c['prompt'] = c['prompt'][:old] + '''
COMPACT APPLICABILITY WIRE: Return the object keyed by every supplied person_id
and one flat edges array, at most 24 edges overall and four per contribution.
Assessment role_id chooses an active role; claim_ref binds one exact owner and
revision from claim_references. Verification edge_ref chooses a supplied proposed
edge identity; the server resolves its role, owner and claim, without copied text.
Do not repeat names, URLs, quotes or known identities. Retain complete scientific
decisions and concise reasons (15–700 characters), gaps (0–300 characters).
Empty edges means no retained relationship, not an incomplete person assessment.
All existing applicability, category, centrality and downgrade-only rules apply.
''' + tail
    c['version'] = VERSION + ('-requirements-v2' if repaired else '-retained-v1')
    c['settings'] |= {'schema_version':VERSION, 'prompt_version':c['version']+'-'+stage}
    return c


def body(stage, data, route, output, repaired=False):
    c = contract(stage,data,repaired)
    c['route'] = deepcopy(ROUTES[route]); c['settings']['max_output_tokens'] = output
    evidence = adapter(repaired).projected_inputs(stage,data)
    import json
    request = request_body(c['route'],c['settings'],c['prompt'],json.loads(encoded(evidence)),c['schema'])
    if route == 'S':
        request['thinking'] = {'type':'adaptive'}
        request['output_config']['effort'] = 'medium'
    return c,request


def resolve(stage,value,data,repaired=False):
    validate_schema(value,contract(stage,data,repaired)['schema'])
    if stage == 'decomposition':return adapter(repaired).resolve(stage,value,data)
    active = requirements.active_data(data) if repaired else data
    wire = {k:deepcopy(v) for k,v in value.items() if k!='edges'}
    wire['edges_by_contribution'] = {r['id']:[] for r in active['interpretation']['roles']}
    refs = demand.edge_table(active) if stage == 'verification' else None
    for edge in value['edges']:
        row=deepcopy(edge)
        rid=row.pop('role_id') if stage=='adjudication' else refs[row['edge_ref']]['role_id']
        wire['edges_by_contribution'][rid].append(row)
    return adapter(repaired).resolve(stage,wire,data)


def validate_resolved(stage,value,data,repaired=False):
    return adapter(repaired).validate_resolved(stage,value,data)
