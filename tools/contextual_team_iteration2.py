"""Restricted normal workflow: Luna interpretation/assessment, Sonnet verifier.

Only the twelve frozen development scopes are executable. The independent
quality checker is separate and is never used as the production verifier.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import time

from tools import contextual_team_iteration2_policy as policy
from tools import contextual_team_latency_contract as interpretation_wire
from tools import contextual_team_requirements as requirements
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_luna_repair import RepairRunner
from tools.contextual_team_policy import inputs
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.contextual_team_cost import generated_input_bounds, no_provider_cache
from tools.offline_ai import response_value
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred


def configuration():
    p = policy.plan()
    source = json.loads((policy.ROOT/'config/contextual_team/iteration2-source-inputs-v1.json').read_bytes())
    base = deepcopy(inputs())
    if (source['registry_generation'] != base['registry_generation'] or source['roster_id'] != base['roster_id']
            or [s['id'] for s in source['scopes']] != p['scope_ids']
            or any(s['source_id'] != identity(scope_inputs(s)) for s in source['scopes'])):
        raise ConfigurationFailure('iteration2_complete_source_or_audited_directory_identity')
    if len(base['documents']) != 155 or len(base['people']) != 155:
        raise ConfigurationFailure('iteration2_fixed_full_eligible_directory')
    base.update(scopes=source['scopes'], snapshot_id=p['release_id'], iteration2=p)
    return base


def result_path(state, scope_id):
    return Path(state)/'cache'/(identity(['iteration2-scope-result', policy.plan()['release_id'], scope_id])+'.json')


INTERPRETATION_FORMAT = 'contextual-i2-interpretation-format-v2'
NONCOHERENT_FORMAT = '''
INTERPRETATION STATE FORMAT: When state is not coherent, approach MUST be the
empty string and roles MUST be empty. Guidance about selecting a future scope
belongs in limitations, never in approach. Do not select a scope merely to fill
this field. Preserve source-warranted abstention and explain it in objective and
limitations. When state is coherent, approach describes the selected approach.
'''


def interpretation_body(data, scope_id, ledger_state):
    """Honor every bound operation, including an unsent prepared operation.

    Only previously unbound I2 interpretations receive the format clarification.
    The scientific validator and all historical body/cache identities stay exact.
    """
    contract, body = interpretation_wire.body('decomposition', data, 'L', 8000, repaired=True)
    original_identity = identity(contract); legacy_version = contract['version']
    purpose = policy.operation(scope_id, 'interpret')
    bound = [e for e in ledger_state['events'] if e.get('authority') == policy.VERSION and e.get('purpose') == purpose]
    if len(bound) > 1:
        raise RecoveryRequired('iteration2_conflicting_interpretation_transport')
    version = bound[0]['contract_version'] if bound else INTERPRETATION_FORMAT
    if version == legacy_version:
        return contract, body
    if version != INTERPRETATION_FORMAT:
        raise RecoveryRequired('iteration2_unknown_interpretation_transport')
    contract['version'] = INTERPRETATION_FORMAT
    contract['validator_contract_sha256'] = original_identity
    contract['prompt'] += NONCOHERENT_FORMAT
    contract['settings'].update(schema_version=INTERPRETATION_FORMAT,prompt_version=INTERPRETATION_FORMAT)
    contract['schema']['properties']['approach']['description'] = 'Empty string unless state is coherent; future scope-selection guidance belongs in limitations.'
    body['instructions'] = contract['prompt']
    body['text']['format']['name'] = INTERPRETATION_FORMAT
    return contract, body


class Iteration2Runner(RepairRunner):
    def __init__(self, *args, counter_post=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.configuration.get('iteration2') != policy.plan():
            raise ConfigurationFailure('iteration2_runner_configuration')
        self.counter = Counter(self.state, **({'post': counter_post} if counter_post else {}))
        self.scope_id = None; self.timings = []; self.effective_contracts = {}

    def has_unknown_request(self):
        try:
            policy.history(self.ledger.read())
            return False
        except (ValueError, Deferred, ConfigurationFailure):
            return True

    def request_provider(self, purpose, body):
        _, stage = policy._stage(purpose)
        provider, model, _ = policy.STAGES[stage]
        if body.get('model') != model:
            raise ConfigurationFailure('iteration2_fixed_stage_model')
        return provider

    def request_usage(self, provider, payload, model):
        if provider == 'voyage':
            return Runner.request_usage(self, provider, payload, model)
        return super().request_usage(provider, payload, model)

    def read_provider_response(self, response, provider, body, receipt):
        if provider == 'voyage':
            return Runner.read_provider_response(self, response, provider, body, receipt)
        return super().read_provider_response(response, provider, body, receipt)

    def request(self, purpose, logical, body, check, **kwargs):
        from tools.contextual_team_checkpoint_disposition import assert_operation_open
        if purpose == 'cb-documents':
            raise RecoveryRequired('iteration2_missing_audited_document_vectors_no_repurchase')
        if purpose == 'cb-query':
            purpose = policy.operation(self.scope_id, 'query')
            c = {'version': 'iteration2-voyage-query-v1', 'space': self.configuration['space'],
                'input_type': 'query', 'complete_input_ids': [v.split(':', 2)[2] for v in kwargs.get('row_inputs', [])]}
            metadata = policy.bind_operation(self.ledger, purpose, body, c, identity(body['input']))
            kwargs['repair_metadata'] = metadata
            logical = [policy.VERSION, purpose, identity(c), identity(body['input'])]
        _, stage = policy._stage(purpose)
        assert_operation_open(self.ledger.read(), purpose)
        provider = self.request_provider(purpose, body)
        if provider == 'openai':
            if (body.get('reasoning') != {'effort': 'low'} or body.get('store') is not False
                    or body.get('text', {}).get('verbosity') != 'low'
                    or body.get('text', {}).get('format', {}).get('strict') is not True):
                raise ConfigurationFailure('iteration2_exact_luna_settings')
        elif provider == 'anthropic':
            no_provider_cache(body)
            if (body.get('thinking') != {'type': 'disabled'}
                    or any(k in body for k in ('temperature', 'top_p', 'top_k'))
                    or 'effort' in body.get('output_config', {})):
                raise ConfigurationFailure('iteration2_exact_sonnet_verifier_settings')
        kwargs['ceiling'] = policy.plan()['input_token_ceilings'][stage]
        return Runner.request(self, purpose, logical, body, check, **kwargs)

    def reservation_cost(self, purpose, body, metadata):
        state = self.ledger.read(); policy.history(state); policy.check_counts(self.state)
        if any(r.get('purpose') == purpose for r in state['requests']):
            raise RecoveryRequired('iteration2_operation_claimed_no_new_count_or_paid_dispatch')
        provider = self.request_provider(purpose, body)
        if provider != 'anthropic':
            bound = len(encoded(body)) + 1024
            amount = (bound * 3 + 24) // 25 if provider == 'voyage' else (bound + 4) // 5 + (body['max_output_tokens'] * 6 + 4) // 5
            return bound, amount, {}
        started = time.monotonic()
        projection = count_projection(body); key = identity(projection)
        native = self.counter.count({'id': purpose, 'body': body})
        # Recheck the persisted count; native estimates never stand in for a
        # completed scientific response or grant permission to change its body.
        rows = [r for r in policy.check_counts(self.state) if r['key'] == key]
        if len(rows) != 1 or rows[0]['status'] != 'complete' or rows[0]['input_tokens'] != native:
            raise ConfigurationFailure('iteration2_native_count_checkpoint_identity')
        bound = math.ceil(native * 1.2) + 1024
        self.timings.append({'stage': 'native_count', 'operation': purpose, 'seconds': time.monotonic() - started})
        return bound, bound * 2 + body['max_tokens'] * 10, {
            'native_count_key': key, 'count_body_sha256': key, 'native_input_tokens': native}

    def scientific(self, stage, data, scope, extension=False, assessment=None):
        if extension:
            raise ConfigurationFailure('iteration2_manual_extension_not_authorized')
        from tools import contextual_team_iteration2_contract as wire
        self.scope_id = scope['id']; start = time.monotonic()
        if stage == 'decomposition':
            name = 'interpret'
            c, body = interpretation_body(data, scope['id'], self.ledger.read())
            check = lambda v, cached: (interpretation_wire.validate_resolved(stage, v, data, repaired=True)
                if cached else interpretation_wire.resolve(stage, response_value('openai', v), data, repaired=True))
            input_id = identity(data)
        elif stage == 'adjudication':
            name = 'assess'; c, body = wire.assessment_body(data)
            check = lambda v, cached: wire.assessment_validate_cached(v, data) if cached else wire.assessment_parse(v, data)
            input_id = identity(data)
        elif stage == 'verification':
            name = 'verify'; c, body = wire.verifier_body(data, assessment)
            check = lambda v, cached: wire.verifier_validate_cached(v, data, assessment) if cached else wire.verifier_parse(v, data, assessment)
            input_id = identity(wire.verification_inputs(data, assessment))
        else:
            raise ConfigurationFailure('iteration2_unapproved_scientific_stage')
        purpose = policy.operation(scope['id'], name)
        metadata = policy.bind_operation(self.ledger, purpose, body, c, input_id)
        value = self.request(purpose, [policy.VERSION, purpose, identity(c), input_id], body, check,
            repair_metadata=metadata)
        self.effective_contracts[stage] = identity(c)
        self.timings.append({'stage': stage, 'cache_hit': self.used[-1]['cache_hit'], 'seconds': time.monotonic() - start})
        return value

    def vectors(self, documents, role, scope=None):
        started = time.monotonic(); before = len(self.ledger.read()['requests'])
        result = Runner.vectors(self, documents, role, scope)
        self.timings.append({'stage': 'query_embedding' if role == 'query' else 'document_vector_reuse',
            'rows': len(result), 'new_attempts': len(self.ledger.read()['requests']) - before,
            'seconds': time.monotonic() - started})
        return result

    def run_scope(self, scope, extension_person=None):
        from tools import contextual_team_iteration2_contract as wire
        from tools.contextual_team_checkpoint_disposition import assert_operation_open
        if extension_person:
            raise ConfigurationFailure('iteration2_manual_extension_not_authorized')
        self.scope_id = scope['id']; policy.operation(scope['id'], 'interpret')
        assert_operation_open(self.ledger.read(), policy.operation(scope['id'], 'interpret'))
        policy.remaining(self.ledger.read(), self.state)
        started = time.monotonic(); source = scope_inputs(scope)
        if scope['state'] != 'unassessed':
            return {'state': scope['state'], 'scope_id': scope['id']}
        interpretation = self.scientific('decomposition', source, scope)
        if interpretation['state'] != 'coherent':
            result = {'state': interpretation['state'], 'scope_id': scope['id'], 'interpretation': interpretation}
        else:
            generated_input_bounds(interpretation)
            documents = self.configuration['documents']; vectors = []
            for i in range(0, len(documents), 80):
                vectors.extend(self.vectors(documents[i:i+80], 'document'))
            queries = []
            for role in requirements.active_roles(interpretation):
                text = '\n'.join([interpretation['objective'], role['label'], role['quote']])
                queries.append({'input_id': identity({'space': self.configuration['space'], 'input_type': 'query', 'text': text}), 'text': text})
            qvectors = self.vectors(queries, 'query', scope); rankings = []
            retrieval_started = time.monotonic()
            for query in qvectors:
                q = query['embedding']; qnorm = math.sqrt(sum(v*v for v in q)); ranked = []
                for doc, vector in zip(documents, vectors):
                    v = vector['embedding']; score = sum(a*b for a, b in zip(q, v)) / (qnorm * math.sqrt(sum(x*x for x in v)))
                    ranked.append((score, doc['person_id']))
                rankings.append([pid for _, pid in sorted(ranked, key=lambda r: (-r[0], r[1]))[:12]])
            shortlist = []
            for position in range(12):
                for ranking in rankings:
                    if position < len(ranking) and ranking[position] not in shortlist and len(shortlist) < 12:
                        shortlist.append(ranking[position])
            people = {p['person_id']: p for p in self.configuration['people']}
            data = source | {'interpretation': interpretation, 'people': [people[pid] for pid in shortlist]}
            self.timings.append({'stage': 'full_directory_retrieval', 'eligible': len(documents),
                'shortlist': len(shortlist), 'seconds': time.monotonic() - retrieval_started})
            assessment = self.scientific('adjudication', data, scope)
            verified = self.scientific('verification', data, scope, assessment=assessment)
            retrieval = {'eligible': len(documents), 'shortlist': shortlist, 'per_contribution': rankings,
                'unassessed': len(documents) - len(shortlist), 'maximum_shortlist': 12}
            result = wire.adapter(data, assessment, verified, self.configuration, scope, retrieval, self.used)
            result['contracts'] = dict(self.effective_contracts)
            result['catalog_source_id'] = scope.get('catalog_source_id')
            result['source_receipt_id'] = identity(scope['source_receipt']) if 'source_receipt' in scope else None
            result['execution_capacity'] = {'version': policy.VERSION,
                'output_tokens': {k: v[2] for k, v in policy.STAGES.items() if k != 'check'},
                'models': {k: v[1] for k, v in policy.STAGES.items() if k != 'check'},
                'automatic_retries': 0, 'new_document_purchases': False}
            result['graph_id'] = identity({k: v for k, v in result.items() if k not in ('requests', 'graph_id')})
        if len(encoded(result)) > policy.plan()['maximum_graph_bytes']:
            raise Deferred('iteration2_complete_graph_bound_no_truncation')
        path = result_path(self.state, scope['id'])
        saved = {'kind': 'contextual_scope_result', 'snapshot_id': self.configuration['snapshot_id'],
            'source_id': scope['source_id'], 'value': result}
        if path.exists():
            previous = json.loads(path.read_bytes())
            # Cache bookkeeping is observational; every scientific byte and
            # accepted graph identity must match the durable first result.
            if (set(previous) != set(saved) or any(previous[k] != saved[k] for k in ('kind', 'snapshot_id', 'source_id'))
                    or {k: v for k, v in previous['value'].items() if k != 'requests'} != {k: v for k, v in result.items() if k != 'requests'}):
                raise RecoveryRequired('iteration2_persisted_scope_result_conflict')
            saved = previous; result = previous['value']
        else:
            atomic_json(path, saved)
        self.timings.append({'stage': 'complete_runner', 'seconds': time.monotonic() - started})
        existing.checkpoint(self.state)
        return result
