"""One separately frozen team-prompt trial; shared existing spend, no production mutation."""
import argparse
import json
import os
from pathlib import Path
import time

from tools import evaluate_offline_ai as original
from tools.offline_ai import Client, Ledger, ConfigurationFailure, atomic_json, config, identity

PROTOCOL = Path('evaluation/offline_team_prompt_repair_frozen.json')
GRANT_EVENT = 'team_prompt_repair_2_baseline_authorization_consumed'
SCOPED_PAUSE = 'bounded_baseline_scope_only'


def population():
    protocol = json.loads(PROTOCOL.read_bytes())
    frozen = json.loads(Path('evaluation/offline_team_frozen.json').read_bytes())
    from scripts import build_opportunity_teams as teams
    if (identity(frozen) != protocol['original_frozen_sha256']
            or identity(teams.DECOMPOSE) != protocol['baseline_decomposition_sha256']
            or protocol['acceptance'] != frozen['acceptance']):
        raise ValueError('Frozen reference, baseline prompt or acceptance criteria changed')
    by_id = {case['scope']['id']: case for case in frozen['cases']}
    development = []
    for key, expected in protocol['development_case_hashes'].items():
        case = by_id[key]
        if case['holdout'] or identity(case) != expected:
            raise ValueError('Development input identity changed')
        development.append(case)
    holdouts = protocol['fresh_holdouts']
    if (len(development) != 18 or len(holdouts) != 6 or protocol['case_count'] != 24
            or protocol['holdout_count'] != 6 or any(not case['holdout'] for case in holdouts)
            or set(by_id) & {case['scope']['id'] for case in holdouts}
            or len({case['scope']['id'] for case in holdouts}) != 6):
        raise ValueError('Fresh holdout population mismatch')
    return protocol, development + holdouts


class TrialClient:
    """Change only the candidate's request prompt; retain production validators."""
    def __init__(self, client, protocol, route):
        self.client, self.protocol, self.route = client, protocol, route

    def json(self, route, stage, prompt, data, schema, validate, *, stage_config=None):
        if self.route == 'luna' and stage == 'decomposition':
            prompt = self.protocol['candidate_decomposition_prompt']
            stage_config = dict(stage_config or config()['stages'][stage],
                                prompt_version=self.protocol['candidate_prompt_version'])
        return self.client.json(route, stage, prompt, data, schema, validate, stage_config=stage_config)


def contract(protocol, route):
    return identity({'protocol': protocol, 'route': route,
        'existing_team_contract': original.evaluation_contract('teams-' + route),
        'candidate_adapter': original.function_hash(TrialClient.json)})


def authorize_baseline(ledger, protocol, authorized):
    """Consume the user's evaluation-only grant once; a new provider stop stays stopped."""
    with ledger.locked():
        state = ledger.read()
        grants = [event for event in state['events'] if event.get('kind') == GRANT_EVENT]
        if grants:
            if any(event['protocol_sha256'] != identity(protocol) for event in grants):
                raise ConfigurationFailure('baseline_authorization_protocol_mismatch')
            # Resume only this same finite baseline. A new provider failure is
            # never cleared, even when the dispatch flag is supplied again.
            if state['blocked_providers'].get('anthropic') == SCOPED_PAUSE:
                del state['blocked_providers']['anthropic']
                atomic_json(ledger.path, state)
            return
        if not authorized:
            raise ConfigurationFailure('explicit_bounded_baseline_authorization_required')
        if not os.environ.get('ANTHROPIC_API_KEY'):
            raise ConfigurationFailure('missing_actions_step_credential')
        reason = state['blocked_providers'].get('anthropic')
        if reason not in (None, 'anthropic_configuration_http_400', 'insufficient_credit'):
            raise ConfigurationFailure('baseline_authorization_does_not_clear_this_provider_stop')
        state['blocked_providers'].pop('anthropic', None)
        state['events'].append({'kind': GRANT_EVENT, 'provider': 'anthropic',
            'prior_reason': reason, 'protocol_sha256': identity(protocol),
            'scope': 'one evaluation baseline; production pause unchanged'})
        atomic_json(ledger.path, state)


def pause_outside_baseline(ledger):
    with ledger.locked():
        state = ledger.read()
        if (any(event.get('kind') == GRANT_EVENT for event in state['events'])
                and 'anthropic' not in state['blocked_providers']):
            state['blocked_providers']['anthropic'] = SCOPED_PAUSE
            atomic_json(ledger.path, state)


def assess(client, directory, protocol, route, case):
    path = directory / f'{route}-{identity(case)}.json'
    expected = contract(protocol, route)
    if path.exists():
        retained = json.loads(path.read_bytes())
        if (retained.get('case_hash') != identity(case) or retained.get('route') != route
                or retained.get('evaluation_contract') != expected):
            raise ValueError('Prompt-repair checkpoint mismatch; preserve historical evidence')
        if retained['state'] in original.SCIENTIFIC_STATES | {'provider_refusal'}:
            return retained
    row = original.team_case(TrialClient(client, protocol, route), route, case)
    row.update(case_hash=identity(case), route=route, evaluation_contract=expected)
    atomic_json(path, row)
    return row


def metrics(cases, rows):
    accepted = {'proposed', 'insufficient_evidence'}
    legitimate = [index for index, case in enumerate(cases)
                  if case['annotations']['expected_scope'] == 'bounded_research']
    completed = sum(row['state'] in original.SCIENTIFIC_STATES for row in rows)
    correct = sum(row['state'] in original.SCIENTIFIC_STATES and
                  (row['state'] in accepted) == (case['annotations']['expected_scope'] == 'bounded_research')
                  for case, row in zip(cases, rows))
    return {'total': len(cases), 'completed': completed, 'scope_correct': correct,
        'scope_accuracy': correct / len(cases), 'legitimate_scopes': len(legitimate),
        'legitimate_accepted': sum(rows[index]['state'] in accepted for index in legitimate),
        'legitimate_acceptance': sum(rows[index]['state'] in accepted for index in legitimate) / len(legitimate),
        'proposed': sum(row['state'] == 'proposed' for row in rows)}


def replay(client, directory, protocol, cases):
    before = len(client.ledger.read()['requests'])
    def forbidden(*args, **kwargs):
        raise AssertionError('Prompt-repair replay attempted a provider request')
    client.post = forbidden
    count = 0
    for route in ('sonnet', 'luna'):
        for case in cases:
            path = directory / f'{route}-{identity(case)}.json'
            if not path.exists():
                continue
            retained = json.loads(path.read_bytes())
            if retained['evaluation_contract'] != contract(protocol, route):
                raise ValueError('Replay contract mismatch')
            if retained['state'] not in original.SCIENTIFIC_STATES:
                continue
            value = original.team_case(TrialClient(client, protocol, route), route, case)
            if any(value[key] != retained[key] for key in ('state', 'stages')):
                raise ValueError('Completed prompt-repair decision changed during replay')
            count += 1
    return {'completed_scopes_replayed': count,
            'new_provider_requests': len(client.ledger.read()['requests']) - before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['round2-sonnet', 'round2-luna', 'round2-stability', 'round2-replay'])
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    protocol, cases = population()
    ledger = Ledger(args.state / 'ledger.json', original.TASK, config()['budgets_usd']['evaluation'],
                    max_requests=config()['max_requests'])
    directory = args.state / protocol['version']
    directory.mkdir(parents=True, exist_ok=True)
    phase = args.phase.removeprefix('round2-')
    route = 'sonnet' if phase == 'sonnet' else 'luna'
    expected = identity({'protocol': protocol, 'phase': phase, 'contract': contract(protocol, route),
                         'metrics_version': original.function_hash(metrics)})
    marker = directory / (phase + '-completed.json')
    client = Client(ledger, args.state / 'cache', deadline=time.monotonic() + 2400)
    result, complete = None, False
    try:
        if marker.exists():
            retained = json.loads(marker.read_bytes())
            if retained.get('evaluation_contract') != expected:
                raise ValueError('Completed trial contract changed; no silent rerun')
            result, complete = retained['result'], True
        elif phase == 'replay':
            result, complete = replay(client, directory, protocol, cases), True
        else:
            if phase == 'sonnet':
                authorize_baseline(ledger, protocol, os.environ.get('AUTHORIZE_ANTHROPIC_BASELINE') == 'true')
            selected, output_directory = cases, directory
            if phase == 'stability':
                selected = [case for case in cases if case['scope']['id'] in protocol['stability_scope_ids']]
                if len(selected) != 2 or protocol['stability_route'] != 'luna':
                    raise ValueError('Predeclared candidate-only stability population changed')
                output_directory = directory / 'stability-results'
                client = Client(ledger, directory / 'stability-cache', deadline=client.deadline)
            rows = [assess(client, output_directory, protocol, route, case) for case in selected]
            result = metrics(selected, rows) | {'route': route, 'decision': 'pending_independent_source_review'}
            held = [(case, row) for case, row in zip(selected, rows) if case['holdout']]
            if held:
                result['holdout'] = metrics([p[0] for p in held], [p[1] for p in held])
            complete = result['completed'] == result['total']
    finally:
        if phase == 'sonnet':
            pause_outside_baseline(ledger)
        receipt = {'evaluation_contract': expected, 'protocol_sha256': identity(protocol),
                   'complete': complete, 'result': result}
        atomic_json(directory / (phase + '-receipt.json'), receipt)
        if complete:
            atomic_json(marker, receipt)
        atomic_json(args.state / 'usage-summary.json', ledger.summary())
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
                output.write('\n```json\n' + json.dumps({'trial': receipt, 'usage': ledger.summary()}, indent=2) + '\n```\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
