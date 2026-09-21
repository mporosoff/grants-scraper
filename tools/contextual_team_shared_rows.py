"""Complete checker answers through one reusable row, with one named fallback.

Only serialization changes. Both transports resolve through the original strict
complete-pair validator. Neither transport authorizes dispatch or publication.
"""
import json
from tools import contextual_team_pair_contract as pairs
from tools.contextual_team_check_wire import mapping
from tools.contextual_team_contract import obj, array, enum, string
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import anthropic_schema, validate_schema, response_value
from tools.offline_spend import identity, encoded

STRICT_VERSION = 'complete-pair-shared-rows-strict-v1'
TEXT_VERSION = 'complete-pair-shared-rows-json-text-v1'
FORMAT = '''
Serialization override only; all scientific instructions and acceptance rules
above are unchanged. Return one JSON object with exactly the key answers. Its
value is an array containing exactly one answer for EVERY question_id in
wire_questions, without duplicates or extra questions. Row order is immaterial.
Every row has exactly question_id, coverage, claims, verdict, reason, and gap.
question_id is a supplied qNN address. coverage is direct, method_transfer,
adjacent, or insufficient_information. verdict is strong, plausible, unrelated,
or insufficient-information. These are independent scientific judgments.
claims is an ordered array of zero to three distinct short claim addresses from
wire_claims, owned by this question's person_id. Read their complete original
claim evidence and revisions. Direct/method_transfer requires at least one
supporting owned claim. Negative decisions may cite informative owned evidence
or use an empty array. The server restores the original claim IDs/revisions;
the first/second/third entries become the canonical claim slots and unused
slots become NONE. The server restores the question's exact fixed source_ref;
this mapping makes no scientific inference or source choice. Do not emit a
source_ref, name, copied evidence, source quotation, or any additional field.
reason is a complete evidence-based explanation of 15-700 characters. gap is
an honest limitation of 0-300 characters. Do not shorten the evidence, omit a
question, guess an answer, or infer a negative from missing information. Return
all questions even when every answer is negative or insufficient-information.
'''
TEXT_FORMAT = '''
This explicitly versioned transport uses ordinary JSON text output. Return only
the complete JSON object described above, without Markdown fences or prose.
The same strict application validator checks every field, question, ownership,
claim revision, source identity, and scientific acceptance rule before use.
'''


def schema(data):
    questions, _, _ = mapping(data)
    row = obj(question_id=enum(*questions), coverage=enum(*pairs.CATEGORIES),
        claims=array(string(20), 3),
        verdict=enum('strong', 'plausible', 'unrelated', 'insufficient-information'),
        reason=string(700, 15), gap=string(300, 0))
    answers = array(row, len(questions))
    answers['minItems'] = len(questions)
    return obj(answers=answers)


def body(data, *, transport=STRICT_VERSION):
    if transport not in (STRICT_VERSION, TEXT_VERSION):
        raise ValueError('shared_rows_unknown_transport')
    canonical, result = pairs.body(data, judge=True)
    questions, claims, _ = mapping(data)
    evidence = json.loads(result['messages'][0]['content'])
    evidence.update(wire_questions=questions, wire_claims=claims)
    result['messages'][0]['content'] = json.dumps(evidence, ensure_ascii=False)
    result['system'] += FORMAT
    local_schema = schema(data)
    if transport == STRICT_VERSION:
        result['output_config']['format']['schema'] = anthropic_schema(local_schema)
    else:
        del result['output_config']
        result['system'] += TEXT_FORMAT
    return {'version': transport, 'canonical_contract_sha256': identity(canonical),
        'input_sha256': identity(data), 'schema': local_schema,
        'mapping_sha256': identity([questions, claims]),
        'maximum_pairs': len(questions), 'maximum_final_bytes': pairs.MAX_FINAL_BYTES,
        'serving_approved': False}, result


def resolve(value, data):
    if len(encoded(value)) > pairs.MAX_FINAL_BYTES:
        raise ValueError('complete_pair_response_bytes')
    validate_schema(value, schema(data))
    questions, _, owners = mapping(data)
    rows = {}
    for row in value['answers']:
        qid = row['question_id']
        if qid in rows:
            raise ValueError('duplicate_answer_question')
        rows[qid] = row
    if set(rows) != set(questions):
        raise ValueError('incomplete_answer_questions')
    canonical = {'decisions': {}}
    for qid, question in questions.items():
        row = rows[qid]
        owned = owners[question['person_id']]
        if any(ref not in owned for ref in row['claims']):
            raise ValueError('answer_claim_owner_or_revision')
        refs = [owned[ref] for ref in row['claims']]
        slots = dict(zip(('primary', 'second', 'third'), refs + [pairs.NONE] * (3-len(refs))))
        canonical['decisions'].setdefault(question['person_id'], {})[question['role_id']] = {
            **{key: row[key] for key in ('coverage', 'verdict', 'reason', 'gap')},
            'claim_refs': slots, 'source_ref': question['source_ref']}
    return pairs.resolve(canonical, data, judge=True)


def parse(payload, data):
    if not isinstance(payload, dict):
        raise ValueError('invalid_response_envelope')
    content = payload.get('content')
    if not isinstance(content, list) or any(not isinstance(part, dict) for part in content):
        # Let the existing refusal/incomplete handling take precedence.
        response_value('anthropic', payload)
    text = final_text('anthropic', payload)
    if len(text.encode('utf8')) > pairs.MAX_FINAL_BYTES:
        raise ValueError('complete_pair_response_bytes')
    response_value('anthropic', payload)  # Existing completion/refusal checks.
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_response_key')
            result[key] = value
        return result
    return resolve(json.loads(text, object_pairs_hook=unique), data)
