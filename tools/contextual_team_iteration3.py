"""Finite restricted corrections, with immutable historical cache reuse.

The independent evaluator is a different operation. A failed or uncertain
historical request is never invoked by this runner, including during recovery.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import time

from tools import contextual_team_iteration2 as old_workflow
from tools import contextual_team_iteration2_policy as old_policy
from tools import contextual_team_iteration2_contract as old_wire
from tools import contextual_team_iteration3_policy as policy
from tools import contextual_team_iteration3_references as references
from tools import contextual_team_iteration3_integrity as integrity
from tools import contextual_team_latency_contract as interpretation_wire
from tools import contextual_team_requirements as requirements
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs, validate_cache_identity
from tools.contextual_team_luna_repair import RepairRunner
from tools.contextual_team_cost import no_provider_cache
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred

VERSION = 'contextual-iteration3-staged-workflow-v1'
STAGES = ('assess', 'verify', 'integrity')


def configuration():
    p = policy.plan()
    source = json.loads((policy.ROOT/'config/contextual_team/iteration3-source-inputs-v1.json').read_bytes())
    base = old_workflow.configuration()
    old = {s['id']: s for s in base['scopes']}
    if (source['registry_generation'] != base['registry_generation'] or source['roster_id'] != base['roster_id']
            or [s['id'] for s in source['scopes']] != p['build_scope_ids']
            or any(s['id'] not in old or scope_inputs(s) != scope_inputs(old[s['id']])
                or s['source_id'] != identity(scope_inputs(s)) for s in source['scopes'])):
        raise ConfigurationFailure('iteration3_exact_retained_science_and_directory_required')
    base.pop('iteration2')
    base.update(scopes=source['scopes'], snapshot_id=p['release_id'], iteration3=p)
    return base


def result_path(state, scope_id):
    return Path(state)/'cache'/(identity([VERSION, policy.plan()['release_id'], scope_id, 'result'])+'.json')


def _cached(state, scope, stage, contract, body, input_id, validator):
    from tools.contextual_team_iteration2_check import _cached_stage
    ledger = existing.ExperimentLedger(Path(state)/'ledger.json').read()
    return _cached_stage(state, ledger, scope, stage, contract, body, input_id, validator)


class _VectorsOnly(Runner):
    def request(self, *args, **kwargs):
        raise RecoveryRequired('iteration3_retained_vector_missing_no_purchase')


def retained_inputs(state, scope_id):
    """Reconstruct the exact old interpretation and deterministic retrieval."""
    config = old_workflow.configuration()
    scope = next(s for s in config['scopes'] if s['id'] == scope_id)
    source = scope_inputs(scope)
    ledger = existing.ExperimentLedger(Path(state)/'ledger.json').read()
    old_policy.history(ledger)
    ic, ib = old_workflow.interpretation_body(source, scope_id, ledger)
    interpretation = _cached(state, scope, 'interpret', ic, ib, identity(source),
        lambda v: interpretation_wire.validate_resolved('decomposition', v, source, repaired=True))
    if interpretation['state'] != 'coherent':
        raise RecoveryRequired('iteration3_retained_coherent_interpretation_required')
    reader = _VectorsOnly(state, config)
    documents = config['documents']; vectors = reader.vectors(documents, 'document')
    queries = []
    for role in requirements.active_roles(interpretation):
        text = '\n'.join([interpretation['objective'], role['label'], role['quote']])
        queries.append({'input_id': identity({'space': config['space'], 'input_type': 'query', 'text': text}), 'text': text})
    qvectors = reader.vectors(queries, 'query', scope); rankings = []
    for query in qvectors:
        q = query['embedding']; norm = math.sqrt(sum(v*v for v in q)); ranked = []
        for doc, vector in zip(documents, vectors):
            v = vector['embedding']; score = sum(a*b for a, b in zip(q, v))/(norm*math.sqrt(sum(x*x for x in v)))
            ranked.append((score, doc['person_id']))
        rankings.append([pid for _, pid in sorted(ranked, key=lambda r: (-r[0], r[1]))[:12]])
    shortlist = []
    for position in range(12):
        for ranking in rankings:
            if position < len(ranking) and ranking[position] not in shortlist and len(shortlist) < 12:
                shortlist.append(ranking[position])
    people = {p['person_id']: p for p in config['people']}
    data = source | {'interpretation': interpretation, 'people': [people[p] for p in shortlist]}
    retrieval = {'eligible': len(documents), 'shortlist': shortlist, 'per_contribution': rankings,
        'unassessed': len(documents)-len(shortlist), 'maximum_shortlist': 12}
    # Even the rejected AI assessment proves its exact original input/body. It
    # does not supply an accepted value and is never called as a fallback.
    ac, ab = old_wire.assessment_body(data)
    events = [e for e in ledger['events'] if e.get('authority') == old_policy.VERSION
        and e.get('purpose') == old_policy.operation(scope_id, 'assess')]
    if events != [old_policy.packet_event(old_policy.operation(scope_id, 'assess'), ab, ac, identity(data))]:
        raise RecoveryRequired('iteration3_original_complete_retrieval_or_assessment_input_changed')
    return config, scope, data, retrieval, {'decomposition': identity(ic)}, reader.used


class Iteration3Runner(RepairRunner):
    def __init__(self, *args, counter_post=None, read_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if self.configuration.get('iteration3') != policy.plan():
            raise ConfigurationFailure('iteration3_runner_configuration')
        self.counter = Counter(self.state, **({'post': counter_post} if counter_post else {}))
        self.timings = []; self.effective_contracts = {}; self.read_only = read_only

    def has_unknown_request(self):
        try:
            policy.history(self.ledger.read()); policy.check_counts(self.state)
            return False
        except (ValueError, Deferred, ConfigurationFailure):
            return True

    def request_provider(self, purpose, body):
        _, stage = policy._stage(purpose)
        provider, model, _ = policy.STAGES[stage]
        if body.get('model') != model:
            raise ConfigurationFailure('iteration3_fixed_model')
        return provider

    def request(self, purpose, logical, body, check, **kwargs):
        policy.history(self.ledger.read()); policy.check_counts(self.state)
        _, stage = policy._stage(purpose)
        provider = self.request_provider(purpose, body)
        if provider == 'openai':
            if (body.get('reasoning') != {'effort': 'low'} or body.get('store') is not False
                    or body.get('text', {}).get('verbosity') != 'low'
                    or body.get('text', {}).get('format', {}).get('strict') is not True):
                raise ConfigurationFailure('iteration3_exact_luna_settings')
        else:
            no_provider_cache(body)
            if (body.get('thinking') != {'type': 'disabled'} or any(k in body for k in ('temperature', 'top_p', 'top_k'))
                    or 'effort' in body.get('output_config', {})):
                raise ConfigurationFailure('iteration3_exact_sonnet_settings')
        if self.read_only:
            key = identity([existing.AUTHORIZATION_ID, 'contextual-v1', logical])
            rows = [r for r in self.ledger.read()['requests'] if r.get('purpose') == purpose]
            if len(rows) != 1 or rows[0]['key'] != key or rows[0]['status'] != 'valid':
                raise RecoveryRequired('iteration3_exact_successful_cache_required')
            saved = json.loads((self.state/'cache'/(key+'.json')).read_bytes())
            validate_cache_identity(saved, rows[0], body, provider)
            value = check(saved['value'], cached=True)
            self.used.append({'key': key, 'request_id': rows[0]['id'], 'cache_hit': True})
            return value
        kwargs['ceiling'] = policy.plan()['input_token_ceilings'][stage]
        return Runner.request(self, purpose, logical, body, check, **kwargs)

    def reservation_cost(self, purpose, body, metadata):
        policy.history(self.ledger.read()); policy.check_counts(self.state)
        if any(r.get('purpose') == purpose for r in self.ledger.read()['requests']):
            raise RecoveryRequired('iteration3_operation_claimed_no_count_or_replay')
        policy.source_currentness(policy._stage(purpose)[0])
        if self.request_provider(purpose, body) == 'openai':
            bound = len(encoded(body))+1024
            return bound, (bound+4)//5+(body['max_output_tokens']*6+4)//5, {}
        started = time.monotonic(); key = identity(count_projection(body))
        native = self.counter.count({'id': purpose, 'body': body})
        rows = [r for r in policy.check_counts(self.state) if r['key'] == key]
        if len(rows) != 1 or rows[0]['status'] != 'complete' or rows[0]['input_tokens'] != native:
            raise ConfigurationFailure('iteration3_native_count_checkpoint_identity')
        bound = math.ceil(native*1.2)+1024
        self.timings.append({'stage': 'native_count', 'operation': purpose, 'seconds': time.monotonic()-started})
        return bound, bound*2+body['max_tokens']*10, {
            'native_count_key': key, 'count_body_sha256': key, 'native_input_tokens': native}

    def scientific(self, stage, data, scope, assessment=None, graph=None):
        started = time.monotonic()
        if stage == 'assess':
            c, body = references.assessment_body(data); input_id = identity(data)
            check = lambda v, cached: references.assessment_validate_cached(v, data) if cached else references.assessment_parse(v, data)
        elif stage == 'verify':
            c, body = references.verifier_body(data, assessment); input_id = identity(old_wire.verification_inputs(data, assessment))
            check = lambda v, cached: references.verifier_validate_cached(v, data, assessment) if cached else references.verifier_parse(v, data, assessment)
        elif stage == 'integrity':
            eligible = [p['person_id'] for p in self.configuration['people']]
            c, body = integrity.body(data, graph, eligible); input_id = c['input_sha256']
            check = lambda v, cached: integrity.validate_cached(v, data, graph, eligible) if cached else integrity.parse(v, data, graph, eligible)
        else:
            raise ConfigurationFailure('iteration3_unapproved_scientific_stage')
        purpose = policy.operation(scope['id'], stage)
        if self.read_only:
            expected = policy.packet_event(purpose, body, c, input_id)
            if [e for e in self.ledger.read()['events'] if e.get('authority') == policy.VERSION and e.get('purpose') == purpose] != [expected]:
                raise RecoveryRequired('iteration3_exact_cached_operation_lock_required')
            metadata = {}
        else:
            metadata = policy.bind_operation(self.ledger, purpose, body, c, input_id)
        value = self.request(purpose, [policy.VERSION, purpose, identity(c), input_id], body, check, repair_metadata=metadata)
        self.effective_contracts[{'assess': 'adjudication', 'verify': 'verification'}.get(stage, stage)] = identity(c)
        self.timings.append({'stage': stage, 'cache_hit': self.used[-1]['cache_hit'], 'seconds': time.monotonic()-started})
        return value

    def reconstruct(self, scope, through='integrity'):
        if through not in STAGES or scope['id'] not in policy.plan()['build_scope_ids']:
            raise ConfigurationFailure('iteration3_finite_stage_or_scope')
        policy.history(self.ledger.read()); policy.check_counts(self.state)
        old_config, old_scope, data, retrieval, contracts, reused = retained_inputs(self.state, scope['id'])
        self.used.extend(reused); self.effective_contracts = contracts
        if scope['id'] == '363268':
            assessment = self.scientific('assess', data, scope)
        else:
            c, body = old_wire.assessment_body(data)
            assessment = _cached(self.state, old_scope, 'assess', c, body, identity(data),
                lambda v: old_wire.assessment_validate_cached(v, data))
            self.effective_contracts['adjudication'] = identity(c)
        result = {'configuration': self.configuration, 'scope': scope, 'data': data, 'assessment': assessment,
            'verified': None, 'graph': None}
        if through == 'assess': return result
        if scope['id'] == '363268':
            verified = self.scientific('verify', data, scope, assessment=assessment)
        else:
            c, body = old_wire.verifier_body(data, assessment)
            verified = _cached(self.state, old_scope, 'verify', c, body, identity(old_wire.verification_inputs(data, assessment)),
                lambda v: old_wire.verifier_validate_cached(v, data, assessment))
            self.effective_contracts['verification'] = identity(c)
        result['verified'] = verified
        # Requests are provenance, not mutable cache-hit observations. Otherwise
        # resuming a later durable stage would re-key the integrity packet.
        stage_purposes = [old_policy.operation(scope['id'], 'interpret')]
        stage_purposes += [(policy.operation if scope['id'] == '363268' else old_policy.operation)(scope['id'], s)
            for s in ('assess', 'verify')]
        lineage = {r['key']: {'key': r['key'], 'request_id': r['id']}
            for r in self.ledger.read()['requests'] if r.get('purpose') in stage_purposes}
        lineage.update({r['key']: {'key': r['key'], 'request_id': r['request_id']} for r in reused})
        graph = old_wire.adapter(data, assessment, verified, self.configuration, scope, retrieval,
            [lineage[k] for k in sorted(lineage)])
        graph.update(contracts=dict(self.effective_contracts), catalog_source_id=scope.get('catalog_source_id'),
            source_receipt_id=identity(scope['source_receipt']) if 'source_receipt' in scope else None,
            execution_capacity={'version': VERSION, 'authority': policy.VERSION, 'automatic_retries': 0,
                'new_document_purchases': False, 'historical_science_retained': True})
        graph['graph_id'] = identity({k: v for k, v in graph.items() if k not in ('requests', 'graph_id')})
        result['graph'] = graph
        if through == 'verify' or verified['state'] != 'coherent': return result
        eligible = [p['person_id'] for p in self.configuration['people']]
        value = (self.scientific('integrity', data, scope, graph=graph)
            if integrity.inputs(data, graph, eligible)['candidates'] else integrity.empty_result(data, graph, eligible))
        result['graph'] = integrity.adapter(data, graph, value, eligible)
        return result

    def run_scope(self, scope, extension_person=None):
        if extension_person: raise ConfigurationFailure('iteration3_no_manual_paid_extensions')
        return self.run_stage(scope, 'integrity')

    def run_stage(self, scope, stage):
        result = self.reconstruct(scope, stage)
        graph = result['graph']
        # Verification determines whether integrity needs generation. Empty
        # candidate sets still cross the durable stage boundary, without a key.
        self.integrity_generation_required = bool(stage == 'verify' and graph
            and result['verified']['state'] == 'coherent' and integrity.inputs(result['data'], graph,
                [p['person_id'] for p in self.configuration['people']])['candidates'])
        if graph and (stage == 'integrity' or result['verified']['state'] != 'coherent'):
            if len(encoded(graph)) > policy.plan()['maximum_graph_bytes']:
                raise Deferred('iteration3_complete_graph_bound_no_truncation')
            saved = {'kind': 'contextual_scope_result', 'snapshot_id': self.configuration['snapshot_id'],
                'source_id': scope['source_id'], 'value': graph}
            path = result_path(self.state, scope['id'])
            if path.exists():
                prior = json.loads(path.read_bytes())
                without_requests = lambda r: {k: v for k, v in r.items() if k != 'requests'}
                if ({k: v for k, v in prior.items() if k != 'value'} != {k: v for k, v in saved.items() if k != 'value'}
                        or without_requests(prior['value']) != without_requests(graph)):
                    raise RecoveryRequired('iteration3_immutable_first_result_conflict')
                graph = prior['value']
            else: atomic_json(path, saved)
        else:
            graph = {'state': 'stage_complete', 'stage': stage, 'scope_id': scope['id']}
        existing.checkpoint(self.state)
        return graph


def actual_result(state, scope_id):
    """Read-only reconstruction for independent evaluation, never generation."""
    if scope_id == '344592:ab-0025':
        from tools.contextual_team_iteration2_check import actual_result as old_result
        config = old_workflow.configuration()
        scope, graph, assessment, _ = old_result(state, config, scope_id)
        _, _, data, _, _, _ = retained_inputs(state, scope_id)
        vc, vb = old_wire.verifier_body(data, assessment)
        verified = _cached(state, scope, 'verify', vc, vb, identity(old_wire.verification_inputs(data, assessment)),
            lambda v: old_wire.verifier_validate_cached(v, data, assessment))
        return {'configuration': config, 'scope': scope, 'graph': graph, 'data': data, 'assessment': assessment, 'verified': verified}
    config = configuration(); scope = next(s for s in config['scopes'] if s['id'] == scope_id)
    runner = Iteration3Runner(state, config, read_only=True)
    result = runner.reconstruct(scope)
    path = result_path(state, scope_id)
    if not path.exists(): raise RecoveryRequired('iteration3_complete_durable_result_required')
    saved = json.loads(path.read_bytes()); expected = {'kind': 'contextual_scope_result',
        'snapshot_id': config['snapshot_id'], 'source_id': scope['source_id'], 'value': result['graph']}
    def stable(v):
        v = deepcopy(v); v['value'].pop('requests', None); return v
    if stable(saved) != stable(expected): raise RecoveryRequired('iteration3_complete_result_identity')
    result['graph'] = saved['value']
    return result
