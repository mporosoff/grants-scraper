"""Durable Voyage requests inside the selected generation's existing allowance.

The Node preload calls these commands before/after its normal vector-builder
transport. Responses stay in the private checkpoint, never the candidate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import yaml

from tools.offline_spend import Deferred, Ledger, atomic_json, identity, production_ledger, exclusive_file_lock

MODEL = 'voyage-4-lite'
URL = 'https://api.voyageai.com/v1/embeddings'
MAX_RESPONSE = 24 * 1024 * 1024
GENERATION_INPUTS = (
    'tools/run_budgeted_vectors.mjs', 'tools/catalog_reconcile_vectors.mjs', 'tools/catalog_reconcile_spend.py',
    'tools/offline_spend.py', 'tools/build_search_v2_voyage_vectors.mjs', 'tools/embedding_contract.mjs',
    'tools/coherent_files.mjs',
    'tools/run_search_diagnosis.mjs', 'assets/search-hybrid.js', 'assets/search-retrieval.js',
    'assets/search-query.js', 'assets/search-v2-config.js', 'assets/match-explain.js',
    'config/offline_ai.json', 'data/opportunities.js', 'data/subtopics.js',
)
VECTOR_OUTPUTS = ('data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
                  'data/search-v2-voyage-canaries.json', 'evaluation/search_v2_hybrid_vector_build.json')
OUTPUT_VERSION = 'vector-output-checkpoint-2'


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
    with exclusive_file_lock(path, unavailable='vector_request_lock_unavailable'):
        yield


def request_id(value):
    # Voyage currently supplies hexadecimal request IDs. Other header values
    # are optional diagnostics, never permission to retain arbitrary text.
    return value if isinstance(value, str) and re.fullmatch('[a-fA-F0-9-]{16,128}', value) else None


def vector_usage(tokens):
    # Voyage bills document input tokens; retain its exact raw total in the
    # accepted response, and use the shared ledger's canonical usage schema.
    return dict(input_tokens=tokens, cached_input_tokens=0, cache_write_tokens=0,
                output_tokens=0, reasoning_tokens=0)


def retained_origin(root, binding, outputs, protected_ref, *, descendant='HEAD'):
    """Authenticate the exact protected asset from which zero new work arose."""
    from tools import release_candidate as c
    from tools.release_dependencies import snapshot
    require(isinstance(protected_ref, str) and re.fullmatch('[a-f0-9]{40}', protected_ref), 'protected_vector_ref')
    subprocess.check_output(['git', '-C', str(root), 'merge-base', '--is-ancestor', protected_ref, descendant],
                            stderr=subprocess.DEVNULL)
    def protected(name):
        return subprocess.check_output(['git', '-C', str(root), 'show', protected_ref + ':' + name],
                                       stderr=subprocess.DEVNULL)
    manifest, receipt, pointer = (json.loads(protected(name)) for name in
        ('release/candidate.json', 'release/validation.json', 'release/candidate-source.json'))
    candidate = manifest.get('candidate_id')
    require(candidate == c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
            and pointer.get('candidate_id') == candidate
            and receipt.get('candidate_id') == candidate
            and receipt.get('generation_sha') == manifest.get('generation_sha')
            and receipt.get('identity', {}).get('candidate_id') == candidate
            and receipt.get('identity', {}).get('candidate_hashes') == manifest.get('files')
            and receipt.get('gates') == {gate: 'passed' for gate in c.GATES}, 'protected_vector_provenance')
    semantic = manifest.get('dependency_groups', {}).get('semantic')
    require(semantic and semantic == snapshot(root, protected_ref)['semantic'], 'protected_vector_semantics')
    require(set(outputs) == set(VECTOR_OUTPUTS)
            and all(manifest['files'].get(name) == digest and hashlib.sha256(protected(name)).hexdigest() == digest
                    for name, digest in outputs.items()), 'protected_vector_outputs')
    vectors = json.loads(protected(VECTOR_OUTPUTS[0]))
    require(all(vectors.get(key) == binding[key] for key in
                ('corpus_sha256', 'configuration_sha256', 'passage_count')), 'protected_vector_corpus')
    return {'version': 'vector-accounting-origin-1', 'kind': 'retained', 'protected_ref': protected_ref,
            'protected_candidate_id': candidate, 'semantic_fingerprint': semantic['fingerprint'],
            'outputs': outputs, 'report_sha256': outputs[VECTOR_OUTPUTS[-1]], 'new_requests': 0}


def verify_retained_origin(root, origin, outputs, binding, *, descendant='HEAD'):
    require(isinstance(origin, dict) and type(origin.get('new_requests')) is int, 'retained_origin_identity')
    expected = retained_origin(root, binding, outputs, origin.get('protected_ref'), descendant=descendant)
    require(origin == expected, 'retained_origin_identity')
    return origin


def protected_vector_asset(root, packet):
    """Reuse one intact protected asset, never mix rows across generations."""
    from tools.release_dependencies import snapshot
    if packet.get('retained_asset_eligible') is not True:
        return None
    ref = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                  stderr=subprocess.DEVNULL).decode().strip()
    outputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in VECTOR_OUTPUTS}
    try:
        manifest = json.loads(subprocess.check_output(['git', '-C', str(root), 'show', ref + ':release/candidate.json'],
                                                     stderr=subprocess.DEVNULL))
        if (manifest.get('dependency_groups', {}).get('semantic') != snapshot(root)['semantic']
                or any(manifest.get('files', {}).get(name) != digest for name, digest in outputs.items())):
            return None
        vectors = json.loads((root / VECTOR_OUTPUTS[0]).read_bytes())
        if any(vectors.get(key) != packet[key] for key in ('corpus_sha256', 'configuration_sha256', 'passage_count')):
            return None
        origin = retained_origin(root, packet, outputs, ref)
    except subprocess.CalledProcessError:
        return None  # A first publication has no protected asset to retain.
    if origin['semantic_fingerprint'] != snapshot(root)['semantic']['fingerprint']:
        return None
    return {key: origin[key] for key in ('protected_ref', 'protected_candidate_id', 'semantic_fingerprint', 'outputs')} | {
        'accounting_origin': origin}


def vector_binding(packet):
    return {key: packet[key] for key in ('corpus_sha256', 'configuration_sha256', 'passage_count')} | {
        'source_hashes': {key: value for key, value in packet['source_hashes'].items() if not key.startswith('data/')}}


def output_bytes(root):
    raw = {name: (root / name).read_bytes() for name in VECTOR_OUTPUTS}
    require(all(0 < len(value) <= 32 * 1024 * 1024 for value in raw.values()), 'bounded_completed_outputs')
    return raw


def retain_outputs(state, value, binding, raw, origin):
    """Persist every completed byte before sealing the completion receipt."""
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    verify_output_origin(state, value, binding, raw, origin)
    for name, digest in hashes.items():
        blob = Path(state) / 'vector-outputs' / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        if blob.exists():
            require(hashlib.sha256(blob.read_bytes()).hexdigest() == digest, 'completed_output_blob_changed')
            continue
        descriptor, temporary = tempfile.mkstemp(prefix='.vector-', dir=blob.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw[name]); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, blob)
        finally:
            Path(temporary).unlink(missing_ok=True)
    receipt = {'version': OUTPUT_VERSION, 'operation_sha256': value['operation_sha256'],
               'vector_binding': binding, 'outputs': hashes, 'accounting_origin': origin}
    atomic_json(Path(state) / 'vector-completions' / (value['operation_sha256'] + '.json'), receipt)
    return receipt


def verify_output_origin(state, value, binding, raw, origin):
    require(isinstance(origin, dict) and origin.get('kind') in {'retained', 'budgeted'}, 'completed_origin_identity')
    if origin['kind'] == 'retained':
        root = Path(__file__).resolve().parents[1]
        verify_retained_origin(root, origin, {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}, binding)
    else:
        verify_budgeted_origin(state, value, raw, ledger(state, value.get('version') == 'generation-vector-operation-1'), origin)


def completed_outputs(state, value, binding, root):
    path = Path(state) / 'vector-completions' / (value['operation_sha256'] + '.json')
    if not path.exists():
        return None
    receipt = json.loads(path.read_bytes())
    require(set(receipt) == {'version', 'operation_sha256', 'vector_binding', 'outputs', 'accounting_origin'}
            and receipt['version'] == OUTPUT_VERSION and receipt['operation_sha256'] == value['operation_sha256']
            and receipt['vector_binding'] == binding and isinstance(receipt['outputs'], dict)
            and set(receipt['outputs']) == set(VECTOR_OUTPUTS)
            and all(re.fullmatch('[a-f0-9]{64}', str(digest)) for digest in receipt['outputs'].values()),
            'completed_vector_identity')
    blobs = {name: Path(state) / 'vector-outputs' / digest for name, digest in receipt['outputs'].items()}
    for name, path in blobs.items():
        require(path.is_file() and 0 < path.stat().st_size <= 32 * 1024 * 1024
                and hashlib.sha256(path.read_bytes()).hexdigest() == receipt['outputs'][name], 'completed_output_blob_changed')
    origin = receipt['accounting_origin']
    verify_output_origin(state, value, binding, {name: path.read_bytes() for name, path in blobs.items()}, origin)
    current = all((root / name).is_file()
                  and hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                  for name, digest in receipt['outputs'].items())
    return {'status': 'complete' if current else 'restore', 'operation_sha256': value['operation_sha256'],
            'outputs': receipt['outputs'], 'blobs': {name: str(path.resolve()) for name, path in blobs.items()},
            'accounting_origin': origin}


def prepare(state, packet, *, generation=False):
    """Bind vector work and completed bytes to the existing logical allowance."""
    root = Path(__file__).resolve().parents[1]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in GENERATION_INPUTS}
    require(packet.get('source_hashes') == hashes
            and all(re.fullmatch('[a-f0-9]{64}', str(packet.get(key, ''))) for key in
                    ('corpus_sha256', 'configuration_sha256'))
            and type(packet.get('passage_count')) is int and packet['passage_count'] > 0, 'generation_inputs')
    binding = vector_binding(packet)
    if not generation:
        value = context(state)
        book = ledger(state)
        require(any(event.get('kind') == 'authenticated_vector_history' and event.get('candidate_id') ==
                    value['parent_candidate_id'] for event in book.read()['events']), 'history_required')
        path = Path(state) / 'vector-bindings' / (value['operation_sha256'] + '.json')
        if path.exists():
            require(json.loads(path.read_bytes()) == binding, 'reconciliation_vector_inputs_changed')
        else:
            atomic_json(path, binding)
        return completed_outputs(state, value, binding, root) or {
            'status': 'prepared', 'operation_sha256': value['operation_sha256']}
    require(packet.get('run_id') == os.environ.get('GITHUB_RUN_ID')
            and re.fullmatch('[1-9][0-9]*', str(packet.get('run_id', '')))
            and Path(state).name == 'offline-' + packet['run_id']
            and packet.get('mode') in {'maintenance', 'pilot'}, 'generation_owner')
    path = Path(state) / 'ledger.json'
    require(path.is_file(), 'original_ledger_required')
    Ledger(path, 'offline-' + packet['run_id'], 2, 300)
    value = {'version': 'generation-vector-operation-1', 'parent_run': packet['run_id'], 'mode': packet['mode'],
             'operation_contract': binding}
    # Incidental catalog timestamps do not change embedding inputs. Retain
    # exact observed bytes separately; corpus/config/code bind cache identity.
    value['operation_sha256'] = identity(value)
    archive = Path(state) / 'vector-operations' / (value['operation_sha256'] + '.json')
    if archive.exists():
        require(json.loads(archive.read_bytes()) == value, 'generation_operation_changed')
    else:
        atomic_json(archive, value)
    atomic_json(Path(state) / 'vector-operation.json', value)
    atomic_json(Path(state) / 'vector-inputs' / (identity(hashes) + '.json'), hashes)
    ledger(state, True)  # Also enforce the existing qualification task linkage.
    completed = completed_outputs(state, value, binding, root)
    if completed:
        return completed
    retained = protected_vector_asset(root, packet)
    if retained:
        origin = retained['accounting_origin']
        raw = output_bytes(root)
        retain_outputs(state, value, binding, raw, origin)
        atomic_json(Path(state) / 'vector-stage.json', {'version': 'generation-vector-stage-1',
                    'status': 'retained_complete_asset', 'operation_sha256': value['operation_sha256'],
                    'new_requests': 0, 'new_usage_total_tokens': 0, **retained})
        return {'status': 'complete', 'operation_sha256': value['operation_sha256'], 'new_requests': 0}
    return {'status': 'prepared', 'operation_sha256': value['operation_sha256']}


def checkpoint(state, packet, *, generation=False):
    value = context(state, generation)
    book = ledger(state, generation)
    require(packet.get('operation_sha256') == value['operation_sha256'], 'generation_checkpoint_identity')
    root = Path(__file__).resolve().parents[1]
    binding = value['operation_contract'] if generation else json.loads((Path(state) / 'vector-bindings' /
                        (value['operation_sha256'] + '.json')).read_bytes())
    raw = output_bytes(root)
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    require(packet.get('outputs') == actual, 'generation_checkpoint_outputs')
    prior = completed_outputs(state, value, binding, root)
    require(prior is None or prior['outputs'] == actual, 'completed_vectors_changed')
    origin = prior['accounting_origin'] if prior else budgeted_origin(state, value, raw, book)
    retain_outputs(state, value, binding, raw, origin)
    if packet.get('restored') is True:
        atomic_json(Path(state) / 'vector-stage.json', {'version': 'generation-vector-stage-1',
                    'status': 'restored_complete_asset', 'operation_sha256': value['operation_sha256'],
                    'new_requests': 0, 'new_usage_total_tokens': 0, 'outputs': actual, 'accounting_origin': origin})
    return {'status': 'complete'}


def vector_report(raw):
    report = json.loads(raw)
    rows = report.get('API_requests')
    require(isinstance(rows, list) and report.get('API_request_count') == len(rows)
            and report.get('model') == MODEL and report.get('status') == 'written'
            and all(type(row.get('usage_total_tokens')) is int and row['usage_total_tokens'] > 0
                    and row.get('model') == MODEL and row.get('http_status') == 200 for row in rows)
            and report.get('usage_total_tokens') == sum(row['usage_total_tokens'] for row in rows),
            'historical_receipt')
    return report


def budgeted_origin(state, value, raw, book):
    """Bind a completed build to paid logical requests, including cached replay."""
    require(set(raw) == set(VECTOR_OUTPUTS), 'budgeted_output_inventory')
    report = vector_report(raw[VECTOR_OUTPUTS[-1]])
    public = Counter()
    for row in report['API_requests']:
        require(type(row.get('passage_count')) is int and 0 < row['passage_count'] <= 256
                and (row.get('request_id') is None or request_id(row['request_id'])), 'budgeted_report_request')
        public[(row.get('request_id'), row['passage_count'], row['usage_total_tokens'])] += 1
    current = local(book).read()
    intents = {}
    paths = list((Path(state) / 'vector-intents').glob('*.json'))
    require(len(paths) <= local(book).max_requests, 'retained_intent_bound')
    for path in paths:
        intent = json.loads(path.read_bytes())
        if intent.get('operation_sha256') != value['operation_sha256']:
            continue
        require(path.stem == intent.get('key') and intent['key'] == identity({
                    'operation': value['operation_sha256'], 'body_sha256': intent.get('body_sha256')})
                and isinstance(intent.get('body_sha256'), str) and re.fullmatch('[a-f0-9]{64}', intent['body_sha256'])
                and type(intent.get('input_count')) is int and 0 < intent['input_count'] <= 256
                and intent['key'] not in intents, 'budgeted_intent_identity')
        intents[intent['key']] = intent
    covered, requests = Counter(), []
    for row in current['requests']:
        intent = intents.get(row['key'])
        if intent is None:
            continue
        require(row['id'] == intent.get('token') and row.get('provider') == 'voyage'
                and row.get('model') == MODEL and row.get('stage') in ('generation_vectors', 'reconciled_vectors')
                and row.get('status') == 'valid', 'budgeted_ledger_request')
        saved = saved_response(state, row['key'], row['id'], value, intent['body_sha256'], intent['input_count'])
        tokens = saved['payload']['usage']['total_tokens']; charge = (tokens + 49) // 50
        require(row.get('response_sha256') == saved['response_sha256']
                and row.get('charged_microusd') == charge <= row['reserved_microusd']
                and row.get('usage') == vector_usage(tokens)
                and row.get('provider_request_id') == saved.get('request_id'), 'budgeted_measured_usage')
        covered[(saved.get('request_id'), intent['input_count'], tokens)] += 1
        requests.append({'id': row['id'], 'key': row['key'], 'body_sha256': intent['body_sha256'],
            'response_sha256': saved['response_sha256'], 'input_count': intent['input_count'],
            'usage_total_tokens': tokens, 'charged_microusd': charge})
    # A cached logical HTTP response can appear repeatedly in a reconstructed
    # public receipt while its atomic reservation remains a single paid call.
    require(requests and len(requests) == len(intents)
            and set(public) == set(covered) and all(public[key] >= count for key, count in covered.items()),
            'budgeted_report_coverage')
    outputs = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    return {'version': 'vector-accounting-origin-1', 'kind': 'budgeted',
        'logical_id': local(book).logical_id, 'operation_sha256': value['operation_sha256'],
        'outputs': outputs, 'report_sha256': outputs[VECTOR_OUTPUTS[-1]], 'requests': requests}


def verify_budgeted_origin(state, value, raw, book, origin):
    require(origin == budgeted_origin(state, value, raw, book), 'budgeted_origin_identity')
    return origin


def parent_vector_mode(manifest, contract):
    """Use the event workflow definition, separately from its checkout plan."""
    from tools import release_candidate as c
    require(not manifest.get('derived_from_candidate'), 'original_generation_parent_required')
    producer = contract.get('parent_producer') or {}
    require(manifest.get('generation_run_id') == contract['parent_run'] == producer.get('run_id')
            and manifest.get('generation_run_attempt') == producer.get('run_attempt')
            and manifest.get('generation_sha') == contract.get('parent_generation_sha')
            and isinstance(manifest.get('generation_sha'), str) and re.fullmatch('[a-f0-9]{40}', manifest['generation_sha'])
            and isinstance(producer.get('head_sha'), str) and re.fullmatch('[a-f0-9]{40}', producer['head_sha'])
            and producer.get('path') == '.github/workflows/refresh-opportunities.yml'
            and producer.get('event') in ('push', 'schedule', 'workflow_dispatch'), 'parent_vector_producer')
    workflow = yaml.safe_load(c.git(c.ROOT, 'show', producer['head_sha'] + ':' + producer['path']))
    steps = workflow.get('jobs', {}).get('generate', {}).get('steps', [])
    selected = [step for step in steps if step.get('id') == 'semantic-vectors']
    require(len(selected) == 1, 'parent_vector_invocation')
    command = selected[0].get('run', '').strip()
    if command == 'node tools/build_search_v2_voyage_vectors.mjs --production --write':
        return 'legacy'
    require(command == 'node tools/run_budgeted_vectors.mjs --production --write', 'parent_vector_invocation')
    return 'managed'


def parent_vector_accounting(state, parent, manifest, contract, book, original):
    mode = parent_vector_mode(manifest, contract)
    if mode == 'legacy':
        require(not (Path(state) / 'vector-operation.json').exists()
                and not any(row.get('provider') == 'voyage' for row in original['requests']),
                'legacy_mixed_vector_accounting')
        return {'classification': 'legacy_untracked'}, None
    value = context(state, generation=True)
    require(value.get('version') == 'generation-vector-operation-1' and value.get('mode') == 'maintenance'
            and value['parent_run'] == contract['parent_run'], 'parent_vector_operation')
    completion_path = Path(state) / 'vector-completions' / (value['operation_sha256'] + '.json')
    completion = json.loads(completion_path.read_bytes())
    outputs = {name: manifest['files'][name] for name in VECTOR_OUTPUTS}
    require(completion.get('version') == OUTPUT_VERSION and completion.get('operation_sha256') == value['operation_sha256']
            and completion.get('vector_binding') == value['operation_contract']
            and completion.get('outputs') == outputs, 'parent_vector_completion')
    raw = {name: (Path(parent) / 'files' / name).read_bytes() for name in VECTOR_OUTPUTS}
    for name, digest in outputs.items():
        blob = Path(state) / 'vector-outputs' / digest
        require(hashlib.sha256(raw[name]).hexdigest() == digest and blob.is_file()
                and hashlib.sha256(blob.read_bytes()).hexdigest() == digest, 'parent_vector_output')
    origin = completion.get('accounting_origin') or {}
    if origin.get('kind') == 'budgeted':
        verify_budgeted_origin(state, value, raw, book, origin)
    else:
        require(origin.get('kind') == 'retained', 'parent_vector_origin_required')
        verify_retained_origin(Path(__file__).resolve().parents[1], origin, outputs, value['operation_contract'],
                               descendant=manifest['generation_sha'])
        require(not any(json.loads(path.read_bytes()).get('operation_sha256') == value['operation_sha256']
                    for path in (Path(state) / 'vector-intents').glob('*.json')), 'retained_operation_dispatched')
    return {'classification': origin['kind'], 'completion_sha256': hashlib.sha256(completion_path.read_bytes()).hexdigest(),
            'accounting_origin': origin}, raw


def import_history(state, parent, original_ledger_sha256):
    """Classify original vector accounting; import only unwrapped paid history."""
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
    report = vector_report(report_raw)
    with book.locked():
        value = book.read()
        events = [event for event in value['events'] if event.get('kind') == 'authenticated_vector_history']
        if events:
            require(len(events) == 1, 'historical_import_identity')
            n, e = events[0]['original_request_count'], events[0]['original_event_count']
            original = dict(value, requests=value['requests'][:n], events=value['events'][:e])
            require(identity(original) == original_ledger_sha256
                    and value['events'][e] == events[0], 'original_ledger_prefix')
        else:
            require(identity(value) == original_ledger_sha256, 'original_ledger_before_import')
            original = value
        accounting, _ = parent_vector_accounting(state, parent, manifest, contract, book, original)
        historical = []
        if accounting['classification'] == 'legacy_untracked':
            for index, row in enumerate(report['API_requests']):
                require(isinstance(row.get('request_id'), str) and request_id(row['request_id']), 'historical_measured_usage')
                tokens = row['usage_total_tokens']; charge = (tokens + 49) // 50
                key = identity({'candidate_id': manifest['candidate_id'], 'index': index, 'receipt': row})
                historical.append({'id': key[:32], 'provider': 'voyage', 'model': MODEL,
                    'stage': 'historical_vector_generation', 'key': key, 'attempt': 1,
                    'reserved_microusd': charge, 'charged_microusd': charge,
                    'status': 'valid', 'usage': vector_usage(tokens),
                    'provider_request_id': row['request_id'], 'parent_candidate_id': manifest['candidate_id']})
        marker = {'kind': 'authenticated_vector_history', 'candidate_id': manifest['candidate_id'],
                  'original_ledger_sha256': original_ledger_sha256,
                  'receipt_sha256': hashlib.sha256(report_raw).hexdigest(), 'requests': historical,
                  **accounting}
        if events:
            require(all(events[0].get(key) == expected for key, expected in marker.items()), 'historical_import_identity')
            require(value['requests'][n:n + len(historical)] == historical
                    and [row for row in value['requests'] if row.get('stage') == 'historical_vector_generation'] == historical,
                    'historical_import_rows')
            return
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
    intents = list((state / 'vector-intents').glob('*.json'))
    require(len(intents) <= local(book).max_requests, 'retained_intent_bound')
    recovered, unknown_same_body = False, False
    for path in intents:
        old = json.loads(path.read_bytes())
        require(isinstance(old, dict) and all(isinstance(old.get(field), str)
                and re.fullmatch('[a-f0-9]{64}', old[field]) for field in
                ('key', 'operation_sha256', 'body_sha256'))
                and path.stem == old['key']
                and old['key'] == identity({'operation': old['operation_sha256'], 'body_sha256': old['body_sha256']})
                and type(old.get('input_count')) is int and 0 < old['input_count'] <= 256,
                'retained_intent_identity')
        if old['key'] == key:
            continue
        rows = [row for row in current['requests'] if row['id'] == old.get('token') and row['key'] == old['key']]
        require(len(rows) == 1, 'retained_intent_without_reservation')
        if rows[0]['status'] != 'reserved_unknown':
            continue
        old_cache = state / 'vector-responses' / (old['key'] + '.json')
        if old_cache.is_file():
            # Accepted usage belongs to its original request, independently of
            # the body/configuration the next generation now needs.
            saved = saved_response(state, old['key'], old['token'],
                {'operation_sha256': old['operation_sha256']}, old['body_sha256'], old['input_count'])
            complete_saved(book, current, rows[0], saved)
            recovered = True
        elif old['body_sha256'] == body_sha256:
            unknown_same_body = True
    if recovered:
        # Settle accounting, but never return old-space vectors to a new build.
        raise Deferred('previous_operation_response_recovered_retry_generation')
    require(not unknown_same_body, 'previous_operation_dispatch_unknown_no_retry')
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
