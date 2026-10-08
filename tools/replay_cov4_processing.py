"""Authenticate paid Cov4 decisions and replay changed processing without providers.

This produces processing evidence only. It cannot approve source review, enable
production, change an allowance, or qualify changed classifier requests.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from scripts import subtopic_cov4 as gate
from tools import evaluate_offline_ai as evaluation
from tools import run_budgeted_documents as documents, run_cov4_validation as harness
from tools.offline_ai import compatible_model, identity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / 'evaluation/sonnet_cov4_qualification_20260909.json'
SCIENCE_MODULES = ('scripts/subtopic_cov4.py', 'scripts/subtopic_records.py',
                   'scripts/subtopic_segmentation.py')
PROCESSING_MODULES = SCIENCE_MODULES + ('tools/run_cov4_validation.py', 'tools/offline_ai.py',
    'tools/run_budgeted_documents.py', 'tools/evaluate_team_prompt_repair.py',
    'tools/replay_cov4_processing.py')


def _load(path):
    return json.loads(Path(path).read_bytes())


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _key(selected):
    return identity({'route': selected['route'], 'stage': 'cov4', 'config': selected['stage'],
        'prompt': selected['prompt'], 'schema': selected['schema'], 'inputs': selected['inputs']})


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines()]


def _current(population):
    protocol, candidates = evaluation.production_cov4_cases(population)
    generic = harness.generic_records(candidates)
    return {'protocol': protocol, 'population': candidates, 'generic_records': generic,
        'bypasses': harness.bypassed_records(),
        'active_requests': [gate.active_contract(gate.candidate_from_record(parent, built[0], document))
                            for _, parent, document, built in generic]}


class ReadOnlyLedger:
    def __init__(self, snapshot):
        self.snapshot = deepcopy(snapshot)

    def read(self):
        return deepcopy(self.snapshot)

    def event(self, **_kwargs):
        raise RuntimeError('Processing replay cannot write accounting events')

    def reserve(self, *_args, **_kwargs):
        raise RuntimeError('Processing replay cannot reserve provider work')


def authenticate(state, *, evidence=DEFAULT_EVIDENCE):
    """Bind exact responses to the reviewed report, historical results and paid rows."""
    state, evidence = Path(state).resolve(), Path(evidence).resolve()
    report = _load(evidence)
    trusted = report['qualification']
    protocol = trusted['configuration']['protocol']
    _require(report.get('quality_gate_passed') is True
             and report.get('source_review', {}).get('status') == 'passed',
             'Historical source qualification is missing')
    _require(trusted.get('execution_complete') is True and trusted.get('numerical_gate_passed') is True,
             'Historical numerical qualification is incomplete')
    _require(identity(trusted['configuration']) == trusted['evaluation_contract'],
             'Historical configuration digest mismatch')
    _require(len(trusted['configuration']['active_requests']) == 43
             and protocol['population_size'] == 43 and len(protocol['controls']) == 5,
             'Expected the historical 43-case population and five controls')
    preflight_path = state / 'production-preflight-receipt.json'
    preflight = _load(preflight_path)
    native = evaluation.production_preflight_configuration()
    _require(preflight.get('complete') is True and preflight.get('result') == {'ready': True}
             and preflight['contract'] == identity(native)
             and trusted['configuration']['preflight_contract'] == preflight['contract'],
             'Exact historical transport preflight does not match')
    ledger_path = state / 'ledger.json'
    ledger = _load(ledger_path)
    paths = {evidence, preflight_path, ledger_path}
    populations = {}
    for population in ('controls', 'population'):
        destination = state / protocol['version'] / population
        receipt_path, results_path = destination / 'qualification-receipt.json', destination / 'results.jsonl'
        receipt = _load(receipt_path)
        rows = _rows(results_path)
        current = _current(population)
        _require(identity(receipt['configuration']) == receipt['evaluation_contract'],
                 population + ': historical configuration digest mismatch')
        _require(receipt.get('execution_complete') is True and receipt.get('numerical_gate_passed') is True,
                 population + ': incomplete historical qualification')
        if population == 'population':
            _require(receipt == trusted, 'Retained population receipt differs from reviewed evidence')
        for field in ('protocol', 'population', 'generic_records', 'bypasses', 'active_requests'):
            _require(identity(current[field]) == identity(receipt['configuration'][field]),
                     population + ': changed ' + field + ' requires a separate qualification')
        _require(receipt['configuration']['preflight_contract'] == preflight['contract'],
                 population + ': preflight provenance mismatch')
        _require(len(rows) == len(current['population']) and identity(rows) == receipt['result_hash'],
                 population + ': historical result digest mismatch')
        selected_keys = {_key(selected) for selected in current['active_requests']}
        _require(len(selected_keys) == len(current['population'])
                 and selected_keys == set(receipt['response_hashes']),
                 population + ': incomplete historical response population')
        paths.update((receipt_path, results_path))
        populations[population] = {'current': current, 'retained': receipt, 'rows': rows}
    controls, full = populations['controls'], populations['population']
    control_ids = set(protocol['controls'])
    _require(controls['rows'] == [row for row in full['rows'] if row['candidate_id'] in control_ids],
             'Historical controls differ from their population decisions')
    _require(all(trusted['response_hashes'].get(key) == digest
                 for key, digest in controls['retained']['response_hashes'].items()),
             'Historical control response hashes differ from the paid population')
    paid = []
    cache = state / 'cov4-production-cache'
    for selected in full['current']['active_requests']:
        key = _key(selected)
        path = cache / (key + '.json')
        cached = _load(path)
        _require(cached.get('key') == key and identity(cached) == trusted['response_hashes'][key]
                 and compatible_model(selected['route']['model'], cached.get('returned_model'))
                 and cached.get('transport_version') == preflight.get('transport'),
                 'Paid response cache provenance mismatch: ' + key)
        matches = [row for row in ledger['requests'] if row.get('key') == key
                   and row.get('stage') == 'cov4' and row.get('provider') == 'anthropic'
                   and row.get('model') == selected['route']['model'] and row.get('status') == 'valid'
                   and row.get('http_status') == 200]
        _require(len(matches) == 1, 'Exact paid Cov4 ledger response is missing or ambiguous: ' + key)
        paid.append(matches[0])
        paths.add(path)
    native_request = identity({'route': native['route'], 'stage': 'preflight',
        'config': native['stage'] | {'preflight_contract': preflight['contract']},
        'prompt': 'Return exactly the requested readiness object.', 'schema': native['schema'],
        'inputs': {'ready': True}})
    _require(any(row.get('key') == native_request and row.get('stage') == 'preflight'
                 and row.get('provider') == 'anthropic' and row.get('status') == 'valid'
                 for row in ledger['requests']), 'Paid native preflight ledger response is missing')
    preflight_cache_path = state / 'cache' / (native_request + '.json')
    preflight_cache = _load(preflight_cache_path)
    _require(preflight_cache.get('key') == native_request
             and preflight_cache.get('value') == {'ready': True}
             and compatible_model(native['route']['model'], preflight_cache.get('returned_model'))
             and preflight_cache.get('transport_version') == preflight.get('transport'),
             'Retained native preflight response provenance mismatch')
    paths.add(preflight_cache_path)
    _require(len(ledger['requests']) == report['accounting']['cumulative_requests']
             and sum(row['charged_microusd'] for row in ledger['requests'])
                 == int(Decimal(str(report['accounting']['cumulative_estimated_usd'])) * 1_000_000),
             'Historical ledger totals differ from the reviewed accounting')
    return {'state': state, 'cache': cache, 'evidence': evidence, 'report': report,
        'ledger': ledger, 'populations': populations, 'preflight_contract': preflight['contract'],
        'files': {str(path): _sha(path) for path in sorted(paths)},
        'paid_requests': len(paid), 'paid_microusd': sum(row['charged_microusd'] for row in paid)}


def _check_unchanged(authenticated):
    _require(all(Path(path).is_file() and _sha(path) == digest
                 for path, digest in authenticated['files'].items()),
             'Historical qualification evidence changed during processing replay')


def replay_processing(state, output, *, evidence=DEFAULT_EVIDENCE):
    """Write a new processing receipt; never rewrite or relabel historical evidence."""
    state, output, evidence = Path(state).resolve(), Path(output).resolve(), Path(evidence).resolve()
    _require(output != state and state not in output.parents and output not in state.parents,
             'Replay output must be separate from historical state')
    _require(output != evidence and output not in evidence.parents,
             'Replay output must not contain historical reviewed evidence')
    _require(not output.exists(), 'Replay output already exists; preserve prior evidence')
    authenticated = authenticate(state, evidence=evidence)
    output.mkdir(parents=True)
    results = {}
    # No credential, live client, socket connection, or authorization constructor
    # participates. ReplayClient independently verifies each exact cache key.
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'}}
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        for target in ('tools.offline_ai.Client', 'requests.sessions.Session.request', 'socket.socket.connect'):
            stack.enter_context(patch(target, side_effect=RuntimeError('Provider calls are forbidden in processing replay')))
        classify = documents.instrument(ReadOnlyLedger(authenticated['ledger']), authenticated['cache'],
                                        gate.classify_fundability, replay=True)
        stack.enter_context(patch.object(gate, 'classify_fundability', classify))
        for population, data in authenticated['populations'].items():
            path = output / (population + '-results.jsonl')
            with redirect_stdout(io.StringIO()):
                metrics = harness.run(path, live=False, candidates=data['current']['population'])
            metrics.pop('raw', None)
            metrics.pop('live', None)
            rows = _rows(path)
            _require(rows == data['rows'] and identity(rows) == data['retained']['result_hash'],
                     population + ': replayed decisions differ from paid qualification')
            _require(metrics == data['retained']['metrics'] and not metrics['api_errors'],
                     population + ': replayed metrics differ from paid qualification')
            _require(metrics['candidates_bypassed_by_provenance'] == {'native': 5, 'referenced': 14}
                     and metrics['bypass_classifier_calls'] == 0,
                     population + ': provenance bypass contract changed')
            results[population] = {'execution_complete': True, 'numerical_gate_passed': True,
                'new_provider_requests': 0, 'result_hash': identity(rows),
                'results_sha256': _sha(path), 'metrics': metrics,
                'active_requests_sha256': identity(data['current']['active_requests']),
                'historical_evaluation_contract': data['retained']['evaluation_contract']}
    _check_unchanged(authenticated)
    modules = {path: evaluation.module_hash(ROOT / path) for path in PROCESSING_MODULES}
    receipt = {'version': 'cov4-processing-replay-1', 'historical_evidence': {
            'path': str(evidence), 'sha256': authenticated['files'][str(evidence)],
            'qualification_contract': authenticated['report']['qualification']['evaluation_contract']},
        'processing': {'modules': modules,
            'instrument': evaluation.function_hash(documents.instrument),
            'scientific_contract': identity({path: modules[path] for path in SCIENCE_MODULES}),
            'request_contract': identity(gate.active_contract({}))},
        'preflight_contract': authenticated['preflight_contract'],
        'responses': {'count': authenticated['paid_requests'],
            'original_charged_microusd': authenticated['paid_microusd'],
            'hashes': authenticated['report']['qualification']['response_hashes']},
        'historical_files_sha256': authenticated['files'], 'populations': results,
        'new_provider_requests': 0, 'ledger_byte_identical': True, 'paid_response_hashes_unchanged': True,
        'execution_complete': True, 'numerical_gate_passed': True,
        'source_review': 'required', 'quality_gate_passed': False, 'production_enabled': False}
    (output / 'processing-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay_processing(args.state, args.output)
    print(json.dumps({key: result[key] for key in ('version', 'execution_complete',
        'numerical_gate_passed', 'new_provider_requests', 'source_review', 'quality_gate_passed', 'production_enabled')}))


if __name__ == '__main__':
    main()
