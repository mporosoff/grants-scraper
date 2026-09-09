"""Shared durable spending and safe accounting for offline generation."""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def identity(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Deferred(RuntimeError):
    pass


class ConfigurationFailure(Deferred):
    pass


class Refusal(RuntimeError):
    pass


class Incomplete(ValueError):
    pass


def error_diagnostics(response):
    """Allowlisted error categories only; never retain a provider body/message."""
    result = {'http_status': response.status_code}
    try:
        error = response.json().get('error', {})
        kind = error.get('type') or error.get('code')
        if isinstance(kind, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', kind):
            result['error_type'] = kind
        message = str(error.get('message', '')).lower()
        result['category'] = next((category for category, phrases in (
            ('insufficient_credit', ('credit balance', 'insufficient credit', 'billing')),
            ('model_unavailable', ('model not found', 'model is not', 'model does not exist', 'invalid model')),
            ('invalid_credential', ('invalid api key', 'invalid x-api-key', 'authentication')),
            ('invalid_request', ('invalid', 'required', 'not supported')))
            if any(phrase in message for phrase in phrases)), 'unclassified_provider_error')
    except (ValueError, AttributeError, TypeError):
        result['category'] = 'unstructured_provider_error'
    return result


def config():
    return json.loads((ROOT / "config/offline_ai.json").read_bytes())


def compatible_model(requested, returned):
    return isinstance(returned, str) and (returned == requested or
        re.fullmatch(re.escape(requested) + r'-\d{4}-\d{2}-\d{2}', returned) is not None)


def normalize_usage(provider, payload):
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return None
    def count(name, source=raw, default=None):
        value = source.get(name, default)
        return value if type(value) is int and value >= 0 else None
    incoming, outgoing = count("input_tokens"), count("output_tokens")
    if incoming is None or outgoing is None:
        return None
    if provider == "openai":
        cached = count("cached_tokens", raw.get("input_tokens_details") or {}, 0)
        reasoning = count("reasoning_tokens", raw.get("output_tokens_details") or {})
        if cached is None or cached > incoming or (reasoning is not None and reasoning > outgoing):
            return None
        return dict(input_tokens=incoming, cached_input_tokens=cached, cache_write_tokens=0,
                    output_tokens=outgoing, reasoning_tokens=reasoning)
    cached, written = count("cache_read_input_tokens", default=0), count("cache_creation_input_tokens", default=0)
    if cached is None or written is None:
        return None
    # Anthropic reports uncached input separately. OpenAI includes cached input.
    return dict(input_tokens=incoming + cached + written, cached_input_tokens=cached,
                cache_write_tokens=written, output_tokens=outgoing, reasoning_tokens=None)


def cost_microusd(usage, prices):
    # One token at $1 / million tokens is one microdollar.
    uncached = usage["input_tokens"] - usage["cached_input_tokens"] - usage["cache_write_tokens"]
    total = sum(Decimal(str(prices[key])) * value for key, value in (
        ("input", uncached), ("cached", usage["cached_input_tokens"]),
        ("cache_write", usage["cache_write_tokens"]), ("output", usage["output_tokens"])))
    return int(total.to_integral_value(rounding=ROUND_CEILING))


class LinkedLedger:
    """A production run and its task allowance both reserve before dispatch."""
    def __init__(self, local, task):
        self.local, self.task = local, task

    def __getattr__(self, name):
        return getattr(self.local, name)

    def read(self):
        value = self.local.read()
        parent = self.task.read()
        # Request resumption follows the logical task across workflow runs.
        # Local counters alone would forget a known schema failure when a new
        # run restores the task but starts a fresh per-run ledger.
        value['requests'] = parent['requests']
        value['blocked_providers'] |= parent['blocked_providers']
        return value

    def reserve(self, provider, model, stage, key, amount, attempt):
        token = self.local.reserve(provider, model, stage, key, amount, attempt)
        try:
            parent = self.task.reserve(provider, model, stage, key, amount, attempt)
        except (ConfigurationFailure, Deferred):
            # This reservation provably precedes transport. Keep the row and
            # attempt, but do not charge a request we could not dispatch.
            self.local.complete(token, status='not_dispatched_task_limit', charged_microusd=0)
            raise
        # A crash before linkage leaves conservative unknown reservations, not
        # permission to spend them again. Both links precede the caller's HTTP.
        self.task.complete(parent, production_logical_id=self.local.logical_id, production_request_id=token)
        self.local.complete(token, task_request_id=parent)
        return token

    def complete(self, token, **result):
        row = next(row for row in self.local.read()['requests'] if row['id'] == token)
        self.task.complete(row['task_request_id'], **result)
        self.local.complete(token, **result)

    def block(self, provider, reason):
        self.task.block(provider, reason)
        self.local.block(provider, reason)

    def summary(self):
        value = self.local.summary()
        parent = self.task.read()
        value['task_accounting'] = {'logical_id': self.task.logical_id,
            'requests': len(parent['requests']),
            'charged_usd': sum(row['charged_microusd'] for row in parent['requests']) / 1_000_000,
            'ledger_sha256': identity(parent)}
        return value


def production_ledger(state, mode):
    """Preserve ordinary run caps; a declared qualification pilot also uses its task cap."""
    state = Path(state)
    settings = config()
    local = Ledger(state / 'ledger.json', state.name, settings['budgets_usd'][mode], settings['max_requests'])
    for provider, evidence in settings.get('generation_provider_pauses', {}).items():
        if provider not in local.read()['blocked_providers']:
            local.block(provider, evidence['reason'])
    marker = state / 'task-accounting.json'
    if not marker.exists():
        if os.environ.get('QUALIFICATION_PILOT') == 'true':
            raise ConfigurationFailure('qualification_pilot_task_checkpoint_required')
        return local
    from tools.evaluate_offline_ai import TASK
    authorization = json.loads((ROOT / 'config/sonnet_production_qualification.json').read_bytes())['authorization']
    if json.loads(marker.read_bytes()) != {'task': TASK, 'authorization_id': authorization['id']}:
        raise ConfigurationFailure('production_task_link_identity_mismatch')
    task_path = state / 'task' / 'ledger.json'
    if not task_path.exists() or json.loads(task_path.read_bytes()).get('active_allowance') != authorization:
        raise ConfigurationFailure('authorized_task_history_required')
    parent = restore_ledger(task_path, TASK, settings['budgets_usd']['evaluation'],
                            settings['max_requests'], authorization)
    return LinkedLedger(local, parent)


def response_cache(ledger, service):
    """Linked pilots retain every completed stage with authoritative task state."""
    if isinstance(ledger, LinkedLedger):
        return ledger.task.path.parent / {'teams': 'cache', 'cov4': 'cov4-production-cache'}[service]
    return ledger.path.parent / {'teams': 'team-responses', 'cov4': 'cov4-cache'}[service]


def require_production_service(service, ledger):
    """Independent service quality holds do not become account-wide denials."""
    settings = config()
    selected = settings.get('production_services', {}).get(service)
    if selected is not None:
        if not selected.get('enabled'):
            ledger.event(kind='service_stop', service=service, reason='quality_gate_pending')
            raise ConfigurationFailure(service + '_quality_gate_pending')
        if service == 'teams':
            from tools.team_provider import contract
            from tools.team_maintenance import science_contract
            active = contract()
            scientific = science_contract()
        elif service == 'cov4':
            from scripts.subtopic_cov4 import active_contract
            from tools.evaluate_offline_ai import module_hash
            active = active_contract({})
            scientific = identity({path: module_hash(str(ROOT / path)) for path in (
                'scripts/subtopic_cov4.py', 'scripts/subtopic_records.py', 'scripts/subtopic_segmentation.py')})
        else:
            raise ConfigurationFailure('unknown_production_service')
        if selected.get('request_contract') != identity(active):
            raise ConfigurationFailure(service + '_qualified_contract_changed')
        if selected.get('scientific_contract') != scientific:
            raise ConfigurationFailure(service + '_qualified_science_changed')
    from tools.team_provider import routes
    for provider in ({'anthropic'} if service == 'cov4' else {route['provider'] for route in routes().values()}):
        if provider in ledger.read()['blocked_providers']:
            raise ConfigurationFailure(ledger.read()['blocked_providers'][provider])


def check_run_transport(ledger, start):
    """Stop this invocation after exhausted transient retries; later runs may retry."""
    if ledger is None:
        return
    rows = ledger.read()['requests'][start:]
    for provider in {row['provider'] for row in rows}:
        recent = [row for row in rows if row['provider'] == provider][-3:]
        if len(recent) == 3 and all(row.get('diagnostics', {}).get('category') == 'transient_transport' for row in recent):
            raise Deferred('provider_transient_run_stop')


class Ledger:
    """Cross-thread/process atomic reservations; a stale lock fails closed.

    Actions retains this ledger plus an outer full-run reservation artifact
    before dispatch. A missing checkpoint never restores a spent allowance.
    """
    def __init__(self, path, logical_id, limit_usd, max_requests=300):
        self.path = Path(path)
        self.logical_id = logical_id
        self.limit = int(Decimal(str(limit_usd)) * 1_000_000)
        self.max_requests = max_requests
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.locked():
            if self.path.exists():
                self.read()
            else:
                atomic_json(self.path, {"version": 1, "logical_id": logical_id, "limit_microusd": self.limit,
                    "max_requests": max_requests, "requests": [], "events": [], "blocked_providers": {}})

    @contextmanager
    def locked(self):
        lock = self.path.with_suffix(".lock")
        deadline = time.monotonic() + 10
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise Deferred("budget_lock_unavailable")
                time.sleep(.01)
        try:
            yield
        finally:
            lock.unlink()

    def read(self):
        value = json.loads(self.path.read_bytes())
        if (value.get("version") != 1 or value.get("logical_id") != self.logical_id
                or value.get("limit_microusd") != self.limit or value.get("max_requests") != self.max_requests):
            raise ValueError("logical_budget_identity_mismatch")
        return value

    def reserve(self, provider, model, stage, key, amount, attempt):
        with self.locked():
            state = self.read()
            allowance = state.get('active_allowance')
            if allowance and provider not in allowance['providers']:
                raise ConfigurationFailure('provider_outside_task_allowance')
            if provider in state["blocked_providers"]:
                raise ConfigurationFailure(state["blocked_providers"][provider])
            spent = sum(r["charged_microusd"] for r in state["requests"])
            if spent + amount > self.limit or len(state["requests"]) >= self.max_requests:
                raise Deferred("logical_budget_exhausted")
            token = uuid.uuid4().hex
            state["requests"].append({"id": token, "provider": provider, "model": model,
                "stage": stage, "key": key, "attempt": attempt, "reserved_microusd": amount,
                "charged_microusd": amount, "status": "reserved_unknown", "usage": None})
            atomic_json(self.path, state)
            return token

    def complete(self, token, **result):
        with self.locked():
            state = self.read()
            row = next(r for r in state["requests"] if r["id"] == token)
            row.update(result)
            atomic_json(self.path, state)

    def block(self, provider, reason):
        with self.locked():
            state = self.read()
            state['events'].append({'kind': 'provider_stop', 'provider': provider, 'reason': reason})
            state["blocked_providers"][provider] = reason
            atomic_json(self.path, state)

    def event(self, **event):
        with self.locked():
            state = self.read()
            state["events"].append(event)
            atomic_json(self.path, state)

    def summary(self):
        with self.locked():
            state = self.read()
        groups = {}
        for row in state["requests"]:
            group = groups.setdefault("/".join(row[k] for k in ("provider", "model", "stage")),
                {"attempts": 0, "retries": 0, "valid_completions": 0, "failures": 0,
                 "unknown_usage_requests": 0, "charged_microusd": 0, "latency_ms": 0,
                 "input_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0,
                 "output_tokens": 0, "reasoning_tokens": 0, "reasoning_usage_unknown": 0})
            group["attempts"] += 1
            group["retries"] += row["attempt"] > 1
            group["valid_completions"] += row["status"] == "valid"
            group["failures"] += row["status"] != "valid"
            group["charged_microusd"] += row["charged_microusd"]
            group["latency_ms"] += row.get("latency_ms", 0)
            if row["usage"] is None:
                group["unknown_usage_requests"] += 1
                continue
            for key, value in row["usage"].items():
                if value is not None:
                    group[key] += value
                elif key == "reasoning_tokens":
                    group["reasoning_usage_unknown"] += 1
        for group in groups.values():
            tokens = ('input_tokens', 'cached_input_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens')
            group['known_usage_totals'] = {key: group[key] for key in tokens}
            if group['unknown_usage_requests']:
                for key in tokens:
                    group[key] = None
            if group['reasoning_usage_unknown']:
                group['reasoning_tokens'] = None
        return {"logical_id": self.logical_id, "limit_usd": self.limit / 1e6,
            "charged_usd": sum(r["charged_microusd"] for r in state["requests"]) / 1e6,
            "by_provider_model_stage": groups, "events": state["events"],
            "blocked_providers": state["blocked_providers"], "prices_verified_at": config()["prices_verified_at"]}


def restore_ledger(path, logical_id, limit_usd, max_requests, authorization=None):
    """Restore a reviewed dynamic allowance without granting it or clearing stops."""
    path = Path(path)
    if not path.exists():
        return Ledger(path, logical_id, limit_usd, max_requests)
    state = json.loads(path.read_bytes())
    if not state.get('active_allowance'):
        return Ledger(path, logical_id, limit_usd, max_requests)
    if not authorization or state['active_allowance'] != authorization:
        raise ConfigurationFailure('task_allowance_identity_mismatch')
    grants = [event for event in state['events'] if event.get('kind') == 'task_allowance'
              and event.get('authorization', {}).get('id') == authorization['id']]
    if len(grants) != 1 or grants[0]['authorization'] != authorization:
        raise ConfigurationFailure('task_allowance_identity_mismatch')
    grant = grants[0]
    prefix = state['requests'][:grant['prior_request_count']]
    if (identity(prefix) != grant['prior_requests_sha256']
            or state['max_requests'] != grant['to_max_requests']
            or state['limit_microusd'] != grant['to_limit_microusd']
            or state['max_requests'] != len(prefix) + authorization['additional_requests']
            or state['limit_microusd'] != min(grant['from_limit_microusd'],
                int(Decimal(str(authorization['cumulative_usd'])) * 1_000_000),
                sum(row['charged_microusd'] for row in prefix) +
                    int(Decimal(str(authorization['additional_usd'])) * 1_000_000))):
        raise ConfigurationFailure('task_allowance_history_mismatch')
    return Ledger(path, logical_id, Decimal(state['limit_microusd']) / 1_000_000, state['max_requests'])


def authorize_allowance(path, logical_id, authorization):
    """Extend retained accounting once, from usage rather than historical counts.

    This never creates missing history and never clears an account denial.
    Repeating a grant must present the identical authorization, including its ID.
    All uncertain reservations are included in the monetary starting point.
    """
    path = Path(path)
    initial = json.loads(path.read_bytes())
    if initial.get('active_allowance', {}).get('id') == authorization['id']:
        return restore_ledger(path, logical_id, 0, 0, authorization)
    ledger = Ledger(path, logical_id, Decimal(initial['limit_microusd']) / 1_000_000,
                    initial['max_requests'])
    with ledger.locked():
        state = ledger.read()
        grants = [event for event in state['events'] if event.get('kind') == 'task_allowance'
                  and event.get('authorization', {}).get('id') == authorization['id']]
        if grants:
            if len(grants) != 1 or grants[0]['authorization'] != authorization:
                raise ConfigurationFailure('task_allowance_identity_mismatch')
            return ledger
        count = authorization['additional_requests']
        dollars = authorization['additional_usd']
        if type(count) is not int or count <= 0 or dollars <= 0:
            raise ValueError('invalid_task_allowance')
        spent = sum(row['charged_microusd'] for row in state['requests'])
        new_limit = min(state['limit_microusd'],
                        int(Decimal(str(authorization['cumulative_usd'])) * 1_000_000),
                        spent + int(Decimal(str(dollars)) * 1_000_000))
        if spent >= new_limit:
            raise Deferred('logical_budget_exhausted')
        grant = {'kind': 'task_allowance', 'authorization': authorization,
                 'prior_ledger_sha256': identity(state), 'prior_request_count': len(state['requests']),
                 'prior_requests_sha256': identity(state['requests']), 'prior_charged_microusd': spent,
                 'from_max_requests': state['max_requests'], 'from_limit_microusd': state['limit_microusd'],
                 'to_max_requests': len(state['requests']) + count, 'to_limit_microusd': new_limit}
        state.update(max_requests=grant['to_max_requests'], limit_microusd=new_limit,
                     active_allowance=authorization)
        state['events'].append(grant)
        atomic_json(path, state)
        ledger.limit, ledger.max_requests = new_limit, grant['to_max_requests']
    return ledger
