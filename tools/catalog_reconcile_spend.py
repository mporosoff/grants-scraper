"""Durable Voyage requests inside the selected generation's existing allowance.

The Node preload calls these commands before/after its normal vector-builder
transport. Responses stay in the private checkpoint, never the candidate.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from tools.offline_spend import Deferred, Ledger, atomic_json, identity, production_ledger

MODEL = 'voyage-4-lite'
URL = 'https://api.voyageai.com/v1/embeddings'
MAX_RESPONSE = 24 * 1024 * 1024
GENERATION_INPUTS = (
    'tools/run_budgeted_vectors.mjs', 'tools/catalog_reconcile_vectors.mjs', 'tools/catalog_reconcile_spend.py',
    'tools/offline_spend.py', 'tools/build_search_v2_voyage_vectors.mjs', 'tools/embedding_contract.mjs',
    'tools/run_search_diagnosis.mjs', 'assets/search-hybrid.js', 'assets/search-retrieval.js',
    'assets/search-query.js', 'assets/search-v2-config.js', 'assets/match-explain.js',
    'config/offline_ai.json', 'data/opportunities.js', 'data/subtopics.js',
)
VECTOR_OUTPUTS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
                  'data/search-v2-voyage-canaries.json', 'evaluation/search_v2_hybrid_vector_build.json')


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_reconcile_spend_' + reason)


def context(state, generation=False):
    value = json.loads((Path(state) / ('vector-operation.json' if generation else 'reconciliation.json')).read_bytes())
    require(re.fullmatch('[a-f0-9]{64}', str(value.get('operation_sha256', '')))
            and identity({k: v for k, v in value.items() if k not in
                          {'operation_sha256', 'completed_candidate_id'}}) == value['operation_sha256']
            and re.fullmatch('[1-9][0-9]*', str(value.get('parent_run', ''))), 'operation_identity')
    return value


def local(book):
    return getattr(book, 'local', book)


def ledger(state, generation=False):
    contract = context(state, generation)
    path = Path(state) / 'ledger.json'
    require(path.is_file(), 'original_ledger_required')
    book = Ledger(path, 'offline-' + str(contract['parent_run']), 2, 300)
    if generation:
        require(contract.get('version') == 'generation-vector-operation-1'
                and contract.get('mode') in {'maintenance', 'pilot'}, 'generation_context')
        book = production_ledger(Path(state), contract['mode'])
        require(local(book).logical_id == 'offline-' + str(contract['parent_run'])
                and local(book).limit == 2_000_000 and local(book).max_requests == 300, 'generation_budget_identity')
    return book


@contextmanager
def request_locked(state, key):
    """Serialize identical reservations while retaining the existing ledger API."""
    path = Path(state) / 'vector-intents' / (key + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 10
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise Deferred('vector_request_lock_unavailable')
            time.sleep(.01)
    try:
        yield
    finally:
        path.unlink()


def request_id(value):
    # Voyage currently supplies hexadecimal request IDs. Other header values
    # are optional diagnostics, never permission to retain arbitrary text.
    return value if isinstance(value, str) and re.fullmatch('[a-fA-F0-9-]{16,128}', value) else None


def vector_usage(tokens):
    # Voyage bills document input tokens; retain its exact raw total in the
    # accepted response, and use the shared ledger's canonical usage schema.
    return dict(input_tokens=tokens, cached_input_tokens=0, cache_write_tokens=0,
                output_tokens=0, reasoning_tokens=0)


def protected_vector_asset(root, packet):
    """Reuse one intact protected asset, never mix rows across generations."""
    from tools import release_candidate as c
    from tools.release_dependencies import snapshot
    if packet.get('retained_asset_eligible') is not True:
        return None
    def protected(name):
        return json.loads(subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:' + name],
                                                  stderr=subprocess.DEVNULL))
    try:
        manifest, receipt, pointer = (protected(name) for name in
            ('release/candidate.json', 'release/validation.json', 'release/candidate-source.json'))
    except subprocess.CalledProcessError:
        return None  # A first publication has no protected asset to retain.
    candidate = manifest.get('candidate_id')
    require(candidate == c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
            and pointer.get('candidate_id') == candidate
            and receipt.get('candidate_id') == candidate
            and receipt.get('generation_sha') == manifest.get('generation_sha')
            and receipt.get('identity', {}).get('candidate_id') == candidate
            and receipt.get('identity', {}).get('candidate_hashes') == manifest.get('files')
            and receipt.get('gates') == {gate: 'passed' for gate in c.GATES}, 'protected_vector_provenance')
    semantic = manifest.get('dependency_groups', {}).get('semantic')
    if not semantic or semantic != snapshot(root)['semantic']:
        return None
    outputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in VECTOR_OUTPUTS}
    if any(manifest['files'].get(name) != value for name, value in outputs.items()):
        return None
    vectors = json.loads((root / VECTOR_OUTPUTS[0]).read_bytes())
    if any(vectors.get(key) != packet[key] for key in
           ('corpus_sha256', 'configuration_sha256', 'passage_count')):
        return None
    return {'protected_candidate_id': candidate, 'semantic_fingerprint': semantic['fingerprint'], 'outputs': outputs}


def prepare(state, packet, *, generation=False):
    """Bind ordinary vector work to existing source inputs and its existing book."""
    require(generation and packet.get('run_id') == os.environ.get('GITHUB_RUN_ID')
            and re.fullmatch('[1-9][0-9]*', str(packet.get('run_id', '')))
            and Path(state).name == 'offline-' + packet['run_id']
            and packet.get('mode') in {'maintenance', 'pilot'}, 'generation_owner')
    root = Path(__file__).resolve().parents[1]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in GENERATION_INPUTS}
    require(packet.get('source_hashes') == hashes
            and all(re.fullmatch('[a-f0-9]{64}', str(packet.get(key, ''))) for key in
                    ('corpus_sha256', 'configuration_sha256'))
            and type(packet.get('passage_count')) is int and packet['passage_count'] > 0, 'generation_inputs')
    path = Path(state) / 'ledger.json'
    require(path.is_file(), 'original_ledger_required')
    Ledger(path, 'offline-' + packet['run_id'], 2, 300)
    value = {'version': 'generation-vector-operation-1', 'parent_run': packet['run_id'], 'mode': packet['mode'],
             'operation_contract': {key: packet[key] for key in
                ('corpus_sha256', 'configuration_sha256', 'passage_count')}}
    # Incidental catalog timestamps do not change embedding inputs. Retain
    # exact observed bytes separately; corpus/config/code bind cache identity.
    value['operation_contract']['source_hashes'] = {k: v for k, v in hashes.items() if not k.startswith('data/')}
    value['operation_sha256'] = identity(value)
    archive = Path(state) / 'vector-operations' / (value['operation_sha256'] + '.json')
    if archive.exists():
        require(json.loads(archive.read_bytes()) == value, 'generation_operation_changed')
    else:
        atomic_json(archive, value)
    atomic_json(Path(state) / 'vector-operation.json', value)
    atomic_json(Path(state) / 'vector-inputs' / (identity(hashes) + '.json'), hashes)
    ledger(state, True)  # Also enforce the existing qualification task linkage.
    completed = Path(state) / 'vector-completions' / (value['operation_sha256'] + '.json')
    if completed.exists():
        receipt = json.loads(completed.read_bytes())
        actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in VECTOR_OUTPUTS}
        require(receipt == {'operation_sha256': value['operation_sha256'], 'outputs': actual}, 'completed_vectors_changed')
        return {'status': 'complete', 'operation_sha256': value['operation_sha256']}
    retained = protected_vector_asset(root, packet)
    if retained:
        atomic_json(completed, {'operation_sha256': value['operation_sha256'], 'outputs': retained['outputs']})
        atomic_json(Path(state) / 'vector-stage.json', {'version': 'generation-vector-stage-1',
                    'status': 'retained_complete_asset', 'operation_sha256': value['operation_sha256'],
                    'new_requests': 0, 'new_usage_total_tokens': 0, **retained})
        return {'status': 'complete', 'operation_sha256': value['operation_sha256'], 'new_requests': 0}
    return {'status': 'prepared', 'operation_sha256': value['operation_sha256']}


def checkpoint(state, packet, *, generation=False):
    require(generation, 'generation_checkpoint')
    value = context(state, True)
    require(packet.get('operation_sha256') == value['operation_sha256'], 'generation_checkpoint_identity')
    root = Path(__file__).resolve().parents[1]
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in VECTOR_OUTPUTS}
    require(packet.get('outputs') == actual, 'generation_checkpoint_outputs')
    atomic_json(Path(state) / 'vector-completions' / (value['operation_sha256'] + '.json'),
                {'operation_sha256': value['operation_sha256'], 'outputs': actual})
    return {'status': 'complete'}


def import_history(state, parent, original_ledger_sha256):
    """Append authenticated measured historical costs once; keep original prefix."""
    book = ledger(state)
    contract = context(state)
    manifest = json.loads((Path(parent) / 'candidate.json').read_bytes())
    require(manifest['candidate_id'] == contract['parent_candidate_id']
            and hashlib.sha256((Path(parent) / 'candidate.json').read_bytes()).hexdigest()
            == contract['parent_manifest_sha256']
            and original_ledger_sha256 == contract['original_spend']['ledger_sha256'], 'parent_identity')
    report_raw = (Path(parent) / 'files/evaluation/search_v2_hybrid_vector_build.json').read_bytes()
    require(hashlib.sha256(report_raw).hexdigest() == manifest['files'][
        'evaluation/search_v2_hybrid_vector_build.json'], 'parent_vector_receipt')
    report = json.loads(report_raw)
    rows = report.get('API_requests')
    require(isinstance(rows, list) and report.get('API_request_count') == len(rows)
            and report.get('model') == MODEL and report.get('status') == 'written', 'historical_receipt')
    historical = []
    for index, row in enumerate(rows):
        tokens = row.get('usage_total_tokens')
        require(type(tokens) is int and tokens > 0 and row.get('model') == MODEL
                and row.get('http_status') == 200 and isinstance(row.get('request_id'), str)
                and request_id(row['request_id']), 'historical_measured_usage')
        charge = (tokens + 49) // 50
        key = identity({'candidate_id': manifest['candidate_id'], 'index': index, 'receipt': row})
        historical.append({'id': key[:32], 'provider': 'voyage', 'model': MODEL,
            'stage': 'historical_vector_generation', 'key': key, 'attempt': 1,
            'reserved_microusd': charge, 'charged_microusd': charge,
            'status': 'valid', 'usage': vector_usage(tokens),
            'provider_request_id': row['request_id'], 'parent_candidate_id': manifest['candidate_id']})
    marker = {'kind': 'authenticated_vector_history', 'candidate_id': manifest['candidate_id'],
              'original_ledger_sha256': original_ledger_sha256,
              'receipt_sha256': hashlib.sha256(report_raw).hexdigest(), 'requests': historical}
    with book.locked():
        value = book.read()
        events = [e for e in value['events'] if e.get('kind') == marker['kind']]
        if events:
            require(len(events) == 1 and all(events[0].get(k) == v for k, v in marker.items()),
                    'historical_import_identity')
            n, e = events[0]['original_request_count'], events[0]['original_event_count']
            original = dict(value, requests=value['requests'][:n], events=value['events'][:e])
            require(identity(original) == original_ledger_sha256
                    and value['events'][e] == events[0], 'original_ledger_prefix')
            require(value['requests'][n:n + len(historical)] == historical
                    and [r for r in value['requests'] if r.get('stage') == 'historical_vector_generation'] == historical,
                    'historical_import_rows')
            return
        require(identity(value) == original_ledger_sha256, 'original_ledger_before_import')
        require(report.get('usage_total_tokens') == sum(row['usage_total_tokens'] for row in rows),
                'historical_usage_total')
        require(len(value['requests']) + len(historical) <= book.max_requests
                and sum(r['charged_microusd'] for r in value['requests'] + historical) <= book.limit,
                'historical_allowance')
        marker.update(original_request_count=len(value['requests']), original_event_count=len(value['events']))
        value['requests'].extend(historical)
        value['events'].append(marker)
        atomic_json(book.path, value)


def clean_payload(payload, count):
    data = payload.get('data'); usage = payload.get('usage') or {}
    tokens = usage.get('total_tokens')
    require(payload.get('model') == MODEL and type(tokens) is int and tokens > 0
            and isinstance(data, list) and len(data) == count
            and all(isinstance(r, dict) and type(r.get('index')) is int for r in data)
            and sorted(r['index'] for r in data) == list(range(count)), 'complete_response')
    for item in data:
        vector = item.get('embedding')
        require(isinstance(vector, list) and len(vector) == 1024
                and all(type(v) in (float, int) and math.isfinite(v) for v in vector)
                and any(vector), 'finite_vector')
    return {'model': MODEL, 'data': [{'index': r['index'], 'embedding': r['embedding']} for r in data],
            'usage': {'total_tokens': tokens}}


def saved_response(state, key, token, contract, body_sha256, count):
    path = Path(state) / 'vector-responses' / (key + '.json')
    saved = json.loads(path.read_bytes())
    require(saved.get('key') == key and saved.get('token') == token and saved.get('status') == 200
            and saved.get('operation_sha256') == contract['operation_sha256']
            and saved.get('body_sha256') == body_sha256, 'cached_response_identity')
    payload = clean_payload(saved['payload'], count)
    require(payload == saved['payload'] and saved.get('response_sha256') == identity(payload), 'cached_response_payload')
    return saved


def complete_saved(book, value, row, saved):
    charge = (saved['payload']['usage']['total_tokens'] + 49) // 50
    require(charge <= row['reserved_microusd'], 'usage_exceeds_reserved_bound')
    if row['status'] == 'valid':
        require(row.get('response_sha256') == saved['response_sha256']
                and row['charged_microusd'] == charge, 'completed_response_identity')
        return
    require(row['status'] == 'reserved_unknown', 'unfinished_reservation')
    book.complete(row['id'], status='valid', charged_microusd=charge,
                  usage=vector_usage(saved['payload']['usage']['total_tokens']),
                  response_sha256=saved['response_sha256'], provider_request_id=saved.get('request_id'))


def reserve(state, packet, *, generation=False):
    require(packet.get('url') == URL and isinstance(packet.get('body'), str), 'exact_transport')
    raw = packet['body'].encode()
    require(0 < len(raw) <= 4 * 1024 * 1024, 'bounded_request')
    body = json.loads(raw)
    require(set(body) == {'input', 'model', 'input_type', 'truncation', 'output_dimension', 'output_dtype'}
            and body['model'] == MODEL and body['input_type'] == 'document'
            and body['truncation'] is True and body['output_dimension'] == 1024
            and body['output_dtype'] == 'float' and isinstance(body['input'], list)
            and 0 < len(body['input']) <= 256
            and all(isinstance(s, str) and s for s in body['input']), 'request_contract')
    state = Path(state)
    contract = context(state, generation)
    body_sha256 = hashlib.sha256(raw).hexdigest()
    key = identity({'operation': contract['operation_sha256'], 'body_sha256': hashlib.sha256(raw).hexdigest()})
    book = ledger(state, generation)
    cache = state / 'vector-responses' / (key + '.json')
    current = local(book).read()
    if not any(row['key'] == key for row in current['requests']):
        intents = list((state / 'vector-intents').glob('*.json'))
        require(len(intents) <= local(book).max_requests, 'retained_intent_bound')
        for path in intents:
            old = json.loads(path.read_bytes())
            if old.get('body_sha256') != body_sha256 or old.get('key') == key:
                continue
            rows = [row for row in current['requests'] if row['id'] == old.get('token') and row['key'] == old.get('key')]
            require(len(rows) == 1, 'retained_intent_without_reservation')
            if rows[0]['status'] == 'reserved_unknown':
                old_cache = state / 'vector-responses' / (old['key'] + '.json')
                require(old_cache.is_file(), 'previous_operation_dispatch_unknown_no_retry')
                saved = saved_response(state, old['key'], old['token'],
                    {'operation_sha256': old['operation_sha256']}, body_sha256, old['input_count'])
                complete_saved(book, current, rows[0], saved)
                # Recover accounting, but do not mix old-space vectors into a
                # fresh homogeneous generation under changed semantic inputs.
                raise Deferred('previous_operation_response_recovered_retry_generation')
    def cached(value):
        prior = [r for r in value['requests'] if r['key'] == key]
        if prior:
            require(len(prior) == 1 and cache.is_file(), 'previous_dispatch_unknown_no_retry')
            saved = saved_response(state, key, prior[0]['id'], contract, body_sha256, len(body['input']))
            complete_saved(book, value, prior[0], saved)
            return {'status': 'cached', 'cache': str(cache.resolve())}
        return None
    # Accepted cache recovery precedes the dispatch mutex: a process dying
    # after response persistence must not strand already-paid work behind it.
    value = local(book).read()
    if cache.is_file():
        result = cached(value)
        require(result, 'orphan_response_cache')
        return result
    with request_locked(state, key):
        value = local(book).read()
        if not generation:
            require(any(e.get('kind') == 'authenticated_vector_history' and e.get('candidate_id') ==
                        contract['parent_candidate_id'] for e in value['events']), 'history_required')
        result = cached(value)
        if result:
            return result
        require(not cache.exists(), 'orphan_response_cache')
        # Reserve under the same lock as deduplication, before granting HTTP.
        amount = (len(raw) + 1024 + 49) // 50
        token = book.reserve('voyage', MODEL, 'generation_vectors' if generation else 'reconciled_vectors', key, amount, 1)
        atomic_json(state / 'vector-intents' / (key + '.json'), {'key': key, 'token': token,
            'operation_sha256': contract['operation_sha256'], 'input_count': len(body['input']), 'body_sha256': body_sha256})
        return {'status': 'reserved', 'key': key, 'token': token}


def finish(state, packet, *, generation=False):
    state = Path(state)
    key = packet['key']
    require(isinstance(key, str) and len(key) == 64 and all(c in '0123456789abcdef' for c in key), 'request_key')
    intent = json.loads((state / 'vector-intents' / (key + '.json')).read_bytes())
    contract = context(state, generation)
    require(packet['token'] == intent['token'] and intent['key'] == key
            and intent['operation_sha256'] == contract['operation_sha256']
            and key == identity({'operation': contract['operation_sha256'], 'body_sha256': intent['body_sha256']}), 'dispatch_token')
    book = ledger(state, generation)
    require(packet.get('status') == 200 and isinstance(packet.get('payload'), dict), 'unsuccessful_response')
    payload = clean_payload(packet['payload'], intent['input_count'])
    saved = {'key': key, 'token': intent['token'], 'payload': payload,
             'request_id': request_id(packet.get('request_id')), 'status': 200,
             'operation_sha256': contract['operation_sha256'], 'body_sha256': intent['body_sha256'],
             'response_sha256': identity(payload)}
    with request_locked(state, key):
        value = local(book).read()
        rows = [r for r in value['requests'] if r['id'] == intent['token'] and r['key'] == key]
        require(len(rows) == 1 and (payload['usage']['total_tokens'] + 49) // 50 <= rows[0]['reserved_microusd'], 'dispatch_reservation')
        cache = state / 'vector-responses' / (key + '.json')
        if cache.exists():
            require(saved_response(state, key, intent['token'], contract, intent['body_sha256'], intent['input_count']) == saved,
                    'accepted_response_changed')
        else:
            atomic_json(cache, saved)
        # A crash here is recovered from the validated accepted cache by reserve.
        complete_saved(book, value, rows[0], saved)
    return {'status': 'complete', 'cache': str(cache.resolve())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('reserve', 'finish', 'prepare', 'checkpoint'))
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--generation', action='store_true')
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_RESPONSE + 1)
    require(len(raw) <= MAX_RESPONSE, 'bounded_packet')
    result = globals()[args.action](args.state, json.loads(raw), generation=args.generation)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
