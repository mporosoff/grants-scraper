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

TRANSPORT_VERSION = "anthropic-structured-json-1"


class SchemaFailure(ValueError):
    def __init__(self, diagnostic):
        super().__init__("response_schema_failure")
        self.diagnostic = diagnostic


def anthropic_schema(schema):
    """Project our finite schema vocabulary onto Anthropic's supported subset.

    The original schema remains authoritative after parsing. Property names are
    never interpreted as keywords, and the input is never modified.
    https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    """
    supported = {"type", "properties", "required", "additionalProperties", "items",
                 "enum", "const", "description", "title"}
    constraints = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
    unknown = set(schema) - supported - constraints
    if unknown:
        raise ValueError("unsupported_application_schema_keyword")
    result = {}
    for key, value in schema.items():
        if key == "properties":
            result[key] = {name: anthropic_schema(child) for name, child in value.items()}
        elif key == "items":
            result[key] = anthropic_schema(value)
        elif key not in constraints:
            result[key] = value
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError("open_object_schema_not_supported")
    limits = {key: value for key, value in schema.items() if key in constraints}
    if limits:
        result["description"] = (result.get("description", "") +
            " Application constraints: " + json.dumps(limits, sort_keys=True)).strip()
    return result


def shape(value, depth=0):
    """Bounded types/counts only; no scientific text, reasoning or raw bodies."""
    result = {"type": type(value).__name__}
    if isinstance(value, (str, list, dict)):
        result["length"] = len(value)
    if isinstance(value, list) and depth < 2:
        result["items"] = [shape(item, depth + 1) for item in value[:6]]
    return result


def validate_schema(value, schema, path="$"):
    """Validate the full shared application shape before scientific validation."""
    expected = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "number": (int, float), "null": type(None)}
    actual = type(value).__name__
    diagnostic = {"path": path, "expected_type": expected, "actual_type": actual,
                  "missing_keys": [], "unexpected_keys": [], "shape": shape(value)}
    def fail(rule):
        raise SchemaFailure(diagnostic | {"rule": rule})
    if expected and (not isinstance(value, types[expected]) or
                     expected in {"number", "integer"} and isinstance(value, bool)):
        fail("type")
    if "enum" in schema and value not in schema["enum"]:
        fail("enum")
    if "const" in schema and value != schema["const"]:
        fail("const")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        diagnostic["missing_keys"] = sorted(set(schema.get("required", [])) - set(value))
        # Unexpected names are diagnostic identifiers, never arbitrary text.
        extra = set(value) - set(properties)
        diagnostic["unexpected_keys"] = [key if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,47}", key)
            else "sha256:" + identity(key) for key in sorted(extra)[:12]]
        if diagnostic["missing_keys"] or extra and schema.get("additionalProperties") is False:
            fail("object_keys")
        for key, child in properties.items():
            if key in value:
                validate_schema(value[key], child, path + "." + key)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            fail("array_length")
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], path + f"[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            fail("string_length")
    if type(value) in (int, float):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            fail("numeric_bounds")
    return value


def stop_reason(payload):
    value = payload.get("stop_reason", payload.get("status")) if isinstance(payload, dict) else None
    return value if (value is None or isinstance(value, str)) and value in {"end_turn", "max_tokens", "refusal", "stop_sequence", "tool_use",
        "pause_turn", "completed", "incomplete", "failed", "cancelled", None} else "unknown"


def request_body(route, stage, prompt, data, schema):
    if route["provider"] == "openai":
        return {"model": route["model"], "store": False, "reasoning": {"effort": route["reasoning"]},
            "instructions": prompt, "input": json.dumps(data, ensure_ascii=False),
            "text": {"verbosity": "low", "format": {"type": "json_schema", "name": stage["schema_version"],
                       "strict": True, "schema": schema}}, "max_output_tokens": stage["max_output_tokens"]}
    return {"model": route["model"], "system": prompt, "max_tokens": stage["max_output_tokens"],
            "messages": [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
            "output_config": {"format": {"type": "json_schema", "schema": anthropic_schema(schema)}}}


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
                value = validate(validate_schema(cached["value"], schema))
            except (FileNotFoundError, ValueError, TypeError, KeyError):
                if path.exists():
                    prior = path.read_bytes()
                    history = self.cache / 'history' / (key + '-' + identity(list(prior)) + '.json')
                    history.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(history)
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
            prior_attempts = sum(row['key'] == key for row in self.ledger.read()['requests']) if stage.get('durable_attempts') else 0
            if prior_attempts >= stage['max_attempts']:
                raise Deferred('request_attempt_allowance_exhausted')
            for attempt in range(prior_attempts + 1, stage["max_attempts"] + 1):
                payload, parsed = None, None
                remaining = self.deadline - time.monotonic()
                if remaining <= 1:
                    raise Deferred("work_deadline_exhausted")
                token = self.ledger.reserve(provider, route["model"], stage_name, key, amount, attempt)
                self.ledger.complete(token, input_hash=identity(data), transport_version=TRANSPORT_VERSION)
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
                    self.ledger.complete(token, provider_stop_reason=stop_reason(payload))
                    parsed = response_value(provider, payload)
                    value = validate(validate_schema(parsed, schema))
                    if not isinstance(payload.get("model"), str) or not payload["model"]:
                        raise ValueError("missing_returned_model_identity")
                    atomic_json(path, {"key": key, "returned_model": payload["model"], "value": value,
                                      "transport_version": TRANSPORT_VERSION})
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
                    category = ("truncation" if isinstance(error, Incomplete) else
                                "transient_transport" if isinstance(error, requests.RequestException) else
                                "schema_failure" if isinstance(error, (SchemaFailure, json.JSONDecodeError)) else
                                "semantic_validation_failure")
                    diagnostic = {"stage": stage_name, "input_hash": identity(data), "contract_hash": key,
                        "category": category, "shape": shape(parsed),
                        "provider_stop_reason": stop_reason(payload),
                        **(error.diagnostic if isinstance(error, SchemaFailure) else {})}
                    self.ledger.complete(token, status=type(error).__name__, diagnostics=diagnostic)
                    atomic_json(self.cache / "failures" / (token + ".json"), diagnostic)
                    # One authority owns retries. A malformed scientific answer is
                    # never patched locally, accepted partially or retried unchanged.
                    if category in {"semantic_validation_failure", "truncation"} or attempt == stage["max_attempts"]:
                        raise
                    if category == "schema_failure":
                        if attempt > 1:
                            raise
                        correction = "\nReturn a complete new decision conforming to the schema. Format diagnostic: " + json.dumps(diagnostic)
                        body = request_body(route, stage, prompt + correction, data, schema)
                        input_ceiling = len(encoded(body)) + 1024
                        if input_ceiling > 200_000:
                            raise Deferred("bounded_prompt_exceeded")
                        amount = cost_microusd({"input_tokens": input_ceiling, "cached_input_tokens": 0,
                            "cache_write_tokens": 0, "output_tokens": stage["max_output_tokens"]},
                            price | {"input": max(price["input"], price["cache_write"])})
                    delay = 2 ** (attempt - 1)
                    if time.monotonic() + delay >= self.deadline:
                        raise Deferred("retry_deadline_exhausted")
                    time.sleep(delay)
