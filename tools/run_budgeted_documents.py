"""Run unchanged document/Cov4 semantics with bounded offline request accounting."""
import json
import os
from pathlib import Path
import runpy
import sys
import time

import requests

from tools.offline_ai import (Ledger, config, identity, atomic_json, encoded, normalize_usage,
                              cost_microusd, ConfigurationFailure, error_diagnostics)


def instrument(ledger, cache, classify):
    def bounded(candidate, *, api_key=None, session=None):
        from scripts import subtopic_cov4 as gate
        contract = {'provider': 'anthropic', 'model': gate.MODEL, 'prompt': gate.render_prompt(candidate),
                    'max_tokens': gate.MAX_TOKENS, 'timeout': gate.TIMEOUT_SECONDS, 'api_version': gate.API_VERSION,
                    'response_contract': 'unchanged-cov4-production-1'}
        key = identity(contract)
        path = cache / (key + '.json')
        if path.exists():
            cached = json.loads(path.read_bytes())
            if cached.get('key') == key and cached.get('status') == 'refusal':
                ledger.event(provider='anthropic', model=gate.MODEL, stage='cov4', event='retained_refusal', key=key)
                return gate._unresolved('provider_safety_refusal', api_request=False)
            value = cached.get('value', {})
            if (cached.get('key') == key and value.get('fundability') in (gate.ACCEPT, gate.REJECT)
                    and value.get('classifier_owned') in (True, False, None) and not value.get('error')):
                ledger.event(provider='anthropic', model=gate.MODEL, stage='cov4', event='cache_hit', key=key)
                return value | {'api_request': False, 'usage_reported': False, 'usage': {}}
        ledger.event(provider='anthropic', model=gate.MODEL, stage='cov4', event='cache_miss', key=key)
        transport = session or requests
        dispatched = []
        refused = []
        class BudgetSession:
            def post(self, url, **kwargs):
                body = kwargs['json']
                prices = config()['prices_per_million'][body['model']]
                amount = cost_microusd({'input_tokens': len(encoded(body)) + 1024, 'cached_input_tokens': 0,
                    'cache_write_tokens': 0, 'output_tokens': body['max_tokens']},
                    prices | {'input': max(prices['input'], prices['cache_write'])})
                token = ledger.reserve('anthropic', body['model'], 'cov4', key, amount, 1)
                dispatched.append(token)
                start = time.monotonic()
                response = transport.post(url, **kwargs)
                ledger.complete(token, latency_ms=int((time.monotonic() - start) * 1000), http_status=response.status_code)
                if response.status_code in (400, 401, 403, 404, 422):
                    ledger.complete(token, diagnostics=error_diagnostics(response), status='configuration_failure')
                    ledger.block('anthropic', f'anthropic_configuration_http_{response.status_code}')
                if response.status_code == 200:
                    payload = response.json()
                    usage = normalize_usage('anthropic', payload)
                    ledger.complete(token, usage=usage, returned_model=payload.get('model'), status='received_unvalidated',
                                    charged_microusd=cost_microusd(usage, prices) if usage else amount)
                    if payload.get('stop_reason') == 'refusal':
                        refused.append(True)
                        atomic_json(path, {'key': key, 'status': 'refusal'})
                        raise ConfigurationFailure('provider_safety_refusal')
                return response
        result = classify(candidate, api_key=api_key, session=BudgetSession())
        if dispatched:
            ledger.complete(dispatched[-1], status='Refusal' if refused else 'valid' if not result.get('error') else 'invalid_or_unavailable')
        result['api_request'] = bool(dispatched)
        if not result.get('error'):
            atomic_json(path, {'key': key, 'value': result})
        return result
    return bounded


def main():
    from scripts import subtopic_cov4 as gate
    state = Path(os.environ['OFFLINE_AI_STATE'])
    mode = os.environ['TEAM_MODE']
    ledger = Ledger(state / 'ledger.json', state.name, config()['budgets_usd'][mode], config()['max_requests'])
    gate.classify_fundability = instrument(ledger, state / 'cov4-cache', gate.classify_fundability)
    # Only the session/accounting boundary changes. Parser, prompt, ownership,
    # native/reference guards and acceptance functions remain untouched.
    sys.argv[0] = 'scripts.extract_document_evidence'
    try:
        runpy.run_module('scripts.extract_document_evidence', run_name='__main__')
    finally:
        atomic_json(state / 'usage-summary.json', ledger.summary())


if __name__ == '__main__':
    main()
