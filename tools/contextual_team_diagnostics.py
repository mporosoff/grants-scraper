"""Opt-in bounded diagnostics for the two public-evidence offline operations.

Never used as a successful cache. Only final text is retained, never reasoning
blocks, unrestricted response bodies, request headers, cookies or credentials.
"""
from datetime import datetime, timezone
import json
import os
import re
from tools.offline_ai import stop_reason
from tools.offline_spend import atomic_json, identity, encoded, ConfigurationFailure

MAX_TEXT = 196608
MAX_WIRE = 2 * 1024 * 1024


def redact(value, maximum=1000):
    if not isinstance(value, str):
        return None
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN',
                 'REGISTRY_WORKFLOW_TOKEN', 'VOYAGE_API_KEY'):
        secret = os.environ.get(name)
        if secret:
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'(?i)(bearer\s+\S+|sk-[\w-]+|gh[pousr]_[\w]+|eyJ[\w.-]{20,})', '[REDACTED]', value)
    value = re.sub(r'(?i)(authorization|api[_-]?key|cookie|token)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', value)
    return value[:maximum]


def final_text(provider, payload):
    if provider == 'anthropic':
        return ''.join(p.get('text', '') for p in payload.get('content', [])
            if isinstance(p, dict) and p.get('type') == 'text' and isinstance(p.get('text'), str))
    return ''.join(p['text'] for item in payload.get('output', [])
        if isinstance(item, dict) and item.get('type') == 'message'
        for p in item.get('content', []) if isinstance(p, dict) and p.get('type') == 'output_text'
        and isinstance(p.get('text'), str))


def safe_usage(usage):
    if not isinstance(usage, dict):
        return None
    result = {}
    for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens',
                'cache_write_tokens', 'cached_input_tokens', 'reasoning_tokens'):
        if type(usage.get(key)) is int and usage[key] >= 0:
            result[key] = usage[key]
    for key, subkeys in {'output_tokens_details': ('thinking_tokens', 'reasoning_tokens'),
                        'input_tokens_details': ('cached_tokens',),
                        'cache_creation': ('ephemeral_1h_input_tokens', 'ephemeral_5m_input_tokens')}.items():
        nested = usage.get(key)
        if isinstance(nested, dict):
            result[key] = {k:nested[k] for k in subkeys if type(nested.get(k)) is int and nested[k] >= 0}
    return result


def path(state, receipt):
    return state / 'diagnostics' / (receipt['request_id'] + '.json')


def read_response(runner, response, provider, body, receipt):
    d = {'version': 'public-scientific-final-diagnostic-v1',
        'request_id': receipt['request_id'], 'body_sha256': identity(body),
        'provider': provider, 'http_status': response.status_code,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'final_answer_captured': False, 'final_answer_complete': False,
        'accepted_cache': False, 'retention_days': 90}
    for key in ('request-id', 'x-request-id'):
        value = getattr(response, 'headers', {}).get(key)
        if isinstance(value, str):
            d['provider_request_id'] = redact(value, 200)
            break
    target = path(runner.state, receipt)
    atomic_json(target, d)  # Headers survive a later body/transport failure.
    parts = []; size = 0
    try:
        for part in response.iter_content(65536):
            size += len(part)
            if size > MAX_WIRE:
                d['envelope_truncated'] = True
                raise ValueError('diagnostic_response_wire_bound')
            parts.append(part)
        raw = b''.join(parts)
        d['response_envelope_sha256'] = identity(raw.hex())
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            d['envelope_invalid_json'] = True
            raise ValueError('diagnostic_invalid_json_envelope')
        if not isinstance(payload, dict):
            raise ValueError('diagnostic_invalid_envelope')
        status = stop_reason(payload)
        if status is not None:
            d['completion_status'] = status
        if isinstance(payload.get('model'), str):
            d['returned_model'] = redact(payload['model'], 100)
        usage = safe_usage(payload.get('usage'))
        if usage is not None:
            d['reported_usage'] = usage
            try:
                normalized, charge = runner.request_usage(provider, payload, body['model'])
                receipt.update(usage=normalized, charged_microusd=charge)
            except (ValueError, TypeError, KeyError):
                d['usage_reconciliation'] = 'incomplete_or_invalid'
        error = payload.get('error')
        if isinstance(error, dict):
            d['error'] = {k:redact(error[k], 1000 if k == 'message' else 200)
                for k in ('type', 'code', 'param', 'parameter', 'message') if isinstance(error.get(k), str)}
        text = final_text(provider, payload)
        if text:
            original = text.encode('utf8')
            retained = redact(original[:MAX_TEXT].decode('utf8', errors='ignore'), MAX_TEXT)
            d.update(final_answer_captured=True, final_answer_complete=len(original) <= MAX_TEXT,
                final_answer_bytes=len(original), final_answer_sha256=identity(text),
                final_answer_text=retained, final_answer_redacted=retained != text,
                retained_text_sha256=identity(retained))
        # Do not retain refusal/reasoning blocks or the raw provider envelope.
        if response.status_code != 200:
            raise ConfigurationFailure('http_' + str(response.status_code))
        if text and len(text.encode('utf8')) > MAX_TEXT:
            raise ValueError('diagnostic_final_answer_bound')
        return payload
    finally:
        response.close()
        atomic_json(target, d)
        receipt['diagnostic_path'] = target.relative_to(runner.state).as_posix()


def finish(state, receipt):
    target = path(state, receipt)
    if not target.exists():
        return
    d = json.loads(target.read_bytes())
    d['validation'] = {k:receipt[k] for k in ('status', 'error', 'disposition', 'schema_diagnostic',
        'semantic_diagnostic', 'charged_microusd', 'usage') if k in receipt}
    # A diagnostic remains non-authoritative even when validation succeeded.
    atomic_json(target, d)
    receipt['diagnostic_sha256'] = identity(d)
