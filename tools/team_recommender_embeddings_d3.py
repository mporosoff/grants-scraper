"""Finite richer representations of the trusted frozen registry and D2 queries.

Inputs remain data. Context groups never combine researchers. No provider I/O.
"""
import hashlib
import json
import math
from pathlib import Path
from collections import defaultdict

PHRASES = 'D3-phrases-v1'
COMBINED = 'D3-combined-v1'
CONTEXT = 'D3-context-v1'
QUERY_FORMAT = 'aspect-purpose-v1'
STANDARD_MODEL = 'voyage-4-large'
CONTEXT_MODEL = 'voyage-context-4'
MODELS = {PHRASES: STANDARD_MODEL, COMBINED: STANDARD_MODEL, CONTEXT: CONTEXT_MODEL}
STANDARD_URL = 'https://api.voyageai.com/v1/embeddings'
CONTEXT_URL = 'https://api.voyageai.com/v1/contextualizedembeddings'
QUERIES_SHA256 = 'f19b8b0ed8b233e2b259632270f915e7b0156219bbc02c3c247a9ce23d31d703'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def is_d3(request):
    # Stage 3 retains the exact standard E2 endpoint/role/preprocessing space.
    return str(request.get('representation', '')).startswith('D3-') or request.get('representation') == 'S3-E2-query-v1'


def profiles(settings):
    result = {}
    for owner, claims in sorted(settings['profile_claims'].items()):
        fields = settings['d1_profile_fields'][owner]
        metadata = {c['id']: c for c in fields['claims']}
        by_text = defaultdict(list)
        for c in claims:
            m = metadata[c['claim_id']]
            by_text[c['text']].append({'claim_id': c['claim_id'], 'revision': c['revision'],
                                      'label': m['label'], 'claim_type': m['claim_type']})
        chunks, attribution = [], []
        if fields['research_summary']:
            chunks.append('Research summary:\n' + fields['research_summary'])
            attribution.append({'field': 'research_summary', 'claim_refs': []})
        for evidence, refs in sorted(by_text.items()):
            labels = sorted({c['claim_type'] + ': ' + c['label'] for c in refs})
            chunks.append('Research interest:\n' + evidence + '\nExisting claim context:\n' + '\n'.join(labels))
            attribution.append({'field': 'claims', 'text': evidence, 'claim_refs': sorted(refs, key=lambda c: c['claim_id'])})
        result[owner] = {'combined': '\n\n'.join(chunks), 'chunks': chunks,
                         'attribution': attribution, 'phrases': sorted(by_text)}
    return result


def queries():
    raw = (Path(__file__).resolve().parents[1] / 'config/team_recommender_executor/queries-d3.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != QUERIES_SHA256:
        raise ValueError('D3_trusted_query_snapshot_changed')
    return json.loads(raw)['scopes']


def query_texts(scope, contextual=False):
    if contextual:
        return ['Scientific purpose:\n' + scope['core'] + '\nScientific contribution:\n' + a['text'] for a in scope['aspects']]
    return [scope['core'], scope['whole_call'], *[a['text'] for a in scope['aspects']]]


def contract(request, settings):
    from tools.team_recommender_executor import exact_keys, text
    exact_keys(request, ['representation', 'model', 'input_role', 'rows'], ['query_format'])
    rep, role, model, rows = (request[k] for k in ('representation', 'input_role', 'model', 'rows'))
    if rep not in MODELS or model != MODELS[rep] or role not in {'query', 'document'}:
        raise ValueError('D3_unapproved_model_or_representation')
    if 'query_format' in request and (role != 'query' or request['query_format'] != QUERY_FORMAT):
        raise ValueError('D3_query_format_not_allowed')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('D3_bounded_rows_required')
    people, sources = profiles(settings), queries()
    identifiers, inputs = set(), []
    for row in rows:
        contextual_doc = rep == CONTEXT and role == 'document'
        exact_keys(row, ['id', 'owner', 'chunks'] if contextual_doc else ['id', 'owner', 'text'])
        if contextual_doc:
            if row['owner'] not in people or row['chunks'] != people[row['owner']]['chunks']:
                raise ValueError('D3_context_must_be_one_exact_frozen_person')
            if not 1 <= len(row['chunks']) <= 17:
                raise ValueError('D3_bounded_document_chunks_required')
            for chunk in row['chunks']: text(chunk)
            content = canonical(row['chunks'])
            inputs.append(row['chunks'])
        else:
            content = text(row['text'])
            if role == 'query':
                if row['owner'] not in sources or row['owner'] not in settings['development_ids'] or content not in query_texts(sources[row['owner']], 'query_format' in request):
                    raise ValueError('D3_query_not_exact_prepared_development_science')
            else:
                person = people.get(row['owner'])
                allowed = person['phrases'] if person and rep == PHRASES else [person['combined']] if person else []
                if content not in allowed:
                    raise ValueError('D3_profile_not_constructed_from_trusted_frozen_fields')
            inputs.append([content] if rep == CONTEXT else content)
        if row['id'] != digest(content) or row['id'] in identifiers:
            raise ValueError('D3_input_identity_or_duplicate')
        identifiers.add(row['id'])
    body = {'model': model, 'input_type': role, 'output_dimension': 1024, 'output_dtype': 'float'}
    if rep == CONTEXT:
        if sum(map(len, inputs)) > 128:
            raise ValueError('D3_bounded_context_output_rows_required')
        body.update(inputs=inputs, enable_auto_chunking=False)
        # Conservative repeated-context ceiling even though the API normally
        # reports one input-token total per document. Never crop source text.
        bound = sum(sum(len(t.encode('utf8')) + 64 for t in doc) * len(doc) for doc in inputs) + 1024
    else:
        body.update(input=inputs, truncation=False)
        bound = len(canonical(body).encode('utf8')) + 1024
    if bound > 100000:
        raise ValueError('D3_complete_request_exceeds_input_bound')
    return body, bound


def endpoint(request):
    return CONTEXT_URL if request['representation'] == CONTEXT else STANDARD_URL


def expected_rows(request):
    output = []
    for row in request['rows']:
        if request['representation'] == CONTEXT and request['input_role'] == 'document':
            for index, chunk in enumerate(row['chunks']):
                output.append({'id': digest(canonical([row['id'], index, chunk])), 'owner': row['owner'],
                               'document_id': row['id'], 'chunk_index': index, 'text': chunk})
        else:
            output.append({'id': row['id'], 'owner': row['owner'], 'text': row['text']})
    return output


def paid_items(request):
    # Bind endpoint/model/role/dimensions/preprocessing and WHOLE ordered
    # contextual document, not just the unchanged local chunk text. Standard
    # query rows remain reusable across E1/E2 and request rebatching.
    space = [endpoint(request), request['model'], request['input_role'], 1024, 'float', 'exact-utf8-D3-v1']
    return ['d3:' + digest(canonical([space, row['id']])) for row in expected_rows(request)]


def validate_value(value, request):
    from tools.team_recommender_executor import exact_keys
    exact_keys(value, ['input_role', 'rows'])
    expected = expected_rows(request)
    if value['input_role'] != request['input_role'] or not isinstance(value['rows'], list) or len(value['rows']) != len(expected):
        raise ValueError('D3_cached_shape')
    for row, item in zip(value['rows'], expected):
        exact_keys(row, ['id', 'embedding'])
        vector = row['embedding']
        if row['id'] != item['id'] or not isinstance(vector, list) or len(vector) != 1024 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError('D3_vector_identity_shape_or_finite')
        if not .8 <= sum(v*v for v in vector) <= 1.2:
            raise ValueError('D3_vector_norm_outside_contract')
    return value


def result(payload, request):
    rows = payload.get('data')
    if not isinstance(rows, list) or len(rows) != len(request['rows']) or sorted(r.get('index') for r in rows) != list(range(len(rows))):
        raise ValueError('D3_response_document_indices')
    vectors = []
    for row in sorted(rows, key=lambda r: r['index']):
        if request['representation'] == CONTEXT:
            chunks = row.get('data');original = request['rows'][row['index']]
            count = len(original['chunks']) if request['input_role'] == 'document' else 1
            if not isinstance(chunks, list) or len(chunks) != count or sorted(c.get('index') for c in chunks) != list(range(count)):
                raise ValueError('D3_response_chunk_indices')
            vectors.extend(c.get('embedding') for c in sorted(chunks, key=lambda c: c['index']))
        else:
            vectors.append(row.get('embedding'))
    return validate_value({'input_role': request['input_role'], 'rows': [
        {'id': r['id'], 'embedding': v} for r, v in zip(expected_rows(request), vectors)]}, request)
