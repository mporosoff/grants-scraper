"""Direct offline model requests with durable, conservative application budgets.

No SDK retries, provider fallback, secret discovery, or public-runtime routing.
Only validated public-derived decisions enter the response cache. Usage is
recorded before output parsing; an uncertain request consumes its reservation.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

import requests

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


def config():
    return json.loads((ROOT / "config/offline_ai.json").read_bytes())


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
        return {"logical_id": self.logical_id, "limit_usd": self.limit / 1e6,
            "charged_usd": sum(r["charged_microusd"] for r in state["requests"]) / 1e6,
            "by_provider_model_stage": groups, "events": state["events"],
            "blocked_providers": state["blocked_providers"], "prices_verified_at": config()["prices_verified_at"]}


def request_body(route, stage, prompt, data, schema):
    if route["provider"] == "openai":
        return {"model": route["model"], "store": False, "reasoning": {"effort": route["reasoning"]},
            "instructions": prompt, "input": json.dumps(data, ensure_ascii=False),
            "text": {"verbosity": "low", "format": {"type": "json_schema", "name": stage["schema_version"],
                       "strict": True, "schema": schema}}, "max_output_tokens": stage["max_output_tokens"]}
    return {"model": route["model"], "system": prompt, "max_tokens": stage["max_output_tokens"],
            "messages": [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}


def response_value(provider, payload):
    if provider == "openai":
        parts = [part for item in payload.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in parts):
            raise Refusal("provider_safety_refusal")
        if payload.get("status") != "completed":
            raise Incomplete("incomplete_response")
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "output_text")
    else:
        if payload.get("stop_reason") == "refusal":
            raise Refusal("provider_safety_refusal")
        if payload.get("stop_reason") != "end_turn":
            raise Incomplete("incomplete_response")
        text = "".join(part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


class Client:
    def __init__(self, ledger, cache, deadline=float("inf"), post=None):
        self.ledger, self.cache, self.deadline = ledger, Path(cache), deadline
        self.post = post or requests.post
        self.key_locks, self.lock = {}, threading.Lock()

    def json(self, route, stage_name, prompt, data, schema, validate, *, stage_config=None):
        settings = config()
        stage = stage_config or settings["stages"][stage_name]
        contract = {"route": route, "stage": stage_name, "config": stage, "prompt": prompt,
                    "schema": schema, "inputs": data}
        key = identity(contract)
        with self.lock:
            lock = self.key_locks.setdefault(key, threading.Lock())
        with lock:
            path = self.cache / (key + ".json")
            try:
                cached = json.loads(path.read_bytes())
                if cached["key"] != key:
                    raise ValueError("cache_identity_mismatch")
                if cached.get("status") == "refusal":
                    self.ledger.event(provider=route["provider"], model=route["model"], stage=stage_name,
                                      event="retained_refusal", key=key)
                    raise Refusal("retained_provider_safety_refusal")
                if not cached["returned_model"]:
                    raise ValueError("cache_model_identity_missing")
                value = validate(cached["value"])
            except (FileNotFoundError, ValueError, TypeError, KeyError):
                self.ledger.event(provider=route["provider"], model=route["model"], stage=stage_name,
                                  event="cache_miss", key=key, reason="missing_or_invalid_exact_contract")
            else:
                self.ledger.event(provider=route["provider"], model=route["model"], stage=stage_name,
                                  event="cache_hit", key=key)
                return value
            body = request_body(route, stage, prompt, data, schema)
            price = settings["prices_per_million"][route["model"]]
            # UTF-8 bytes are a conservative token ceiling; include serialization
            # and schema plus a framing margin. No tools or >272K prompts allowed.
            input_ceiling = len(encoded(body)) + 1024
            if input_ceiling > 200_000:
                raise Deferred("bounded_prompt_exceeded")
            amount = cost_microusd({"input_tokens": input_ceiling, "cached_input_tokens": 0,
                "cache_write_tokens": 0, "output_tokens": stage["max_output_tokens"]},
                price | {"input": max(price["input"], price["cache_write"])})
            provider = route["provider"]
            key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
            secret = os.environ.get(key_name)
            if not secret:
                self.ledger.block(provider, "missing_actions_step_credential")
                raise ConfigurationFailure("missing_actions_step_credential")
            url = "https://api.openai.com/v1/responses" if provider == "openai" else "https://api.anthropic.com/v1/messages"
            headers = {"Content-Type": "application/json", "User-Agent": "FundingFinder-OfflineEvaluation/1.0"}
            headers.update({"Authorization": "Bearer " + secret} if provider == "openai" else
                           {"x-api-key": secret, "anthropic-version": "2023-06-01"})
            for attempt in range(1, stage["max_attempts"] + 1):
                remaining = self.deadline - time.monotonic()
                if remaining <= 1:
                    raise Deferred("work_deadline_exhausted")
                token = self.ledger.reserve(provider, route["model"], stage_name, key, amount, attempt)
                started = time.monotonic()
                try:
                    response = self.post(url, headers=headers, json=body, timeout=min(stage["timeout_seconds"], remaining),
                                         allow_redirects=False)
                    latency = int((time.monotonic() - started) * 1000)
                    self.ledger.complete(token, http_status=response.status_code, latency_ms=latency)
                    if response.status_code in (400, 401, 403, 404, 422):
                        reason = f"{provider}_configuration_http_{response.status_code}"
                        self.ledger.block(provider, reason)
                        raise ConfigurationFailure(reason)
                    if response.status_code != 200:
                        raise requests.RequestException(f"provider_http_{response.status_code}")
                    payload = response.json()
                    usage = normalize_usage(provider, payload)
                    self.ledger.complete(token, usage=usage, returned_model=payload.get("model"),
                        status="received_unvalidated", charged_microusd=cost_microusd(usage, price) if usage else amount)
                    value = validate(response_value(provider, payload))
                    if not isinstance(payload.get("model"), str) or not payload["model"]:
                        raise ValueError("missing_returned_model_identity")
                    atomic_json(path, {"key": key, "returned_model": payload["model"], "value": value})
                    self.ledger.complete(token, status="valid")
                    return value
                except Refusal:
                    atomic_json(path, {"key": key, "status": "refusal", "returned_model": payload.get("model")})
                    self.ledger.complete(token, status="Refusal")
                    raise
                except ConfigurationFailure as error:
                    self.ledger.complete(token, status=type(error).__name__)
                    raise
                except (ValueError, TypeError, KeyError, requests.RequestException) as error:
                    self.ledger.complete(token, status=type(error).__name__)
                    if attempt == stage["max_attempts"]:
                        raise
                    delay = 2 ** (attempt - 1)
                    if time.monotonic() + delay >= self.deadline:
                        raise Deferred("retry_deadline_exhausted")
                    time.sleep(delay)
