"""Execute one immutable catalog request in the existing serialized workflow."""
from decimal import Decimal
from datetime import datetime, timezone
import base64
import json
import math
import os
from pathlib import Path
import time

import requests

from tools import catalog_correction_policy as policy
from tools import team_recommender_executor as existing
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity

WORKER = 'https://funding-finder-voyage-search.urochestercheme.workers.dev/'
ORIGIN = 'https://mporosoff.github.io'


def usage(payload, op):
    value = payload.get('usage') if isinstance(payload, dict) else None
    tokens = value.get('total_tokens') if isinstance(value, dict) else None
    policy.require(type(tokens) is int and tokens > 0, 'actual_usage_required')
    divisor = 20 if op['model'] == 'rerank-2.5' else 50
    return {'total_tokens': tokens}, (tokens+divisor-1)//divisor


def vector(value):
    policy.require(isinstance(value, list) and len(value) == 1024 and all(
        type(v) in (float, int) and math.isfinite(v) for v in value)
        and sum(v*v for v in value) > 0, 'complete_finite_vector')


def validate_response(name, body, payload):
    op = policy.operation(name)
    policy.require(isinstance(payload, dict) and payload.get('model') == op['model'], 'returned_model')
    usage(payload, op)
    if name.startswith('embedding-'):
        rows = payload.get('data')
        policy.require(isinstance(rows, list) and len(rows) == len(body['input']) and all(
            isinstance(r, dict) and type(r.get('index')) is int for r in rows)
            and sorted(r['index'] for r in rows) == list(range(len(body['input']))), 'complete_owned_embedding_rows')
        for row in rows:
            vector(row.get('embedding'))
    elif name == 'smoke-embed':
        policy.require(set(payload) == {'model', 'embedding', 'usage', 'latency_ms'}
            and type(payload.get('latency_ms')) in (int, float) and math.isfinite(payload['latency_ms'])
            and payload['latency_ms'] >= 0, 'strict_worker_response')
        vector(payload.get('embedding'))
    else:
        policy.require(set(payload) == {'model', 'rankings', 'usage', 'latency_ms'}
            and type(payload.get('latency_ms')) in (int, float) and math.isfinite(payload['latency_ms'])
            and payload['latency_ms'] >= 0, 'strict_worker_response')
        rows = payload.get('rankings')
        policy.require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
            and set(rows[0]) == {'index', 'passage_id', 'relevance_score'}
            and type(rows[0].get('index')) is int and rows[0]['index'] == 0
            and rows[0].get('passage_id') == policy.plan()['smoke_shared_passage_id']
            and type(rows[0].get('relevance_score')) in (float, int)
            and math.isfinite(rows[0]['relevance_score']) and 0 <= rows[0]['relevance_score'] <= 1,
            'complete_owned_smoke_ranking')
    return payload


def input_body(inputs, name):
    op = policy.operation(name)
    raw = (Path(inputs)/op['body_file']).read_bytes()
    policy.require(existing.sha(raw) == op['wire_sha256'], 'exact_input_bytes')
    body = json.loads(raw)
    policy.require(identity(body) == op['body_sha256'] and len(encoded(body))+1024 == op['input_tokens'],
        'exact_body_and_complete_bound')
    return body


def capacity(state):
    """Reserve restoration capacity for all seven full responses before spending."""
    root = Path(state); ledger = existing.ExperimentLedger(root/'ledger.json').read()
    claimed = {r['purpose'] for r in ledger['requests']}
    future = sum((existing.PACKET_LIMIT if n.startswith('embedding-') else 65536)+4096
        for n, op in policy.plan()['operations'].items() if op['purpose'] not in claimed)
    current = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    # One interrupted promotion can retain a complete base64 diagnostic beside
    # its accepted cache. Base64 bounds even malformed/control-byte responses;
    # accepted serialized caches are independently checked against their bound.
    headroom = 4*((existing.PACKET_LIMIT+2)//3)+1024*1024
    policy.require(current+future+headroom <= existing.STATE_LIMIT, 'complete_persistence_capacity')
    return {'current_bytes': current, 'maximum_additional_bytes': future+headroom,
        'state_limit_bytes': existing.STATE_LIMIT}


def validate_vector_prefix(state, inputs, name, payload):
    """Use the release builder's same gates before buying another batch."""
    from tools.catalog_source_correction import validate_vector_prefix as validate
    validate(state, inputs, name, payload)


class CatalogRunner:
    def __init__(self, state, inputs, *, post=requests.post, crash=lambda boundary: None):
        self.state = Path(state); self.inputs = Path(inputs)
        self.ledger = existing.ExperimentLedger(self.state/'ledger.json')
        self.post = post; self.crash = crash

    def cached(self, name, body):
        key = policy.logical_key(name)
        rows = [r for r in self.ledger.read()['requests'] if r.get('key') == key]
        policy.require(len(rows) == 1 and rows[0]['status'] == 'valid', 'accepted_cache_required')
        saved = json.loads((self.state/'cache'/(key+'.json')).read_bytes())
        policy.require(set(saved) == {'key', 'body_sha256', 'model', 'request_id', 'response_text', 'response_sha256'}
            and all(saved.get(k) == rows[0].get(k) for k in ('key', 'body_sha256', 'model'))
            and saved['request_id'] == rows[0]['id'] and saved['body_sha256'] == identity(body)
            and existing.sha(saved['response_text'].encode('utf8')) == saved['response_sha256'], 'owned_exact_response_cache')
        payload = json.loads(saved['response_text'])
        validate_response(name, body, payload)
        received, charge = usage(payload, policy.operation(name))
        policy.require(rows[0]['usage'] == received and rows[0]['charged_microusd'] == charge, 'cache_usage_owner')
        return payload

    def execute(self, name, *, external_body=None, serving_proof=None):
        state = self.ledger.read(); policy.history(state); policy.counts(self.state)
        op = policy.operation(name); body = input_body(self.inputs, name)
        key = policy.logical_key(name); cache = self.state/'cache'/(key+'.json')
        if any(r.get('purpose') == op['purpose'] for r in state['requests']):
            return self.cached(name, body)
        policy.require(not cache.exists(), 'orphan_cache_no_dispatch')
        policy.envelope(state); capacity(self.state)
        for earlier, prior in policy.plan()['operations'].items():
            if any(r.get('purpose') == prior['purpose'] for r in state['requests']):
                self.cached(earlier, input_body(self.inputs, earlier))
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
            'User-Agent': 'FundingFinder-CatalogCorrection/1.0 (+https://github.com/mporosoff/grants-scraper)'}
        if name.startswith('embedding-'):
            secret = os.environ.get('VOYAGE_API_KEY')
            policy.require(bool(secret), 'embedding_credential_missing')
            headers['Authorization'] = 'Bearer '+secret
            url = 'https://api.voyageai.com/v1/embeddings'; sent = body
            policy.require(external_body is None and serving_proof is None, 'embedding_has_no_external_override')
        else:
            # This adapter must authenticate every module/configuration byte and
            # derive the public wrapper from the locked provider body. Caller
            # JSON, endpoint health or a claimed version is not provenance.
            from tools.catalog_source_correction import verify_smoke_dispatch
            sent = verify_smoke_dispatch(name, body, external_body, serving_proof)
            url = WORKER+('embed-query' if name == 'smoke-embed' else 'rerank')
            headers['Origin'] = ORIGIN
        token = self.ledger.reserve_experiment('voyage', op['model'], 2, key,
            op['maximum_microusd'], 1, trusted_route=True, input_tokens=op['input_tokens'], output_tokens=0,
            execution_metadata=policy.metadata(name) | {'code_sha': os.environ['GITHUB_SHA']})
        receipt = {'version': policy.VERSION, 'name': name, 'purpose': op['purpose'], 'key': key,
            'request_id': token, 'body_sha256': op['body_sha256'], 'sent_body_sha256': identity(sent),
            'provider': 'voyage', 'model': op['model'], 'reserved_microusd': op['maximum_microusd'],
            'status': 'reserved_unknown', 'automatic_retries': 0, 'code_sha': os.environ['GITHUB_SHA']}
        if serving_proof is not None:
            receipt['serving_proof'] = serving_proof
        started = time.monotonic(); self.crash('after_reserve')
        try:
            existing.checkpoint(self.state); self.crash('after_reservation_checkpoint')
            wire = (self.inputs/op['body_file']).read_bytes() if name.startswith('embedding-') else encoded(sent)
            receipt['external_http_body_sha256'] = existing.sha(wire)
            receipt['public_body_text'] = wire.decode('utf8') if not name.startswith('embedding-') else None
            response = self.post(url, headers=headers, data=wire, timeout=(10, 120), stream=True, allow_redirects=False)
            self.crash('after_dispatch'); receipt['http_status'] = response.status_code
            raw = existing.bounded_response(response, existing.PACKET_LIMIT if name.startswith('embedding-') else 65536)
            # Preserve the one complete response even if its validator rejects
            # it; malformed replies must never become invisible/free retries.
            diagnostic = {'version': policy.VERSION, 'request_id': token,
                'http_status': response.status_code, 'response_sha256': existing.sha(raw),
                'response_base64': base64.b64encode(raw).decode('ascii')}
            atomic_json(self.state/'diagnostics'/(token+'.json'), diagnostic)
            payload = json.loads(raw); actual_usage, charge = usage(payload, op)
            receipt.update(usage=actual_usage, charged_microusd=charge, response_sha256=existing.sha(raw))
            validate_response(name, body, payload)
            if name.startswith('embedding-'):
                validate_vector_prefix(self.state, self.inputs, name, payload)
            saved = {'key': key, 'body_sha256': op['body_sha256'], 'model': op['model'],
                'response_text': raw.decode('utf8'), 'response_sha256': existing.sha(raw), 'request_id': token}
            policy.require(len(encoded(saved)) <= (existing.PACKET_LIMIT if name.startswith('embedding-') else 65536)+4096,
                'serialized_cache_capacity')
            self.crash('before_reconcile')
            self.ledger.reconcile(token, cost_usd=Decimal(charge)/1000000, usage=actual_usage, status='valid')
            self.crash('after_reconcile')
            # Retain exact HTTP bytes once, including accepted vector precision.
            atomic_json(cache, saved)
            self.crash('after_cache')
            diagnostic.pop('response_base64')
            atomic_json(self.state/'diagnostics'/(token+'.json'), diagnostic)
            receipt['status'] = 'valid'
        except Exception as error:
            # A builder/subprocess failure after a complete usage receipt is a
            # known failed charge too. Always re-raise; never retry dispatch.
            row = next(r for r in self.ledger.read()['requests'] if r['id'] == token)
            if 'charged_microusd' in receipt and row['status'] == 'reserved_unknown':
                self.ledger.reconcile(token, cost_usd=Decimal(receipt['charged_microusd'])/1000000,
                    usage=receipt['usage'], status='failed')
            receipt['status'] = next(r for r in self.ledger.read()['requests'] if r['id'] == token)['status']
            receipt['error'] = type(error).__name__
            raise
        finally:
            # Reconciliation may already be durable when an interruption lands
            # between cache promotion and the in-memory receipt update.
            receipt['status'] = next(r for r in self.ledger.read()['requests'] if r['id'] == token)['status']
            receipt['elapsed_seconds'] = round(time.monotonic()-started, 6)
            receipt['completed_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            atomic_json(self.state/'receipts'/(token+'.json'), receipt)
            self.crash('after_receipt'); existing.checkpoint(self.state)
        return payload


def run(args):
    existing.trusted_environment()
    requested = json.loads(os.environ['CONTEXTUAL_CHECK'])
    if isinstance(requested, dict) and 'catalog_capacity' in requested:
        return install_capacity(args, requested)
    policy.require(set(requested) == {'catalog_correction'} and not any(os.environ.get(k) for k in
        ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')), 'exclusive_fixed_operation')
    name = requested['catalog_correction']; op = policy.operation(name)
    from tools.catalog_source_correction import prepare_inputs, smoke_dispatch_inputs
    inputs = Path(args.state).parent/'catalog-correction-inputs'
    if args.action == 'prepare':
        prepare_inputs(inputs)
        existing.restore(args.state, existing.policy())
        policy.require(policy.present(existing.ExperimentLedger(Path(args.state)/'ledger.json').read()),
            'separate_zero_provider_amendment_required')
    body = input_body(inputs, name); runner = CatalogRunner(args.state, inputs)
    state = runner.ledger.read(); policy.history(state); policy.counts(args.state)
    cache_only = any(r.get('purpose') == op['purpose'] for r in state['requests'])
    if cache_only:
        runner.cached(name, body)
    record = {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha': os.environ['GITHUB_SHA'], 'name': name, 'plan_sha256': policy.PLAN_SHA,
        'body_sha256': identity(body), 'additional_allowance': 0, 'automatic_retries': 0,
        'cache_only': cache_only,
        'maximum_new_microusd': 0 if cache_only else op['maximum_microusd'],
        'maximum_new_metered_attempts': 0 if cache_only else 1,
        'maximum_new_native_counts': 0, 'complete_remaining_inventory': policy.envelope(state),
        'persistence': capacity(args.state)}
    if args.action == 'prepare':
        atomic_json(args.reservation, record)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                credential = ('cache' if cache_only else 'voyage') if name.startswith('embedding-') else 'none'
                stream.write('text_provider=catalog\ncatalog_provider='+credential+'\n')
                stream.write('catalog_operation='+name+'\n')
        return
    # State bytes/size may change only through the prepared immutable operation.
    policy.require(json.loads(args.reservation.read_bytes()) == record, 'prepared_request_changed')
    value = None
    try:
        extra = {} if name.startswith('embedding-') else smoke_dispatch_inputs(args.state, inputs, name)
        value = runner.execute(name, **extra)
    finally:
        atomic_json(args.result, record | {'accepted_response_sha256': identity(value) if value is not None else None,
            'durable_requests': [r for r in runner.ledger.read()['requests'] if r.get('purpose') == op['purpose']]})
        existing.checkpoint(args.state)


def install_capacity(args, requested):
    """The approved inventory amendment is a separate zero-provider operation."""
    policy.require(requested == {'catalog_capacity': policy.VERSION} and not any(os.environ.get(k) for k in
        ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')), 'exact_capacity_selector')
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy())
        capacity(args.state)
        policy.install(args.state)
    ledger = existing.ExperimentLedger(Path(args.state)/'ledger.json').read()
    policy.history(ledger); policy.counts(args.state)
    policy.require(policy.present(ledger), 'durable_input_amendment_required')
    record = {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha': os.environ['GITHUB_SHA'], 'event': policy.scope_event(),
        'maximum_new_microusd': 0, 'maximum_new_metered_attempts': 0, 'maximum_new_native_counts': 0,
        'unchanged_financial_allowance': True, 'complete_remaining_inventory': policy.envelope(ledger)}
    if args.action == 'prepare':
        atomic_json(args.reservation, record)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=none\n')
    else:
        policy.require(json.loads(args.reservation.read_bytes()) == record, 'capacity_reservation_changed')
        atomic_json(args.result, record)
        retained = Path(args.state)/'cache'/(identity([policy.VERSION, 'capacity-receipt'])+'.json')
        if retained.exists():
            saved = json.loads(retained.read_bytes())
            policy.require(identity(saved.get('event')) == identity(policy.scope_event())
                and saved.get('authorization_id') == existing.AUTHORIZATION_ID
                and all(saved.get(k) == 0 for k in ('maximum_new_microusd', 'maximum_new_metered_attempts',
                    'maximum_new_native_counts')), 'original_capacity_receipt_changed')
        else:
            atomic_json(retained, record)
        existing.checkpoint(args.state)
