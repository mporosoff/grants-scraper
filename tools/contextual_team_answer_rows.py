"""Versioned normal complete-pair transport with exact owned references.

Historical transports and the one-time retained-response recovery are unchanged.
This adapter authorizes neither paid retries nor production graph admission.
"""
import json
from tools import contextual_team_pair_contract as pairs
from tools.contextual_team_check_wire import mapping
from tools.contextual_team_contract import obj, array, enum, string
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import anthropic_schema, validate_schema, response_value
from tools.offline_spend import identity, encoded

VERSION = 'contextual-complete-answer-rows-v2'
FORMAT = '''
NORMAL ANSWER-ROW SERIALIZATION: The scientific rubric above is unchanged.
Return one JSON object with exactly answers, an array with exactly one answer
for EVERY question_id in wire_questions. The actual supplied question set is
authoritative for every provided person and contribution, regardless of count.
Do not omit, repeat, invent or rank questions. Row order is immaterial.
Each answer contains question_id, coverage, claims, reason and gap as defined
by the attached schema. coverage is direct, method_transfer, adjacent, or
insufficient_information. Prefer canonical claim_id@revision references in
claims: use the exact claim_ref values disclosed in wire_claims and the original
claim_references. Cite only active evidence belonging to this question's person.
claims is an ordered array of zero to three DISTINCT claims. A short alias and
its canonical reference identify the SAME claim and cannot both be cited.
Direct/method_transfer requires at least one supporting owned claim. Negative
decisions may cite informative owned evidence or use an empty array. Never guess
a claim, owner or revision. A valid reference alone supplies no scientific support.
The server restores exact fixed person/contribution/source identities and claim
slots; that mapping makes no scientific inference. Do not emit source_ref,
person_id, names, copied evidence, source quotations or extra fields. reason is
a complete evidence-based explanation of 15-700 characters; gap is an honest
limitation of 0-300 characters. Preserve all questions and honest negative or
insufficient-information answers. Return JSON only, without Markdown or prose.
'''
CHECK_FORMAT = '''
Independent-check rows also require verdict: strong, plausible, unrelated, or
insufficient-information. Preserve its distinction from the coverage decision.
'''


def schema(data, *, judge=False):
    questions, _, owners = mapping(data)
    maximum = max(len(ref) for owned in owners.values() for pair in owned.items() for ref in pair)
    row = obj(question_id=enum(*questions), coverage=enum(*pairs.CATEGORIES),
        claims=array(string(maximum), 3), reason=string(700, 15), gap=string(300, 0),
        **({'verdict': enum('strong', 'plausible', 'unrelated', 'insufficient-information')} if judge else {}))
    answers = array(row, len(questions)); answers['minItems'] = len(questions)
    return obj(answers=answers)


def contract(data, *, judge=False):
    canonical = pairs.contract(data, judge=judge)
    questions, claims, _ = mapping(data)
    return {'version': VERSION + ('-check' if judge else '-assessment'),
        'reference_version': VERSION, 'input_sha256': identity(data),
        'canonical_contract_sha256': identity(canonical),
        'schema': schema(data, judge=judge),
        'prompt': canonical['prompt'] + FORMAT + (CHECK_FORMAT if judge else ''),
        'mapping_sha256': identity([questions, claims]),
        'reference_policy': 'exact-owned-alias-or-canonical; duplicates-after-canonicalization',
        'maximum_pairs': len(questions), 'maximum_final_bytes': pairs.MAX_FINAL_BYTES,
        'serving_approved': False}


def body(data, *, judge=False):
    c = contract(data, judge=judge)
    _, result = pairs.body(data, judge=judge)
    questions, claims, _ = mapping(data)
    text = result['messages'][0]['content'] if judge else result['input']
    evidence = json.loads(text)
    evidence.update(wire_questions=questions, wire_claims=claims)
    text = json.dumps(json.loads(encoded(evidence)), ensure_ascii=False)
    if judge:
        result['messages'][0]['content'] = text
        result['system'] = c['prompt']
        result['output_config']['format']['schema'] = anthropic_schema(c['schema'])
    else:
        result['input'] = text
        result['instructions'] = c['prompt']
        result['text']['format'].update(name=c['version'], schema=c['schema'])
    return c, result


def resolve(value, data, *, judge=False):
    if len(encoded(value)) > pairs.MAX_FINAL_BYTES:
        raise ValueError('complete_pair_response_bytes')
    validate_schema(value, schema(data, judge=judge))
    questions, _, owners = mapping(data)
    answers = {}
    for answer in value['answers']:
        qid = answer['question_id']
        if qid in answers:
            raise ValueError('duplicate_answer_question')
        answers[qid] = answer
    if set(answers) != set(questions):
        raise ValueError('incomplete_answer_questions')
    canonical = {'decisions': {}}
    for qid, question in questions.items():
        answer = answers[qid]; owned = owners[question['person_id']]
        canonical_refs = set(owned.values()); refs = []
        for reference in answer['claims']:
            if reference in owned:
                refs.append(owned[reference])
            elif reference in canonical_refs:
                refs.append(reference)
            else:
                raise ValueError('answer_claim_owner_or_revision')
        if len(refs) != len(set(refs)):
            raise ValueError('duplicate_support_claim_after_canonicalization')
        fields = ('coverage', 'reason', 'gap', 'verdict') if judge else ('coverage', 'reason', 'gap')
        canonical['decisions'].setdefault(question['person_id'], {})[question['role_id']] = {
            **{key: answer[key] for key in fields},
            'claim_refs': dict(zip(('primary', 'second', 'third'), refs + [pairs.NONE]*(3-len(refs)))),
            'source_ref': question['source_ref']}
    return pairs.resolve(canonical, data, judge=judge)


def validate_cached(value, data, *, judge=False):
    # The request envelope binds this version/body; cached scientific values must
    # still be exact lossless results of the original complete-pair validator.
    return pairs.validate_cached(value, data, judge=judge)


def parse(payload, provider, data, *, judge=False):
    if provider not in ('openai', 'anthropic') or not isinstance(payload, dict):
        raise ValueError('invalid_response_envelope')
    try:
        text = final_text(provider, payload)
    except (TypeError, AttributeError) as error:
        raise ValueError('invalid_response_content') from error
    if len(text.encode('utf8')) > pairs.MAX_FINAL_BYTES:
        raise ValueError('complete_pair_response_bytes')
    try:
        response_value(provider, payload)
    except (TypeError, AttributeError) as error:
        raise ValueError('invalid_response_content') from error
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_response_key')
            result[key] = value
        return result
    def non_json_constant(value):
        raise ValueError('non_json_response_constant')
    return resolve(json.loads(text, object_pairs_hook=unique, parse_constant=non_json_constant), data, judge=judge)
