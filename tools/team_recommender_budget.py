"""One experiment ledger, using the existing atomic ledger/lock machinery.

This module has no provider dispatch. A trusted route is a separate prerequisite.
"""
from decimal import Decimal
from contextlib import contextmanager
import threading
from tools.offline_spend import Ledger, Deferred, ConfigurationFailure, atomic_json

AUTHORIZATION_ID = "on-demand-team-offline-v2-20260909"
STAGE_CEILINGS = {1: 0, 2: 6_000_000, 3: 10_000_000, 4: 10_000_000}
ROUTES = {"anthropic": "claude-sonnet-5", "voyage": "voyage-4-lite"}
MAX_REQUESTS = 690


class ExperimentLedger(Ledger):
    # Windows can briefly deny O_EXCL while another thread releases the file.
    # Serialize local threads first; the existing file lock still owns processes.
    _thread_guard = threading.RLock()

    @contextmanager
    def locked(self):
        with self._thread_guard:
            with super().locked():
                yield

    def __init__(self, path, *, initialize=False):
        # Resuming a missing durable checkpoint must never create fresh credit.
        from pathlib import Path
        if not Path(path).exists() and not initialize:
            raise Deferred("experiment_checkpoint_missing")
        super().__init__(path, AUTHORIZATION_ID, 10, MAX_REQUESTS)

    def read(self):
        import json
        state = json.loads(self.path.read_bytes())
        if state.get('version') != 1 or state.get('logical_id') != AUTHORIZATION_ID:
            raise ValueError('logical_budget_identity_mismatch')
        if (state.get('limit_microusd'), state.get('max_requests')) == (10_000_000, MAX_REQUESTS):
            # Do not accept a recorded amendment with only some caps updated.
            from tools.contextual_team_completion_policy import VERSION
            if any(e.get('authority') == VERSION for e in state.get('events', [])):
                raise ValueError('completion_partial_budget_amendment')
            self.limit, self.max_requests = 10_000_000, MAX_REQUESTS
        else:
            from tools.contextual_team_completion_policy import amended_limits
            self.limit, self.max_requests = amended_limits(state)
        from tools.contextual_team_checkpoint_disposition import validate
        validate(state)
        return state

    def reserve_experiment(self, provider, model, stage, key, amount, attempt,
                           *, approved_stage=2, trusted_route=False, input_tokens=0, output_tokens=0,
                           execution_metadata=None, purpose_limit=None):
        import uuid
        if not trusted_route:
            raise ConfigurationFailure("task_specific_trusted_route_unavailable")
        metadata = execution_metadata or {}
        is_contextual = metadata.get('purpose', '').startswith('cb-')
        is_latency = metadata.get('purpose', '').startswith('cb-lr-')
        is_luna_repair = metadata.get('purpose', '').startswith('cb-lc-')
        is_completion = metadata.get('purpose', '').startswith('cb-fc-')
        d3_embedding = provider == 'voyage' and metadata.get('purpose') in {'d3-embedding','d3-query-format'}
        s3_embedding = provider == 'voyage' and metadata.get('purpose') == 's3-embedding'
        allowed_model = (model == ('voyage-4-large' if provider == 'voyage' else 'claude-sonnet-5')) if is_contextual else model == 'voyage-4-large' if s3_embedding else model in {'voyage-4-large','voyage-context-4'} if d3_embedding else ROUTES.get(provider) == model
        if is_latency:
            allowed_model = {'anthropic':'claude-sonnet-5','openai':'gpt-5.6-luna','voyage':'voyage-4-large'}.get(provider)==model
            if metadata.get('latency_model')!=model:raise ConfigurationFailure('latency_reserved_model_identity')
        if metadata.get('purpose', '').startswith('cb-fc-i2-'):
            allowed_model = {'anthropic':'claude-sonnet-5','openai':'gpt-5.6-luna','voyage':'voyage-4-large'}.get(provider)==model
        if metadata.get('purpose', '').startswith('cb-fc-i3-'):
            allowed_model = {'anthropic':'claude-sonnet-5','openai':'gpt-5.6-luna'}.get(provider)==model
        if metadata.get('purpose', '').startswith('cb-fc-cat-'):
            from tools.catalog_correction_policy import PREFIX, operation
            allowed_model = provider == 'voyage' and model == operation(metadata['purpose'][len(PREFIX):])['model']
        if is_luna_repair:
            allowed_model = {'anthropic':'claude-sonnet-5','openai':'gpt-5.6-luna'}.get(provider)==model
        if stage not in (2, 3) or stage > approved_stage or not allowed_model:
            raise ConfigurationFailure("outside_experiment_authority")
        if (stage == 3) != metadata.get('purpose','').startswith('s3-'):
            raise ConfigurationFailure('stage3_exact_purpose_required')
        if type(amount) is not int or amount <= 0 or attempt not in (1, 2):
            raise ValueError("invalid_conservative_reservation")
        if type(input_tokens) is not int or type(output_tokens) is not int or input_tokens <= 0 or output_tokens < 0 or provider=='anthropic' and output_tokens==0:
            raise ValueError('invalid_token_reservation')
        with self.locked():
            state = self.read()
            from tools.contextual_team_checkpoint_disposition import exposure, assert_operation_open
            assert_operation_open(state, metadata.get('purpose'))
            from tools.contextual_team_ec_disposition import assert_operation_open as assert_ec_open
            assert_ec_open(state, metadata.get('purpose'), key)
            held = exposure(state)
            # Reservation is the irreversible dispatch claim. A caller cannot
            # prove non-dispatch from a missing cache, receipt or terminal flag.
            # Check under the same lock as insertion, including legacy rows.
            if any(r["key"] == key for r in state["requests"]):
                raise Deferred("logical_request_already_claimed_requires_recovery")
            if attempt != 1:
                raise Deferred("automatic_paid_retry_not_authorized")
            metadata = execution_metadata or {}
            allowed_metadata={"packet_sha256", "body_sha256", "purpose", "code_sha", "row_inputs", "judge_items"}
            if is_contextual:allowed_metadata.add('execution_capacity')
            if is_latency:allowed_metadata.update({'latency_lock','latency_operation','latency_model','latency_effort','native_count_key','count_body_sha256','native_input_tokens'})
            if is_luna_repair:allowed_metadata.update({'luna_repair','luna_operation','pair_contract_sha256','repair_of'})
            if is_completion:
                allowed_metadata.update({'completion_authority','completion_transport','completion_lock_sha256',
                    'pair_contract_sha256','repair_of','native_count_key','count_body_sha256','native_input_tokens'})
            if metadata.get('purpose','').startswith('cb-cc-'):
                allowed_metadata.update({'compact_continuation','continuation_lock_sha256','pair_contract_sha256','repair_of'})
            if metadata.get('purpose','').startswith('cb-o1-'):allowed_metadata.update({'option1_release','repair_of'})
            if metadata.get('purpose','').startswith('cb-p1-'):allowed_metadata.update({'phase1_lock','response_contract_sha256','repair_of'})
            if metadata.get('purpose','').startswith('cb-p2-'):
                allowed_metadata.update({'phase2_lock','phase2_operation','native_count_key','count_body_sha256','native_input_tokens','phase2_capacity','repair_of'})
            if set(metadata) - allowed_metadata:
                raise ValueError("invalid_execution_metadata")
            if provider == "voyage" and execution_metadata is not None:
                purchased = {item for r in state["requests"] for item in r.get("row_inputs", [])}
                if purchased.intersection(metadata["row_inputs"]):
                    raise Deferred("paid_embedding_row_already_claimed_no_rebatch")
                row_input_ceiling = 3840
                if metadata.get('purpose', '').startswith('cb-fc-cat-'):
                    from tools.catalog_correction_policy import unique_input_limit
                    row_input_ceiling = unique_input_limit(state)
                if len(purchased | set(metadata["row_inputs"])) > row_input_ceiling:
                    raise Deferred("unique_embedding_inventory_exhausted")
            if metadata.get('judge_items'):
                from tools.team_recommender_items import claimed_judge_items, historical_index
                historical = historical_index()
                purchased = {item for r in state['requests'] for item in claimed_judge_items(r,historical)}
                if purchased.intersection(metadata['judge_items']):
                    raise Deferred('paid_judge_item_already_claimed_no_rebatch')
            if purpose_limit is not None:
                if sum(r.get("purpose") == metadata["purpose"] for r in state["requests"]) >= purpose_limit:
                    raise Deferred("finite_purpose_inventory_exhausted")
            if provider in state["blocked_providers"]:
                raise ConfigurationFailure(state["blocked_providers"][provider])
            if state.get("reservation_overrun"):
                raise Deferred("recorded_reservation_overrun_requires_review")
            spent = sum(r["charged_microusd"] for r in state["requests"]) + held['microusd']
            if is_contextual:
                from tools.contextual_team_policy import check_reservation
                check_reservation(state, provider, metadata, amount, input_tokens, output_tokens)
            if stage == 3:
                validation = [r for r in state['requests'] if r['stage']==3]
                if (len(validation)>=184 or len(state['requests']) + held['attempts']>=665
                        or sum(r['charged_microusd'] for r in validation)+amount>4_000_000
                        or spent+amount>7_135_333):
                    raise Deferred('stage3_or_stage4_reserve_exhausted')
                if provider=='voyage':
                    preparation=[r for r in validation if r['provider']=='voyage']
                    if (not s3_embedding or input_tokens>20_000 or len(preparation)>=20
                            or sum(r.get('reserved_input_tokens',0) for r in preparation)+input_tokens>400_000
                            or sum(r['reserved_microusd'] for r in preparation)+amount>48_000):
                        raise Deferred('stage3_query_envelope_exhausted')
                elif metadata.get('purpose') not in {'s3-primary','s3-alternative','s3-explanation','s3-swap','s3-control'}:
                    raise ConfigurationFailure('stage3_unapproved_judge_purpose')
            judge = [r for r in state['requests'] if r['provider']=='anthropic' and r['stage']==stage]
            if provider=='voyage' and not is_contextual:
                embedding=[r for r in state['requests'] if r['provider']=='voyage']
                if metadata.get('purpose') == 'd2-context':
                    contextual=[r for r in embedding if r.get('purpose')=='d2-context']
                    if len(contextual)>=5 or sum(r['reserved_microusd'] for r in contextual)+amount>20_000:
                        raise Deferred('finite_d2_context_envelope_exhausted')
                if d3_embedding:
                    d3 = [r for r in embedding if r.get('purpose') in {'d3-embedding','d3-query-format'}]
                    if len(d3)>=28 or sum(r['reserved_microusd'] for r in d3)+amount>180_000:
                        raise Deferred('finite_d3_embedding_envelope_exhausted')
                    if metadata['purpose']=='d3-query-format':
                        formats=[r for r in d3 if r.get('purpose')=='d3-query-format']
                        if len(formats)>=3 or any(r['model']!=model for r in formats):
                            raise Deferred('one_D3_leading_query_format_only')
                if output_tokens or len(embedding)>=80 or sum(r.get('reserved_input_tokens',0) for r in embedding)+input_tokens>10_000_000:
                    raise Deferred('finite_embedding_envelope_exhausted')
                if sum(r['reserved_microusd'] for r in embedding)+amount>200_000:
                    raise Deferred('finite_preparation_dollar_envelope_exhausted')
                minimum=(input_tokens*3+24)//25 if d3_embedding or s3_embedding else (input_tokens+49)//50
                if amount < minimum:raise ValueError('underreserved_embedding_request')
            if provider=='anthropic' and not is_contextual:
                post = metadata.get('purpose') == 'post-audit'
                d1 = metadata.get('purpose', '').startswith('d1-')
                d2 = metadata.get('purpose', '').startswith('d2-')
                d3 = metadata.get('purpose', '').startswith('d3-')
                if (d1 or d2 or d3) and stage != 2:
                    raise ConfigurationFailure('d1_is_development_only')
                # A finite amended question inventory, never a fresh dollar
                # allowance. Historical charges/uncertainty remain in spent.
                # Preserve the original B1 inventory and its consumed bounds.
                family = 'post-audit' if post else 'd3-' if d3 else 'd2-' if d2 else 'd1-' if d1 else None
                judge = [r for r in judge if (r.get('purpose','').startswith(family) if family else not r.get('purpose','').startswith(('d1-','d2-','d3-','post-audit')))]
                count_cap, input_cap, output_cap = ((60, 1_440_000, 30_720) if post else (120, 1_100_000, 61_440) if d2 or d3 else (200, 1_360_000, 102_400) if d1 else
                    ((350, 1_433_600, 179_200) if stage==2 else (164, 1_064_960, 83_968)))
                if input_tokens > (24_000 if post else 12_000) or output_tokens > 512 or len(judge)>=count_cap or sum(r.get('reserved_input_tokens',0) for r in judge)+input_tokens>input_cap or sum(r.get('reserved_output_tokens',0) for r in judge)+output_tokens>output_cap:
                    raise Deferred('finite_judge_phase_envelope_exhausted')
                if amount < (input_tokens*5+1)//2 + output_tokens*10:
                    raise ValueError('underreserved_judge_request')
                dollar_cap = 2_000_000 if post else 3_364_400 if d2 or d3 else 4_424_000 if d1 else (5_376_000 if stage==2 else 3_993_600)
                if sum(r['reserved_microusd'] for r in judge)+amount>dollar_cap:
                    raise Deferred('finite_judge_dollar_envelope_exhausted')
            if is_completion or held['attempts']:
                from tools.contextual_team_completion_policy import check_pool
                check_pool(state, amount, 1)
            # The pooled amendment increases only exact completion operations;
            # every older route keeps its original lifetime/stage envelope.
            effective_limit = self.limit if is_completion else min(10_000_000, 9_290_655 if is_contextual else STAGE_CEILINGS[stage])
            effective_attempts = self.max_requests if is_completion else MAX_REQUESTS
            if spent + amount > effective_limit or len(state["requests"]) + held['attempts'] >= effective_attempts:
                raise Deferred("experiment_stage_or_total_budget_exhausted")
            token = uuid.uuid4().hex
            state["requests"].append({"id": token, "provider": provider, "model": model,
                "stage": stage, "key": key, "attempt": attempt, "reserved_microusd": amount,
                "charged_microusd": amount, "status": "reserved_unknown", "usage": None,
                "reserved_input_tokens":input_tokens,"reserved_output_tokens":output_tokens,
                "dispatch_claim": "irreversible-v1", **metadata})
            atomic_json(self.path, state)
            return token

    def reserve(self, *args, **kwargs):
        raise ConfigurationFailure("use_stage_checked_experiment_reservation")

    def reconcile(self, token, *, cost_usd, usage, status):
        amount = int((Decimal(str(cost_usd)) * 1_000_000).to_integral_value(rounding="ROUND_CEILING"))
        if amount < 0 or not isinstance(usage, dict) or status not in ("valid", "failed"):
            raise ValueError("invalid_usage_receipt")
        with self.locked():
            state = self.read()
            row = next(r for r in state["requests"] if r["id"] == token)
            if row["status"] != "reserved_unknown":
                if row["charged_microusd"] == amount and row["usage"] == usage and row["status"] == status:
                    return
                raise ValueError("conflicting_reconciliation")
            if amount > row["reserved_microusd"]:
                row.update(charged_microusd=amount, usage=usage, status=status)
                state["reservation_overrun"] = {"request_id": token, "actual_microusd": amount,
                    "reserved_microusd": row["reserved_microusd"]}
                atomic_json(self.path, state)
                raise ValueError("receipt_exceeds_conservative_reservation_stop")
            row.update(charged_microusd=amount, usage=usage, status=status)
            atomic_json(self.path, state)

    def complete(self, token, **result):
        raise ConfigurationFailure("use_receipt_checked_reconciliation")
