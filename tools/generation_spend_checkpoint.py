"""One durable spend allowance per coordinated Actions generation run."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import zipfile

from tools.offline_ai_checkpoint import api
from tools.offline_ai import atomic_json, config, identity, Ledger
from tools.release_candidate import checked_path
from tools.fetch_release_artifact import artifact_bytes, run_artifacts
from tools.github_job_log_bytes import read_job_log


def latest_checkpoint(artifacts, run, attempt):
    """Native attempts order one allowance; artifact IDs carry no chronology."""
    current = int(attempt)
    if current < 1:
        raise ValueError('Invalid generation spend attempt')
    pattern = re.compile(r'generation-spend-(reservation|state)-' + re.escape(str(run)) + r'-([1-9][0-9]*)')
    records = {'reservation': {}, 'state': {}}
    for artifact in artifacts:
        name = artifact.get('name', '')
        if not name.startswith('generation-spend-'):
            continue
        match = pattern.fullmatch(name)
        if match is None:
            raise ValueError('Invalid generation spend checkpoint identity')
        kind, number = match[1], int(match[2])
        if number >= current or number in records[kind]:
            raise ValueError('Conflicting/future generation spend checkpoint attempt; remaining allowance unavailable')
        records[kind][number] = artifact
    reservations, states = records['reservation'], records['state']
    if not reservations:
        if states:
            raise ValueError('Generation spend state has no reservation; remaining allowance unavailable')
        return None
    latest = max(reservations)
    if not states or max(states) != latest:
        raise ValueError('Incomplete generation spend checkpoint; remaining allowance unavailable')
    selected = states[latest]
    if selected.get('expired') is not False:
        raise ValueError('Incomplete/expired generation spend checkpoint; remaining allowance unavailable')
    return reservations[latest], selected


def prepare(repository, run, attempt, destination, reservation, mode, *, qualification_pilot=False):
    meta = json.loads(api(repository, f'actions/runs/{run}'))
    if meta['path'] != '.github/workflows/refresh-opportunities.yml' or meta['head_branch'] != 'main':
        raise ValueError('Untrusted generation spend origin')
    artifacts = run_artifacts(run, lambda path: api(repository, path), repository=repository)
    checkpoint = latest_checkpoint(artifacts, run, attempt)
    initial_proof = None
    if checkpoint is None and int(attempt) > 1:
        from tools import generation_spend_recovery
        recovered = generation_spend_recovery.restore(repository, run, attempt, destination, mode, meta, artifacts,
            api=lambda path: api(repository, path), qualification_pilot=qualification_pilot,
            log_reader=lambda job: read_job_log(repository, job))
        if not recovered:
            from tools.release_attempt_history import require_preflight_only_before_allocation
            initial_proof = require_preflight_only_before_allocation(repository, meta, int(attempt), artifacts,
                api=lambda path: api(repository, path))
            if str(meta['id']) != str(run):
                raise ValueError('First-allocation history belongs to a different generation run')
    if checkpoint is not None:
        _, selected = checkpoint
        with zipfile.ZipFile(io.BytesIO(artifact_bytes(repository, run, selected, lambda path: api(repository, path)))) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    target = checked_path(destination, item.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
        if not (destination / 'ledger.json').exists():
            raise ValueError('Authoritative generation ledger missing')
    ledger = Ledger(destination / 'ledger.json', destination.name, config()['budgets_usd'][mode], config()['max_requests'])
    if initial_proof is not None:
        atomic_json(destination / 'initial-allocation-provenance.json', initial_proof)
    for provider, evidence in config().get('generation_provider_pauses', {}).items():
        if provider not in ledger.read()['blocked_providers']:
            ledger.block(provider, evidence['reason'])
    if qualification_pilot:
        if mode != 'pilot' or meta.get('event') != 'workflow_dispatch':
            raise ValueError('Qualification pilots require an explicit manual pilot run')
        from tools import offline_ai_checkpoint
        # Restore the newest task checkpoint after the local run checkpoint;
        # a rerun's older embedded task ledger must never roll back later work.
        offline_ai_checkpoint.prepare(repository, destination / 'task', destination / 'task-reservation.json')
        from tools.offline_spend import ROOT, restore_ledger
        from tools.evaluate_offline_ai import TASK
        authorization = json.loads((ROOT / 'config/sonnet_production_qualification.json').read_bytes())['authorization']
        restore_ledger(destination / 'task/ledger.json', TASK, config()['budgets_usd']['evaluation'],
                       config()['max_requests'], authorization)
        atomic_json(destination / 'task-accounting.json', {'task': TASK, 'authorization_id': authorization['id']})
    atomic_json(reservation, {'run_id': str(run), 'attempt': str(attempt), 'mode': mode,
        'maximum_logical_spend_usd': config()['budgets_usd'][mode], 'prior_ledger_hash': identity(ledger.read()),
        **({'first_allocation_proof_sha256': identity(initial_proof)} if initial_proof is not None else {})})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--reservation', type=Path, required=True)
    parser.add_argument('--mode', choices=('pilot', 'maintenance', 'backfill'), required=True)
    args = parser.parse_args()
    prepare(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'],
            args.state, args.reservation, args.mode, qualification_pilot=os.environ.get('QUALIFICATION_PILOT') == 'true')


if __name__ == '__main__':
    main()
