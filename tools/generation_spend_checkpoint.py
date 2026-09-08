"""One durable spend allowance per coordinated Actions generation run."""
import argparse
import io
import json
import os
from pathlib import Path
import zipfile

from tools.offline_ai_checkpoint import api
from tools.offline_ai import atomic_json, config, identity, Ledger
from tools.release_candidate import checked_path


def prepare(repository, run, attempt, destination, reservation, mode):
    meta = json.loads(api(repository, f'actions/runs/{run}'))
    if meta['path'] != '.github/workflows/refresh-opportunities.yml' or meta['head_branch'] != 'main':
        raise ValueError('Untrusted generation spend origin')
    artifacts = json.loads(api(repository, f'actions/runs/{run}/artifacts?per_page=100'))['artifacts']
    reservations = [a for a in artifacts if a['name'].startswith(f'generation-spend-reservation-{run}-')]
    if not reservations and int(attempt) > 1:
        raise ValueError('Prior attempt spend evidence unavailable; remaining budget cannot be reset')
    if reservations:
        prior = max(reservations, key=lambda a: a['id'])
        name = prior['name'].replace('-reservation-', '-state-')
        matches = [a for a in artifacts if a['name'] == name and not a['expired']]
        if len(matches) != 1:
            raise ValueError('Incomplete/expired generation spend checkpoint; remaining allowance unavailable')
        with zipfile.ZipFile(io.BytesIO(api(repository, f"actions/artifacts/{matches[0]['id']}/zip"))) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    target = checked_path(destination, item.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
        if not (destination / 'ledger.json').exists():
            raise ValueError('Authoritative generation ledger missing')
    ledger = Ledger(destination / 'ledger.json', destination.name, config()['budgets_usd'][mode], config()['max_requests'])
    for provider, evidence in config().get('generation_provider_pauses', {}).items():
        ledger.block(provider, evidence['reason'])
    atomic_json(reservation, {'run_id': str(run), 'attempt': str(attempt), 'mode': mode,
        'maximum_logical_spend_usd': config()['budgets_usd'][mode], 'prior_ledger_hash': identity(ledger.read())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--reservation', type=Path, required=True)
    parser.add_argument('--mode', choices=('pilot', 'maintenance', 'backfill'), required=True)
    args = parser.parse_args()
    prepare(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'],
            args.state, args.reservation, args.mode)


if __name__ == '__main__':
    main()
