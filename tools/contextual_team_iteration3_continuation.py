"""Execute one named correction; each predecessor is a durable validated cache.

The existing serialized protected workflow retains the complete state between
operations. No operation generates interpretation, retrieval or assessment.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import time

from tools import contextual_team_iteration3 as original
from tools import contextual_team_iteration3_policy as prior_policy
from tools import contextual_team_iteration3_continuation_policy as policy
from tools import contextual_team_iteration3_references as references
from tools import contextual_team_verifier_states as verifier
from tools import contextual_team_iteration3_integrity as integrity
from tools import contextual_team_iteration3_check as independent
from tools import contextual_team_iteration2_contract as scientific
from tools import contextual_team_iteration2_policy as historical
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired, validate_cache_identity
from tools.contextual_team_luna_repair import RepairRunner
from tools.contextual_team_cost import no_provider_cache
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity

EC_VERSION = 'contextual-iteration3-ec-complete-evaluation-read240-v2'
AI_ASSESSMENT_ID = 'd4d6afd5ea1f4920a10239e69c481f1b'
AI_ASSESSMENT_BODY = 'ce0a986e670b592848be2e3da2208cf20a45fbee36c4cfe4968cfe7f88f7a02f'


def _require(ok, why):
    if not ok:
        raise ConfigurationFailure('iteration3_continuation_' + why)


def configuration():
    config = original.configuration()
    config['scopes'] = [s for s in config['scopes'] if s['id'] == '363268']
    config['snapshot_id'] = policy.plan()['release_id']
    config['iteration3_continuation'] = policy.plan()
    return config


def retained_ai(state):
    """Read the complete accepted 48-row assessment with its original identity."""
    config, scope, data, retrieval, contracts, vectors = original.retained_inputs(state, '363268')
    ledger = existing.ExperimentLedger(Path(state)/'ledger.json').read()
    contract, body = references.assessment_body(data)
    purpose = prior_policy.operation('363268', 'assess'); input_id = identity(data)
    expected = prior_policy.packet_event(purpose, body, contract, input_id)
    events = [e for e in ledger['events'] if e.get('authority') == prior_policy.VERSION and e.get('purpose') == purpose]
    rows = [r for r in ledger['requests'] if r.get('purpose') == purpose]
    key = identity([existing.AUTHORIZATION_ID, 'contextual-v1', [prior_policy.VERSION, purpose, identity(contract), input_id]])
    _require(events == [expected] and len(rows) == 1 and rows[0].get('id') == AI_ASSESSMENT_ID
        and rows[0].get('status') == 'valid' and rows[0].get('key') == key
        and identity(body) == AI_ASSESSMENT_BODY, 'accepted_48_answer_assessment_identity')
    saved = json.loads((Path(state)/'cache'/(key+'.json')).read_bytes())
    validate_cache_identity(saved, rows[0], body, 'openai')
    assessment = references.assessment_validate_cached(saved['value'], data)
    _require(len(data['people']) == 12 and sum(len(p['decisions']) for p in assessment['people']) == 48,
        'complete_retained_ai_frame')
    contracts['adjudication'] = identity(contract)
    return {'configuration': config, 'scope': scope, 'data': data, 'assessment': assessment,
        'retrieval': retrieval, 'contracts': contracts, 'vectors': vectors}


class ContinuationRunner(RepairRunner):
    def __init__(self, state, *, post=None, counter_post=None):
        super().__init__(state, configuration(), **({'post': post} if post is not None else {}))
        self.counter = Counter(self.state, **({'post': counter_post} if counter_post is not None else {}))
        self.timings = []

    def has_unknown_request(self):
        try:
            policy.history(self.ledger.read()); policy.counts(self.state)
            return False
        except (ValueError, Deferred):
            return True

    def request_provider(self, purpose, body):
        policy.name_of(purpose)
        _require(body.get('model') == 'claude-sonnet-5', 'fixed_provider_model')
        return 'anthropic'

    def provider_read_timeout(self, purpose, provider, body):
        # The only observed defect was the 120s EC HTTP read timeout. This
        # exact replacement retains its packet and raises only that boundary.
        return 240 if purpose == policy.operation('ec_check') else super().provider_read_timeout(purpose, provider, body)

    def reservation_cost(self, purpose, body, metadata):
        policy.history(self.ledger.read()); policy.counts(self.state)
        _require(not any(r.get('purpose') == purpose for r in self.ledger.read()['requests']), 'claimed_request_no_count')
        started = time.monotonic()
        native = self.counter.count({'id': purpose, 'body': body}); key = identity(count_projection(body))
        rows = [r for r in policy.counts(self.state) if r['key'] == key]
        _require(len(rows) == 1 and rows[0]['status'] == 'complete' and rows[0]['input_tokens'] == native, 'count_provenance')
        bound = math.ceil(native*1.2)+1024
        self.timings.append({'stage': 'native_count', 'operation': purpose, 'seconds': time.monotonic()-started,
            'reused_prior_count': rows[0]['id'] != purpose})
        return bound, bound*2+body['max_tokens']*10, {
            'native_count_key': key, 'count_body_sha256': key, 'native_input_tokens': native}

    def cached(self, name, contract, body, input_id, check):
        purpose = policy.operation(name)
        expected = policy.packet_event(name, body, contract, input_id)
        ledger = self.ledger.read()
        _require([e for e in ledger['events'] if e.get('authority') == policy.VERSION and e.get('purpose') == purpose] == [expected],
            'predecessor_exact_operation')
        key = identity([existing.AUTHORIZATION_ID, 'contextual-v1', [policy.VERSION, purpose, identity(contract), input_id]])
        rows = [r for r in ledger['requests'] if r.get('purpose') == purpose]
        _require(len(rows) == 1 and rows[0]['key'] == key and rows[0]['status'] == 'valid', 'accepted_predecessor_required')
        saved = json.loads((self.state/'cache'/(key+'.json')).read_bytes())
        validate_cache_identity(saved, rows[0], body, 'anthropic')
        value = check(saved['value'], cached=True)
        self.used.append({'key': key, 'request_id': rows[0]['id'], 'cache_hit': True})
        return value

    def execute_named(self, name):
        policy.history(self.ledger.read()); policy.counts(self.state)
        c, body, check, _, input_id = prepared(self.state, name)
        no_provider_cache(body)
        metadata = policy.bind_operation(self.ledger, name, body, c, input_id)
        if any(r.get('purpose') == policy.operation(name) for r in self.ledger.read()['requests']):
            return self.cached(name, c, body, input_id, check)
        started = time.monotonic()
        value = Runner.request(self, policy.operation(name), [policy.VERSION, policy.operation(name), identity(c), input_id],
            body, check, ceiling=policy.plan()['input_token_ceiling'], repair_metadata=metadata)
        self.timings.append({'stage': name, 'seconds': time.monotonic()-started, 'cache_hit': False})
        return value

    def run_stage(self, scope, stage):
        _require(scope in self.configuration['scopes'] and stage in ('assess', 'verify', 'integrity'), 'exact_ai_build_stage')
        policy.history(self.ledger.read()); policy.counts(self.state)
        if stage == 'assess':
            started = time.monotonic(); retained_ai(self.state)
            self.timings.append({'stage': 'assess', 'seconds': time.monotonic()-started,
                'cache_hit': True, 'request_id': AI_ASSESSMENT_ID})
            return {'state': 'stage_complete', 'stage': stage, 'scope_id': '363268'}
        if stage == 'verify':
            self.execute_named('ai_verify')
            actual = ai_graph(self.state, through='verify')
            self.integrity_generation_required = actual['verified']['state'] == 'coherent' and bool(integrity.inputs(
                actual['data'], actual['graph'], [p['person_id'] for p in actual['configuration']['people']])['candidates'])
            if actual['verified']['state'] == 'coherent':
                return {'state': 'stage_complete', 'stage': stage, 'scope_id': '363268'}
        else:
            actual = ai_graph(self.state, through='verify')
            if actual['verified']['state'] == 'coherent' and integrity.inputs(actual['data'], actual['graph'],
                    [p['person_id'] for p in actual['configuration']['people']])['candidates']:
                self.execute_named('ai_integrity')
            actual = ai_graph(self.state)
        save_graph(self.state, actual['graph'])
        return actual['graph']


def prepare_job(state_path, reservation, job):
    from tools.contextual_team_executor import resolve_job
    resolve_job(configuration(), job)
    policy.install_authority(state_path, contextual_job=job)
    runner = ContinuationRunner(state_path)
    c, body, _, _, input_id = prepared(state_path, 'ai_verify')
    policy.bind_operation(runner.ledger, 'ai_verify', body, c, input_id)
    state = runner.ledger.read(); envelope = policy.finite_envelope(state, policy.counts(state_path))
    atomic_json(reservation, {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'job_id': job['job_id'], 'scope_id': '363268', 'release_id': policy.plan()['release_id'],
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'additional_allowance': 0, 'automatic_retries': 0, 'public_activation': False,
        'maximum_new_microusd': 1080000, 'maximum_new_metered_attempts': 2, 'maximum_new_native_counts': 2,
        'complete_remaining_inventory': envelope, 'retained_assessment_request': AI_ASSESSMENT_ID,
        'verify_packet': policy.packet_event('ai_verify', body, c, input_id)})
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('text_provider=mixed\niteration3=true\ni3_assess_provider=none\n')
            for stage in ('verify', 'integrity'):
                claimed = any(r.get('purpose') == policy.operation('ai_'+stage) for r in state['requests'])
                stream.write('i3_'+stage+'_provider='+('none' if claimed else 'anthropic')+'\n')

def ai_verify_packet(actual):
    data, assessment = actual['data'], actual['assessment']
    c, body = verifier.verifier_body(data, assessment)
    # Preserve the canonical scientific contract; the exact verification input
    # remains blinded to all assessor rationales.
    check = lambda v, cached: verifier.verifier_validate_cached(v, data, assessment) if cached else verifier.verifier_parse(v, data, assessment)
    return c, body, check


def _input_id(contract, actual=None):
    if contract['version'] == verifier.VERSION:
        return identity(scientific.verification_inputs(actual['data'], actual['assessment']))
    return contract.get('evidence_sha256', contract.get('input_sha256'))


def ai_graph(state, *, through='integrity'):
    actual = retained_ai(state); runner = ContinuationRunner(state)
    c, body, check = ai_verify_packet(actual)
    verified = runner.cached('ai_verify', c, body, _input_id(c, actual), check)
    ledger = runner.ledger.read()
    purposes = {historical.operation('363268', 'interpret'), prior_policy.operation('363268', 'assess'), policy.operation('ai_verify')}
    lineage = {r['key']: {'key': r['key'], 'request_id': r['id']} for r in ledger['requests'] if r.get('purpose') in purposes}
    lineage.update({r['key']: {'key': r['key'], 'request_id': r['request_id']} for r in actual['vectors']})
    config = configuration(); scope = next(s for s in config['scopes'] if s['id'] == '363268')
    graph = scientific.adapter(actual['data'], actual['assessment'], verified, config, scope, actual['retrieval'],
        [lineage[k] for k in sorted(lineage)])
    graph.update(contracts=actual['contracts'] | {'verification': identity(c)},
        catalog_source_id=scope.get('catalog_source_id'),
        source_receipt_id=identity(scope['source_receipt']) if 'source_receipt' in scope else None,
        execution_capacity={'version': policy.VERSION, 'authority': policy.VERSION, 'automatic_retries': 0,
            'new_document_purchases': False, 'historical_science_retained': True})
    graph['graph_id'] = identity({k: v for k, v in graph.items() if k not in ('requests', 'graph_id')})
    actual.update(configuration=config, scope=scope, verified=verified, graph=graph)
    if through == 'verify' or verified['state'] != 'coherent':
        return actual
    eligible = [p['person_id'] for p in config['people']]
    if integrity.inputs(actual['data'], graph, eligible)['candidates']:
        c, body = integrity.body(actual['data'], graph, eligible)
        check = lambda v, cached: integrity.validate_cached(v, actual['data'], graph, eligible) if cached else integrity.parse(v, actual['data'], graph, eligible)
        value = runner.cached('ai_integrity', c, body, c['input_sha256'], check)
    else:
        value = integrity.empty_result(actual['data'], graph, eligible)
    actual['graph'] = integrity.adapter(actual['data'], graph, value, eligible)
    return actual


def ec_packet(state):
    actual = original.actual_result(state, '344592:ab-0025')
    selection = independent.select(actual['graph'], direct_source=True)
    old, body, previous, report = independent.packet(actual['scope'], actual['graph'], actual['assessment'], selection,
        actual['configuration'], generation_id=prior_policy.plan()['release_id'])
    _require(identity(body) == 'f3e2b5d4c0e4f29f0197be30c9713836debd1106d6148c5956b935f0eb2e1fae'
        and identity(old) == '65e76545438515c69539f6a7f370e33d1669b99bfcd7cee2f0c9e04d34bf3443',
        'exact_original_ec_packet')
    c = deepcopy(old) | {'version': EC_VERSION, 'preceding_contract_sha256': identity(old),
        'replacement_of': '534aba746f3044978f83262b69c1d073', 'read_timeout_seconds': 240, 'automatic_retries': 0}
    def check(value, cached):
        if cached:
            _require(isinstance(value, dict) and set(value) == {'version', 'contract_sha256', 'independent_result'}
                and value['version'] == EC_VERSION and value['contract_sha256'] == identity(c), 'ec_cache_lineage')
            previous(value['independent_result'], True)
            return value
        return {'version': EC_VERSION, 'contract_sha256': identity(c), 'independent_result': previous(value, False)}
    return c, body, check, report | {'historical_missing_judgments': 13, 'replacement_question_count': 13,
        'original_unknown_hold_microusd': 153198, 'recovered_original_response': False}


def prepared(state, name):
    _require(name in policy.OPERATIONS, 'unapproved_operation')
    if name == 'ai_verify':
        actual = retained_ai(state); c, body, check = ai_verify_packet(actual)
        return c, body, check, {'complete_people': 12, 'complete_answers': 48,
            'accepted_assessment_request': AI_ASSESSMENT_ID}, _input_id(c, actual)
    if name == 'ai_integrity':
        actual = ai_graph(state, through='verify'); eligible = [p['person_id'] for p in actual['configuration']['people']]
        _require(actual['verified']['state'] == 'coherent', 'integrity_not_applicable_verifier_abstention')
        _require(bool(integrity.inputs(actual['data'], actual['graph'], eligible)['candidates']), 'integrity_not_applicable_no_candidates')
        c, body = integrity.body(actual['data'], actual['graph'], eligible)
        check = lambda v, cached: integrity.validate_cached(v, actual['data'], actual['graph'], eligible) if cached else integrity.parse(v, actual['data'], actual['graph'], eligible)
        return c, body, check, {'base_graph_id': actual['graph']['graph_id']}, c['input_sha256']
    if name == 'ai_check':
        actual = ai_graph(state)
        selection = independent.uncomposed_selection(actual['graph']) if actual['graph']['state'] in independent.UNCOMPOSED_STATES else independent.select(actual['graph'], direct_source=True)
        c, body, check, report = independent.packet(actual['scope'], actual['graph'], actual['assessment'], selection,
            actual['configuration'], generation_id=policy.plan()['release_id'])
        return c, body, check, report | {'selection': selection}, c['evidence_sha256']
    if name == 'ec_check':
        c, body, check, report = ec_packet(state)
        return c, body, check, report, c['evidence_sha256']
    from tools.contextual_team_rejected_group_check import packet
    _, _, c, body, check, report = packet(state, policy.OPERATIONS[name][0])
    return c, body, check, report, c['evidence_sha256']


def graph_path(state):
    return Path(state)/'cache'/(identity([policy.VERSION, policy.plan()['release_id'], '363268', 'result'])+'.json')


def save_graph(state, graph):
    _require(len(encoded(graph)) <= policy.plan()['maximum_graph_bytes'], 'complete_graph_bound')
    value = {'kind': 'contextual_scope_result', 'snapshot_id': policy.plan()['release_id'],
        'source_id': graph['source_id'], 'value': graph}
    path = graph_path(state)
    _require(not path.exists() or json.loads(path.read_bytes()) == value, 'immutable_graph_conflict')
    if not path.exists():
        atomic_json(path, value)
    existing.checkpoint(state)


def run(args):
    existing.trusted_environment()
    requested = json.loads(os.environ['CONTEXTUAL_CHECK'])
    _require(set(requested) == {'iteration3_continuation'} and requested['iteration3_continuation'] in policy.OPERATIONS
        and not any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')), 'exclusive_named_operation')
    name = requested['iteration3_continuation']
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy()); policy.install_authority(args.state)
    runner = ContinuationRunner(args.state)
    policy.history(runner.ledger.read()); policy.counts(args.state)
    c, body, check, report, input_id = prepared(args.state, name)
    no_provider_cache(body)
    metadata = policy.bind_operation(runner.ledger, name, body, c, input_id)
    record = {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'purpose': policy.operation(name), 'release_id': policy.plan()['release_id'], 'contract_sha256': identity(c),
        'body_sha256': identity(body), 'input_sha256': input_id, 'additional_allowance': 0,
        'automatic_retries': 0, 'maximum_new_metered_attempts': 1, 'maximum_new_native_counts': 1,
        'maximum_new_microusd': policy.plan()['input_token_ceiling']*2+body['max_tokens']*10,
        'complete_remaining_inventory': policy.finite_envelope(runner.ledger.read(), policy.counts(args.state)),
        'public_activation': False, 'recurring_paid_usage': False}
    if args.action == 'prepare':
        atomic_json(args.reservation, record)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=anthropic\n')
        return
    _require(json.loads(args.reservation.read_bytes()) == record, 'prepared_request_changed')
    value = None; graph = None
    try:
        purpose = policy.operation(name)
        value = Runner.request(runner, purpose, [policy.VERSION, purpose, identity(c), input_id], body, check,
            ceiling=policy.plan()['input_token_ceiling'], repair_metadata=metadata)
        if name in ('ai_integrity', 'ai_check'):
            graph = ai_graph(args.state)['graph']; save_graph(args.state, graph)
        elif name == 'ai_verify':
            actual = ai_graph(args.state, through='verify')
            if actual['verified']['state'] != 'coherent':
                graph = actual['graph']; save_graph(args.state, graph)
            elif not integrity.inputs(actual['data'], actual['graph'], [p['person_id'] for p in actual['configuration']['people']])['candidates']:
                graph = ai_graph(args.state)['graph']; save_graph(args.state, graph)
    finally:
        atomic_json(args.result, record | {'report': report, 'value': value, 'graph': graph,
            'evidence': json.loads(body['messages'][0]['content']), 'requests': runner.used,
            'stage_timings': runner.timings,
            'durable_requests': [r for r in runner.ledger.read()['requests'] if r.get('purpose') == policy.operation(name)]})
        existing.checkpoint(args.state)
