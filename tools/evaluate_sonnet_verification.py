"""One authorized verification-only repair; reuse every earlier completed stage."""
import argparse
import json
import os
from pathlib import Path
import time

from tools import evaluate_established_sonnet as previous
from tools import evaluate_offline_ai as original
from tools import evaluate_team_prompt_repair as trial
from tools.offline_ai import Client, Ledger, ConfigurationFailure, atomic_json, config, identity

PROTOCOL = Path('evaluation/sonnet_verification_repair_frozen.json')
GRANT = 'sonnet_verification_12_request_authorization'


def population():
    protocol = json.loads(PROTOCOL.read_bytes())
    prior, cases = previous.population()
    if (identity(prior) != protocol['prior_protocol_sha256']
            or {c['scope']['id']: identity(c) for c in cases} != protocol['cases']
            or protocol['acceptance'] != prior['acceptance']):
        raise ValueError('Frozen verification repair dependencies changed')
    return protocol, prior, cases


class VerificationLedger(Ledger):
    """The explicit grant changes this evaluation only; production uses Ledger."""
    def __init__(self, path, protocol, *, migrate=False):
        self.path = Path(path)
        self.logical_id = original.TASK
        self.limit = 15_000_000
        self.max_requests = 307
        if (protocol['limit_usd'] != 15 or protocol['max_requests'] != 307
                or protocol['prior_request_count'] != 295 or protocol['authorized_stages'] != ['verification']
                or config()['budgets_usd']['evaluation'] != 15):
            raise ValueError('Verification authorization boundary changed')
        with self.locked():
            state = json.loads(self.path.read_bytes())  # Missing history never creates a fresh allowance.
            if state.get('max_requests') == 300:
                if not migrate or identity(state) != protocol['prior_ledger_sha256']:
                    raise ValueError('The authorized prior ledger is required for the ceiling change')
                state['max_requests'] = self.max_requests
                state['events'].append({'kind': GRANT, 'protocol_sha256': identity(protocol),
                    'prior_ledger_sha256': protocol['prior_ledger_sha256'],
                    'from_max_requests': 300, 'to_max_requests': 307, 'additional_from_used': 12,
                    'scope': 'Sonnet verification only, including retries; $15 and production limits unchanged'})
                atomic_json(self.path, state)
            self.read()

    def read(self):
        state = super().read()
        protocol = json.loads(PROTOCOL.read_bytes())
        grants = [e for e in state['events'] if e.get('kind') == GRANT]
        added = state['requests'][295:]
        if (len(grants) != 1 or grants[0]['protocol_sha256'] != identity(protocol)
                or identity(state['requests'][:295]) != protocol['prior_requests_sha256']
                or len(added) > 12
                or any(r['provider'] != 'anthropic' or r['stage'] != 'verification'
                       or r['model'] != config()['routes']['sonnet']['model'] for r in added)):
            raise ValueError('Verification spend provenance mismatch')
        return state

    def reserve(self, provider, model, stage, key, amount, attempt):
        if (provider != 'anthropic' or stage != 'verification'
                or model != config()['routes']['sonnet']['model']):
            raise ConfigurationFailure('Only the authorized Sonnet verification requests may spend')
        return super().reserve(provider, model, stage, key, amount, attempt)


class StageClient:
    def __init__(self, replay, paid, protocol, prior):
        self.earlier = previous.RepairClient(replay, prior)
        self.verifier = previous.RepairClient(paid, {'version': protocol['version'],
                                                  'prompts': {'verification': protocol['prompt']}})

    def json(self, route, stage, prompt, data, schema, validate, *, stage_config=None):
        if stage not in ('decomposition', 'adjudication', 'verification'):
            raise ValueError('Unauthorized stage')
        target = self.verifier if stage == 'verification' else self.earlier
        return target.json(route, stage, prompt, data, schema, validate, stage_config=stage_config)


def retained_rows(state, protocol, prior, cases):
    """Establish the exact earlier-stage inputs with transport-forbidden replay."""
    replay = previous.RepairClient(trial.ReplayClient(state / 'cache'), prior)
    rows = []
    for case in cases:
        row = json.loads((state / prior['version'] / ('team-' + identity(case) + '.json')).read_bytes())
        if identity(row) != protocol['prior_results'][case['scope']['id']]:
            raise ValueError('Retained scientific evidence changed')
        checked = original.team_case(replay, 'sonnet', case)
        checked.update(case_hash=identity(case), evaluation_contract=protocol['prior_team_contract'])
        if checked != row:
            raise ValueError('Earlier completed stages cannot be reproduced without transport')
        rows.append(row)
    if sum('verification' in row['stages'] for row in rows) != 6:
        raise ValueError('The authorized six verifier inputs changed')
    return rows


def run(state, *, replay=False):
    protocol, prior, cases = population()
    # Population/history inspection remains possible after the shared transport
    # evolves. Executing this historical harness still requires its exact code.
    if previous.contract(prior, 'teams') != protocol['prior_team_contract']:
        raise ValueError('Historical verification runtime changed; use the qualified active route')
    old = retained_rows(state, protocol, prior, cases)
    # All provenance is established before modifying accounting or contacting a provider.
    ledger = VerificationLedger(state / 'ledger.json', protocol, migrate=not replay)
    directory = state / protocol['version']
    directory.mkdir(parents=True, exist_ok=True)
    expected = identity({'protocol': protocol, 'harness': original.module_hash(__file__),
                         'prior_contract': protocol['prior_team_contract']})
    before = ledger.path.read_bytes()
    rows, complete = [], False
    client = trial.ReplayClient(state / 'cache') if replay else Client(
        ledger, state / 'cache', deadline=time.monotonic() + 2400)
    client.diagnostics = directory / 'validation-failures'
    adapter = StageClient(trial.ReplayClient(state / 'cache'), client, protocol, prior)
    try:
        if not replay:
            if not os.environ.get('ANTHROPIC_API_KEY'):
                raise ConfigurationFailure('missing_actions_step_credential')
            previous.authorize(ledger, protocol, 'verification-sonnet')
        for case, old_row in zip(cases, old):
            path = directory / ('team-' + identity(case) + '.json')
            saved = json.loads(path.read_bytes()) if path.exists() else None
            if saved and (saved.get('evaluation_contract') != expected or saved.get('case_hash') != identity(case)):
                raise ValueError('Retained verification repair identity mismatch')
            if saved and not replay and saved['state'] in original.SCIENTIFIC_STATES | {'provider_refusal'}:
                row = saved
            else:
                if replay and (not saved or saved['state'] not in original.SCIENTIFIC_STATES):
                    raise ValueError('Replay requires a completed verification repair')
                row = original.team_case(adapter, 'sonnet', case)
                row.update(case_hash=identity(case), evaluation_contract=expected)
                if any(row['stages'].get(s) != old_row['stages'].get(s) for s in ('decomposition', 'adjudication')):
                    raise ValueError('An earlier stage changed during verification-only repair')
                if replay:
                    if row != saved:
                        raise ValueError('Verification repair changed during read-only replay')
                else:
                    atomic_json(path, row)
            rows.append(row)
        complete = all(r['state'] in original.SCIENTIFIC_STATES for r in rows)
    finally:
        if not replay:
            previous.pause(ledger)
        elif ledger.path.read_bytes() != before:
            raise ValueError('Read-only replay modified the spending ledger')
        receipt = {'evaluation_contract': expected, 'protocol_sha256': identity(protocol),
            'complete': complete, 'result': trial.metrics(cases, rows) if len(rows) == len(cases) else None,
            'decision': 'pending_independent_source_review', 'limitation': protocol['limitation'],
            'files': {p.name: identity(json.loads(p.read_bytes())) for p in directory.glob('team-*.json')},
            'usage': ledger.summary()}
        atomic_json(directory / ('replay-receipt.json' if replay else 'verification-receipt.json'), receipt)
        atomic_json(state / 'usage-summary.json', ledger.summary())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['verification-sonnet', 'verification-replay'])
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.state, replay=args.phase == 'verification-replay')))


if __name__ == '__main__':
    main()
