"""Focused established-service repair; no model search or production mutation."""
import argparse
import json
import os
from pathlib import Path
import time

import requests

from tools import evaluate_offline_ai as original
from tools import evaluate_team_prompt_repair as trial
from tools.offline_ai import Client, Ledger, ConfigurationFailure, atomic_json, compatible_model, config, identity

PROTOCOL = Path('evaluation/established_sonnet_repair_2_frozen.json')
PAUSE = 'bounded_established_service_check_only'
GRANT = 'established_sonnet_repair_2_authorization_consumed'


def population(path=PROTOCOL):
    protocol = json.loads(path.read_bytes())
    prior, cases = trial.population()
    if identity(prior) != protocol['original_protocol_sha256'] or protocol['acceptance'] != prior['acceptance']:
        raise ValueError('Frozen prior comparison or unchanged criteria mismatch')
    selected = [case for case in cases if case['scope']['id'] in protocol['cases']]
    if {case['scope']['id']: identity(case) for case in selected} != protocol['cases']:
        raise ValueError('Focused source/claim population changed')
    return protocol, selected


class RepairClient:
    def __init__(self, client, protocol):
        self.client, self.protocol = client, protocol

    def json(self, route, stage, prompt, data, schema, validate, *, stage_config=None):
        if route != config()['routes']['sonnet']:
            raise ValueError('Only the established Sonnet route is authorized')
        def diagnosed(value):
            try:
                return validate(value)
            except (ValueError, TypeError, KeyError) as error:
                directory = getattr(self.client, 'diagnostics', None)
                if directory is not None:
                    # Frozen public inputs only. No transport envelope, headers,
                    # credentials or unrestricted source/provider text is retained.
                    safe = {key: value.get(key) for key in ('specific', 'suitable_for_team')
                            if isinstance(value, dict) and type(value.get(key)) is bool}
                    if isinstance(value, dict):
                        for key in ('roles', 'edges'):
                            rows = value.get(key)
                            if isinstance(rows, list):
                                safe[key] = [{k: str(v)[:400] for k, v in row.items()
                                    if k in ('id', 'label', 'quote', 'role_id', 'claim_id', 'coverage')}
                                    for row in rows[:24] if isinstance(row, dict)]
                    atomic_json(directory / (identity([stage, data, safe, type(error).__name__]) + '.json'),
                        {'stage': stage, 'input_hash': identity(data), 'error_type': type(error).__name__,
                         'validator_error': str(error)[:160], 'bounded_response_fields': safe})
                raise
        return self.client.json(route, stage, self.protocol['prompts'][stage], data, schema, diagnosed,
            stage_config=dict(stage_config or config()['stages'][stage], prompt_version=self.protocol['version']))


def contract(protocol, phase):
    return identity({'protocol': protocol, 'phase': phase,
        'team_contract': original.evaluation_contract('teams-sonnet'),
        'harness': original.module_hash(__file__),
        'cov4_classifier': original.module_hash('scripts/subtopic_cov4.py'),
        'cov4_accounting': original.module_hash('tools/run_budgeted_documents.py')})


def authorize(ledger, protocol, phase):
    """The explicit user grant covers these two finite checks, not any new provider stop."""
    with ledger.locked():
        state = ledger.read()
        grants = [event for event in state['events'] if event.get('kind') == GRANT and event.get('phase') == phase]
        if any(event.get('protocol_sha256') != identity(protocol) for event in grants):
            raise ConfigurationFailure('established_service_authorization_identity_mismatch')
        if not os.environ.get('ANTHROPIC_API_KEY'):
            raise ConfigurationFailure('missing_actions_step_credential')
        reason = state['blocked_providers'].get('anthropic')
        if reason not in (None, trial.SCOPED_PAUSE, PAUSE):
            raise ConfigurationFailure('new_provider_stop_requires_resolution')
        state['blocked_providers'].pop('anthropic', None)
        if not grants:
            state['events'].append({'kind': GRANT, 'phase': phase, 'protocol_sha256': identity(protocol),
                'prior_reason': reason, 'scope': 'finite established service check; production pause unchanged'})
        atomic_json(ledger.path, state)


def pause(ledger):
    with ledger.locked():
        state = ledger.read()
        if 'anthropic' not in state['blocked_providers']:
            state['blocked_providers']['anthropic'] = PAUSE
            atomic_json(ledger.path, state)


def team_rows(client, directory, protocol, cases, replay=False):
    expected = contract(protocol, 'teams')
    rows = []
    for case in cases:
        path = directory / ('team-' + identity(case) + '.json')
        retained = json.loads(path.read_bytes()) if path.exists() else None
        if retained and (retained.get('evaluation_contract') != expected or retained.get('case_hash') != identity(case)):
            raise ValueError('Retained focused decision provenance mismatch')
        if replay or retained is None or retained['state'] not in original.SCIENTIFIC_STATES | {'provider_refusal'}:
            if replay and (not retained or retained['state'] not in original.SCIENTIFIC_STATES):
                raise ValueError('Replay requires a completed scientific decision')
            row = original.team_case(RepairClient(client, protocol), 'sonnet', case)
            row.update(case_hash=identity(case), evaluation_contract=expected)
            if replay:
                if row != retained:
                    raise ValueError('Focused decision changed during read-only replay')
            else:
                atomic_json(path, row)
            retained = row
        rows.append(retained)
    return rows


def cov4(ledger, directory, protocol):
    from scripts import subtopic_cov4 as gate
    from tools.run_cov4_ownership import load_candidates
    from tools.run_budgeted_documents import instrument
    selected = [case for case in load_candidates() if case['candidate_id'] in protocol['cov4_cases']]
    if {case['candidate_id']: identity(case) for case in selected} != protocol['cov4_cases']:
        raise ValueError('Frozen Cov4 service check changed')

    class VerifiedSession:
        def post(self, *args, **kwargs):
            response = requests.post(*args, **kwargs)
            if response.status_code == 200 and not compatible_model(gate.MODEL, response.json().get('model')):
                ledger.block('anthropic', 'unexpected_returned_model_identity')
                raise ConfigurationFailure('unexpected_returned_model_identity')
            return response

    bounded = instrument(ledger, directory / 'cov4-cache', gate.classify_fundability)
    rows = []
    for case in selected:
        result = bounded(case, session=VerifiedSession())
        rows.append({'candidate_id': case['candidate_id'], 'case_hash': identity(case), 'result': result,
            'expected_fundability': protocol['cov4_expected'][case['candidate_id']]})
    return {'rows': rows, 'access_contract_passed': all(not row['result'].get('error') and
        row['result']['fundability'] == row['expected_fundability'] for row in rows),
        'limitation': protocol['cov4_limitation'], 'production_topics_published': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['recovery-sonnet', 'cov4-sonnet', 'recovery-replay',
                                         'scope-repair-sonnet', 'scope-repair-replay'])
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    phase = args.phase
    is_replay = phase in ('recovery-replay', 'scope-repair-replay')
    protocol, cases = population(PROTOCOL if phase.startswith('scope-repair-') else
                                Path('evaluation/established_sonnet_repair_frozen.json'))
    directory = args.state / protocol['version']
    directory.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.state / 'ledger.json', original.TASK, config()['budgets_usd']['evaluation'],
                    max_requests=config()['max_requests'])
    expected = contract(protocol, phase)
    marker = directory / (phase + '-completed.json')
    result, complete = None, False
    try:
        if marker.exists():
            retained = json.loads(marker.read_bytes())
            files = {name: identity(json.loads((directory / name).read_bytes())) for name in retained['files']}
            if retained['evaluation_contract'] != expected or files != retained['files']:
                raise ValueError('Completed service check changed; no silent repeat')
            result, complete = retained['result'], True
        elif is_replay:
            before = ledger.path.read_bytes()
            rows = team_rows(trial.ReplayClient(args.state / 'cache'), directory, protocol, cases, replay=True)
            if ledger.path.read_bytes() != before:
                raise ValueError('Read-only replay altered accounting')
            result, complete = {'replayed': len(rows), 'provider_requests': 0}, True
        else:
            authorize(ledger, protocol, phase)
            if phase == 'cov4-sonnet':
                result = cov4(ledger, directory, protocol)
                # An operational failure is retained, not silently retried as a scientific result.
                complete = True
            else:
                client = Client(ledger, args.state / 'cache', deadline=time.monotonic() + 2400)
                client.diagnostics = directory / 'validation-failures'
                rows = team_rows(client, directory, protocol, cases)
                result = trial.metrics(cases, rows) | {'decision': 'pending_independent_source_review',
                    'required_source_checks': protocol['required_source_checks'], 'limitation': protocol['limitation']}
                complete = all(row['state'] in original.SCIENTIFIC_STATES | {'provider_refusal'} for row in rows)
    finally:
        if not is_replay:
            pause(ledger)
        files = {path.name: identity(json.loads(path.read_bytes())) for path in directory.glob('team-*.json')}
        receipt = {'evaluation_contract': expected, 'protocol_sha256': identity(protocol),
            'complete': complete, 'result': result, 'files': files}
        atomic_json(directory / (phase + '-receipt.json'), receipt)
        if complete:
            atomic_json(marker, receipt)
        atomic_json(args.state / 'usage-summary.json', ledger.summary())
    print(json.dumps({'receipt': receipt, 'usage': ledger.summary()}))


if __name__ == '__main__':
    main()
