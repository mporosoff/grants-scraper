"""Direct team/evaluation requests with validated complete-stage reuse."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import threading
import time
import requests

from tools.offline_spend import (
    ROOT, encoded, identity, atomic_json, Deferred, ConfigurationFailure, Refusal,
    Incomplete, error_diagnostics, config, compatible_model, normalize_usage,
    cost_microusd, Ledger,
)


def request_body(route, stage, prompt, data, schema):
    if route["provider"] == "openai":
        return {"model": route["model"], "store": False, "reasoning": {"effort": route["reasoning"]},
            "instructions": prompt, "input": json.dumps(data, ensure_ascii=False),
            "text": {"verbosity": "low", "format": {"type": "json_schema", "name": stage["schema_version"],
                       "strict": True, "schema": schema}}, "max_output_tokens": stage["max_output_tokens"]}
    return {"model": route["model"], "system": prompt, "max_tokens": stage["max_output_tokens"],
            "messages": [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}


def response_value(provider, payload):
    if not isinstance(payload, dict):
        raise ValueError('invalid_response_envelope')
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
        content = payload.get('content')
        if not isinstance(content, list) or any(not isinstance(part, dict) for part in content):
            raise ValueError('invalid_response_content')
        text = "".join(part.get("text", "") for part in content if part.get("type") == "text")
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
                if not compatible_model(route['model'], cached['returned_model']):
                    raise ValueError("cache_model_identity_missing")
                value = validate(cached["value"])
            except (FileNotFoundError, ValueError, TypeError, KeyError):
                path.unlink(missing_ok=True)
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
                        self.ledger.complete(token, diagnostics=error_diagnostics(response))
                        reason = f"{provider}_configuration_http_{response.status_code}"
                        self.ledger.block(provider, reason)
                        raise ConfigurationFailure(reason)
                    if response.status_code != 200:
                        raise requests.RequestException(f"provider_http_{response.status_code}")
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError('invalid_response_envelope')
                    usage = normalize_usage(provider, payload)
                    returned = payload.get('model')
                    model_matches = compatible_model(route['model'], returned)
                    self.ledger.complete(token, usage=usage, returned_model=returned,
                        status='received_model_unverified')
                    if not model_matches:
                        self.ledger.block(provider, 'unexpected_returned_model_identity')
                        raise ConfigurationFailure('unexpected_returned_model_identity')
                    self.ledger.complete(token,
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
