"""Lossless compact wire addresses for the unchanged complete-pair check."""
import json
from tools import contextual_team_pair_contract as pairs
from tools.contextual_team_contract import obj, array, enum, string
from tools.offline_ai import anthropic_schema, validate_schema, response_value
from tools.offline_spend import identity, encoded

VERSION = 'complete-pair-addresses-v1'
FORMAT = '''
Serialization override only; the scientific rubric above is unchanged.
Return a decisions object keyed by EVERY qNN in wire_questions. Each qNN is one
fixed person/contribution question, not a rank or selected team. Return coverage,
claims, verdict, reason and gap for each. claims is an ordered array of zero to
three distinct short claim addresses allowed for that question. Look up their
original owned claim IDs/revisions in wire_claims. Direct/method_transfer needs
at least one claim. Negative decisions may cite informative owned evidence or
use an empty array. The first/second/third entries become the canonical claim
slots; empty slots become NONE. Do not emit source_ref: the server supplies the
exact fixed source_ref from this question's original contribution. No scientific
inference or source choice is made by that mapping. Preserve the same complete
15–700 character reason and 0–300 character gap. Do not emit person names,
source quotations or copied profile passages. Every question remains required.
'''


def mapping(data):
    pairs.schema(data, judge=True)  # Original identity/coherence checks.
    questions = {}; claims = {}; owners = {}
    for i, person in enumerate(data['people'], 1):
        owned = {}
        for j, claim in enumerate(person['claims'], 1):
            address = f'p{i:02}c{j:02}'
            owned[address] = claim['claim_id']+'@'+str(claim['revision'])
            claims[address] = {'person_id':person['person_id'], 'claim_ref':owned[address]}
        owners[person['person_id']] = owned
        for role in data['interpretation']['roles']:
            questions[f'q{len(questions)+1:02}'] = {
                'person_id':person['person_id'], 'role_id':role['id'],
                'source_ref':role['source_ref']}
    return questions, claims, owners


def schema(data):
    questions, _, owners = mapping(data)
    return obj(decisions=obj(**{qid:obj(coverage=enum(*pairs.CATEGORIES),
        claims=array(enum(*owners[q['person_id']]),3),
        verdict=enum('strong','plausible','unrelated','insufficient-information'),
        reason=string(700,15),gap=string(300,0)) for qid,q in questions.items()}))


def body(data):
    canonical, result = pairs.body(data, judge=True)
    questions, claims, _ = mapping(data)
    evidence = json.loads(result['messages'][0]['content'])
    evidence.update(wire_questions=questions, wire_claims=claims)
    result['messages'][0]['content'] = json.dumps(evidence, ensure_ascii=False)
    result['system'] += FORMAT
    wire_schema = schema(data)
    result['output_config']['format']['schema'] = anthropic_schema(wire_schema)
    return {'version':VERSION, 'canonical_contract_sha256':identity(canonical),
        'input_sha256':identity(data), 'schema':wire_schema,
        'mapping_sha256':identity([questions,claims]), 'maximum_pairs':len(questions),
        'serving_approved':False}, result


def resolve(value, data):
    if len(encoded(value)) > pairs.MAX_FINAL_BYTES:
        raise ValueError('complete_pair_response_bytes')
    validate_schema(value,schema(data))
    questions, _, owners = mapping(data)
    canonical = {'decisions':{}}
    for qid,q in questions.items():
        row = value['decisions'][qid]
        refs = [owners[q['person_id']][ref] for ref in row['claims']]
        slots = dict(zip(('primary','second','third'), refs+[pairs.NONE]*(3-len(refs))))
        canonical['decisions'].setdefault(q['person_id'],{})[q['role_id']] = {
            **{k:row[k] for k in ('coverage','verdict','reason','gap')},
            'claim_refs':slots,'source_ref':q['source_ref']}
    return pairs.resolve(canonical,data,judge=True)


def parse(payload, data):
    response_value('anthropic',payload)
    from tools.contextual_team_diagnostics import final_text
    def unique(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate_response_key')
            result[k]=v
        return result
    return resolve(json.loads(final_text('anthropic',payload),object_pairs_hook=unique),data)
