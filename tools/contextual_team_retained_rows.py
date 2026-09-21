"""Lossless alias recovery of a retained complete independent checker response.

The trusted caller must authenticate the exact retained text and scientific
input identities. This converter neither dispatches nor changes any judgment.
"""
from copy import deepcopy
import json
from tools import contextual_team_shared_rows as rows
from tools import contextual_team_pair_contract as pairs
from tools.offline_ai import validate_schema
from tools.offline_spend import identity

VERSION = 'iteration1-canonical-claim-alias-recovery-v1'


def _mapping(data):
    questions, claims, owners = rows.mapping(data)
    if len(data['people']) != 12 or len(data['interpretation']['roles']) != 2 or len(questions) != 24:
        raise ValueError('retained_recovery_exact_12_people_24_questions')
    return questions, claims, owners


def contract(data):
    questions, claims, _ = _mapping(data)
    return {'version': VERSION, 'input_sha256': identity(data),
        'canonical_contract_sha256': identity(pairs.contract(data, judge=True)),
        'shared_rows_schema_sha256': identity(rows.schema(data)),
        'mapping_sha256': identity([questions, claims]),
        'maximum_final_bytes': pairs.MAX_FINAL_BYTES,
        'rules': ['exact_12_people_24_questions', 'canonical_claim_references_only',
            'exact_active_claim_owner_revision', 'preserve_all_scientific_fields_and_claim_order',
            'unchanged_complete_pair_validator'], 'serving_approved': False}


def recover(text, data):
    """Replace only exact owned canonical references with their fixed aliases."""
    if not isinstance(text, str) or len(text.encode('utf8')) > pairs.MAX_FINAL_BYTES:
        raise ValueError('retained_recovery_final_text_bound')
    questions, _, owners = _mapping(data)

    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate_response_key')
            value[key] = item
        return value

    def non_json_constant(value):
        raise ValueError('retained_recovery_non_json_constant')

    original = json.loads(text, object_pairs_hook=unique, parse_constant=non_json_constant)
    validate_schema(original, rows.schema(data))
    qids = [row['question_id'] for row in original['answers']]
    if len(qids) != len(set(qids)) or set(qids) != set(questions):
        raise ValueError('retained_recovery_complete_unique_questions')
    converted = deepcopy(original)
    for answer in converted['answers']:
        question = questions[answer['question_id']]
        inverse = {reference: address for address, reference in owners[question['person_id']].items()}
        if any(reference not in inverse for reference in answer['claims']):
            raise ValueError('retained_recovery_exact_canonical_owner_revision')
        answer['claims'] = [inverse[reference] for reference in answer['claims']]
    # No aliases, identities or scientific fields are inferred. The unchanged
    # validator still enforces completeness, distinct claims and positive support.
    value = rows.resolve(converted, data)
    return pairs.validate_cached(value, data, judge=True)
