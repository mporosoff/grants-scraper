"""One selected scientific approach; optional directions never become gaps.

The legacy wire/graphs remain reproducible. This contract is selected explicitly
by a new release, never by rewriting an accepted interpretation or its cache.
"""
from copy import deepcopy
from tools import contextual_team_demand_contract as demand
from tools import contextual_team_references as references
from tools.contextual_team_contract import obj, string, enum, validate_semantics
from tools.offline_ai import validate_schema

VERSION = 'contextual-selected-approach-v2'
GRAPH_VERSION = 'contextual-audited-graph-v2'
KINDS = ('sponsor_requirement', 'approach_necessary', 'optional_direction')
APPLICABILITY = ('applies', 'does_not_apply', 'unknown')
POLICY = '''
SELECTED-APPROACH V2 supersedes the ambiguous legacy required flag.
Before seeing any named candidates, select ONE coherent approach warranted by
the complete source. State it in approach. Do not invent an experiment, take the
union of mutually exclusive directions, or choose an approach to suit a team.
Each scientific contribution has kind, applicability and condition:
sponsor_requirement means an explicit scientific sponsor obligation, supported
by its exact source reference; preserve its applicability and conditions.
approach_necessary means needed for this selected approach, not a sponsor mandate.
optional_direction includes optional additions and unselected alternatives;
these are not missing skills, complementary requirements or admission evidence.
Administrative eligibility and cost sharing stay in source conditions, never roles.
Use applies only when the complete source establishes applicability to this
approach; does_not_apply or unknown must not silently become a covered requirement.
State unresolved applicability in limitations. Unknown does not mean waived.
Preserve genuine conjunctions, shared/nonexclusive methods and genuine gaps.
One substantive contribution is sufficient; no universal role template or splitting.
Only applicable sponsor_requirement and approach_necessary roles may be central.
The server derives required; it is not a model assertion of certification.
For assessment/verification, only roles contains active contributions. Other
directions remain in considered_directions for context, never edges or support.
Every automatic person still needs a contextual direct or credible-transfer
connection to an active contribution. Reference existence is not applicability.
'''


def active_roles(interpretation):
    if interpretation.get('requirement_policy') != VERSION:
        return interpretation['roles']
    return [r for r in interpretation['roles'] if r['kind'] != 'optional_direction'
            and r['applicability'] == 'applies']


def active_data(data):
    result = deepcopy(data)
    if 'interpretation' in data:
        selected = active_roles(data['interpretation'])
        result['interpretation']['roles'] = deepcopy(selected)
        ids = {r['id'] for r in selected}
        result['interpretation']['considered_directions'] = [deepcopy(r)
            for r in data['interpretation']['roles'] if r['id'] not in ids]
        if any(e['role_id'] not in ids for e in data.get('proposed_edges', [])):
            raise ValueError('inactive_direction_has_assessed_edge')
    return result


def contract(stage, data):
    c = demand.contract(stage, active_data(data))
    if stage == 'decomposition':
        fields = c['schema']['properties']
        fields['approach'] = string(1000, 0)
        c['schema']['required'].append('approach')
        role = fields['roles']['items']
        del role['properties']['required']; role['required'].remove('required')
        role['properties'].update(kind=enum(*KINDS), applicability=enum(*APPLICABILITY),
                                  condition=string(400, 0))
        role['required'].extend(['kind', 'applicability', 'condition'])
    c['prompt'] += POLICY
    c['version'] = VERSION
    c['settings'] |= {'prompt_version': VERSION+'-'+stage, 'schema_version': VERSION}
    return c


def projected_inputs(stage, data):
    return demand.projected_inputs(stage, active_data(data))


def resolve(stage, value, data):
    validate_schema(value, contract(stage, data)['schema'])
    if stage != 'decomposition':
        return demand.resolve(stage, value, active_data(data))
    result = deepcopy(value)
    refs = {r['source_ref']: r for r in references.source_references(data)}
    result['requirement_policy'] = VERSION
    for role in result['roles']:
        ref = refs[role['source_ref']]
        role['quote'] = ref['text']; role['source_field'] = ref['field']
        role['required'] = role['kind'] != 'optional_direction' and role['applicability'] == 'applies'
        if role['central'] and not role['required']:
            raise ValueError('inactive_direction_cannot_be_central')
        if role['applicability'] != 'applies' and not role['condition'].strip():
            raise ValueError('conditional_disposition_needs_explanation')
    validate_semantics(stage, result, data)
    active = active_roles(result)
    if result['state'] == 'coherent' and (not result['approach'].strip() or not active
                                         or not any(r['central'] for r in active)):
        raise ValueError('coherent_selected_approach_required')
    if result['state'] != 'coherent' and result['approach']:
        raise ValueError('noncoherent_source_has_no_selected_approach')
    if any(r['applicability'] == 'unknown' for r in result['roles']) and not result['limitations']:
        raise ValueError('unknown_applicability_requires_limitation')
    return result


def validate_resolved(stage, value, data):
    if stage != 'decomposition':
        return demand.validate_resolved(stage, value, active_data(data))
    wire = deepcopy(value)
    wire.pop('requirement_policy', None)
    for role in wire['roles']:
        for key in ('required', 'quote', 'source_field'): role.pop(key)
    if resolve(stage, wire, data) != value:
        raise ValueError('selected_approach_cache_identity')
    return value


def graph_metadata(graph, interpretation):
    active = {r['id'] for r in active_roles(interpretation)}
    if any(e['role_id'] not in active for e in graph['edges']):
        raise ValueError('inactive_graph_relationship')
    covered = {e['role_id'] for e in graph['edges'] if e['coverage'] in ('direct', 'method_transfer')}
    graph.update(version=GRAPH_VERSION, requirement_policy=VERSION,
                 approach=interpretation['approach'])
    if graph['state'] != 'no_supported_group_in_assessed_set':
        graph['state'] = 'ready' if active <= covered else 'ready_with_gaps'
    return graph
