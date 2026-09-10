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

    def reserve_experiment(self, provider, model, stage, key, amount, attempt,
                           *, approved_stage=2, trusted_route=False, input_tokens=0, output_tokens=0,
                           execution_metadata=None, purpose_limit=None):
        import uuid
        if not trusted_route:
            raise ConfigurationFailure("task_specific_trusted_route_unavailable")
        if stage not in (2, 3) or stage > approved_stage or ROUTES.get(provider) != model:
            raise ConfigurationFailure("outside_experiment_authority")
        if type(amount) is not int or amount <= 0 or attempt not in (1, 2):
            raise ValueError("invalid_conservative_reservation")
        if type(input_tokens) is not int or type(output_tokens) is not int or input_tokens <= 0 or output_tokens < 0 or provider=='anthropic' and output_tokens==0:
            raise ValueError('invalid_token_reservation')
        with self.locked():
            state = self.read()
            # Reservation is the irreversible dispatch claim. A caller cannot
            # prove non-dispatch from a missing cache, receipt or terminal flag.
            # Check under the same lock as insertion, including legacy rows.
            if any(r["key"] == key for r in state["requests"]):
                raise Deferred("logical_request_already_claimed_requires_recovery")
            if attempt != 1:
                raise Deferred("automatic_paid_retry_not_authorized")
            metadata = execution_metadata or {}
            if set(metadata) - {"packet_sha256", "body_sha256", "purpose", "code_sha", "row_inputs"}:
                raise ValueError("invalid_execution_metadata")
            if provider == "voyage" and execution_metadata is not None:
                purchased = {item for r in state["requests"] for item in r.get("row_inputs", [])}
                if len(purchased | set(metadata["row_inputs"])) > 3840:
                    raise Deferred("unique_embedding_inventory_exhausted")
            if purpose_limit is not None:
                if sum(r.get("purpose") == metadata["purpose"] for r in state["requests"]) >= purpose_limit:
                    raise Deferred("finite_purpose_inventory_exhausted")
            if provider in state["blocked_providers"]:
                raise ConfigurationFailure(state["blocked_providers"][provider])
            if state.get("reservation_overrun"):
                raise Deferred("recorded_reservation_overrun_requires_review")
            spent = sum(r["charged_microusd"] for r in state["requests"])
            judge = [r for r in state['requests'] if r['provider']=='anthropic' and r['stage']==stage]
            if provider=='voyage':
                embedding=[r for r in state['requests'] if r['provider']=='voyage']
                if stage!=2 or output_tokens or len(embedding)>=80 or sum(r.get('reserved_input_tokens',0) for r in embedding)+input_tokens>10_000_000:
                    raise Deferred('finite_embedding_envelope_exhausted')
                if sum(r['reserved_microusd'] for r in embedding)+amount>200_000:
                    raise Deferred('finite_preparation_dollar_envelope_exhausted')
                if amount < (input_tokens+49)//50:raise ValueError('underreserved_embedding_request')
            if provider=='anthropic':
                d1 = metadata.get('purpose', '').startswith('d1-')
                if d1 and stage != 2:
                    raise ConfigurationFailure('d1_is_development_only')
                # A finite amended question inventory, never a fresh dollar
                # allowance. Historical charges/uncertainty remain in spent.
                # Preserve the original B1 inventory and its consumed bounds.
                judge = [r for r in judge if r.get('purpose','').startswith('d1-') == d1]
                count_cap, input_cap, output_cap = ((200, 1_360_000, 102_400) if d1 else
                    ((350, 1_433_600, 179_200) if stage==2 else (260, 1_064_960, 133_120)))
                if input_tokens > 12_000 or output_tokens > 512 or len(judge)>=count_cap or sum(r.get('reserved_input_tokens',0) for r in judge)+input_tokens>input_cap or sum(r.get('reserved_output_tokens',0) for r in judge)+output_tokens>output_cap:
                    raise Deferred('finite_judge_phase_envelope_exhausted')
                if amount < (input_tokens*5+1)//2 + output_tokens*10:
                    raise ValueError('underreserved_judge_request')
                dollar_cap = 4_424_000 if d1 else (5_376_000 if stage==2 else 3_993_600)
                if sum(r['reserved_microusd'] for r in judge)+amount>dollar_cap:
                    raise Deferred('finite_judge_dollar_envelope_exhausted')
            if spent + amount > min(self.limit, STAGE_CEILINGS[stage]) or len(state["requests"]) >= self.max_requests:
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
