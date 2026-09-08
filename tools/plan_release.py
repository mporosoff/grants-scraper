"""Select the least expensive release stage at one pinned protected SHA."""
import json
import os
from pathlib import Path
import re
import tempfile

from tools import release_candidate as c
from tools.release_dependencies import snapshot, candidate_groups, changed_groups


def decide(changes, *, event, requested='', verified=False, receipt_current=False, runtime_changed=False):
    if requested in ('generate', 'teams', 'backfill', 'reuse', 'validate', 'publish', 'verify'):
        return requested
    if event == 'schedule' or set(changes) & {'source', 'semantic'}:
        return 'generate'
    if 'teams' in changes:
        return 'teams'
    if runtime_changed:
        return 'reuse'
    if not receipt_current:
        return 'validate' if verified else 'publish'
    return 'noop' if verified else 'publish'


def latest_report(repository, candidate, kind, destination):
    from tools.fetch_release_artifact import fetch
    from tools.offline_ai_checkpoint import api
    for page in range(1, 101):
        rows = json.loads(api(repository, f'actions/artifacts?per_page=100&page={page}'))['artifacts']
        matches = [a for a in rows if re.fullmatch(f'{kind}-{candidate}-[1-9][0-9]*', a['name']) and not a['expired']]
        for artifact in sorted(matches, key=lambda a: a['id'], reverse=True):
            run = str(artifact['workflow_run']['id'])
            target = Path(destination) / str(artifact['id'])
            fetch(repository, run, artifact['name'], target)
            report = target / ('live-verification.json' if kind == 'live' else 'validation.json')
            if kind == 'validation' and not report.exists():
                report = target / 'validation-report.json'
            if report.exists():
                value = c.read_json(report)
                return run, value
            raise ValueError('Latest release evidence is incomplete; do not substitute an older passing receipt')
        if len(rows) < 100:
            return '', None
    raise ValueError('Release evidence history exceeds bounded lookup')


def plan(root, environment, *, receipt=None, live=None):
    root = Path(root)
    sha = c.git(root, 'rev-parse', 'HEAD')
    requested = environment.get('REQUESTED_STAGE', '')
    explicit = requested in ('validate', 'publish', 'verify')
    pointer = c.read_json(root / 'release/candidate-source.json')
    run, candidate = environment.get('CANDIDATE_RUN', ''), environment.get('CANDIDATE_ID', '')
    if not explicit and not run and not candidate:
        run, candidate = pointer['artifact_run'], pointer['candidate_id']
    if requested != 'generate' and (not re.fullmatch(r'[1-9][0-9]*', run) or not re.fullmatch(r'[a-f0-9]{64}', candidate)):
        raise ValueError('An exact candidate run and identity are required; no implicit replacement')
    for field in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'):
        value = environment.get(field, '')
        if value and not re.fullmatch(r'[1-9][0-9]*', value):
            raise ValueError('Invalid ' + field)
    if requested == 'verify' and not all(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN')):
        raise ValueError('Verify requires exact validation and publication evidence')
    manifest = c.read_json(root / 'release/candidate.json')
    if explicit:
        return {'stage': requested, 'release_sha': sha, 'candidate_id': candidate, 'candidate_run': run, 'changes': {},
                'reason': 'Exact named checkpoint; dependency verification must pass without substitution'}
    if manifest['candidate_id'] != candidate:
        raise ValueError('Automatic planning requires the protected candidate pointer')
    if manifest['candidate_id'] != c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'})):
        raise ValueError('Protected candidate manifest is corrupt')
    current = snapshot(root)
    changes = changed_groups(candidate_groups(root, manifest), current)
    # Source seed edits are generation inputs even when code is unchanged.
    for name, expected in manifest['generation_files'].items():
        if c.digest(c.checked_path(root, name).read_bytes()) != expected:
            group = 'teams' if name in c.read_json(root / c.POLICY)['team_outputs'] else 'source'
            changes.setdefault(group, []).append(name)
    runtime = [name for name in changes.get('runtime', [])
               if name not in manifest['files'] or current['runtime']['files'].get(name) != manifest['files'][name]]
    verified = bool(live and live.get('verified') is True and live.get('candidate_id') == candidate)
    receipt_current = bool(receipt and receipt.get('identity') == c.validation_identity(root, manifest)
                           and receipt.get('gates') == {g: 'passed' for g in c.GATES})
    stage = decide(changes, event=environment['GITHUB_EVENT_NAME'], requested=requested,
                   verified=verified, receipt_current=receipt_current, runtime_changed=bool(runtime))
    model = c.read_json(root / 'config/opportunity_team_model.json')
    mode = 'backfill' if stage == 'backfill' else 'maintenance' if model.get('economical_pilot') else 'pilot'
    return {'stage': stage, 'release_sha': sha, 'candidate_id': candidate, 'candidate_run': run,
            'team_mode': mode, 'changes': changes, 'runtime_changes': runtime, 'live_verified': verified,
            'receipt_current': receipt_current, 'reason': 'Dependency fingerprints and retained release evidence'}


def main():
    environment = dict(os.environ)
    pointer = c.read_json(c.ROOT / 'release/candidate-source.json')
    requested = environment.get('REQUESTED_STAGE', '')
    receipt = live = None
    receipt_run = environment.get('RECEIPT_RUN', '')
    if requested not in ('generate', 'validate', 'publish', 'verify'):
        with tempfile.TemporaryDirectory() as directory:
            _, live = latest_report(environment['GITHUB_REPOSITORY'], pointer['candidate_id'], 'live', Path(directory) / 'live')
            receipt_run, receipt = latest_report(environment['GITHUB_REPOSITORY'], pointer['candidate_id'], 'validation', Path(directory) / 'validation')
    result = plan(c.ROOT, environment, receipt=receipt, live=live)
    result['receipt_run'] = receipt_run
    from tools.team_provider import provider_names
    result['openai'] = str('openai' in provider_names()).lower()
    result['anthropic'] = str('anthropic' in provider_names()).lower()
    c.write_json(Path(os.environ['RUNNER_TEMP']) / 'release-plan.json', result)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for key, value in result.items():
            if not isinstance(value, (dict, list)):
                output.write(f'{key}={value}\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write('```json\n' + json.dumps(result, indent=2) + '\n```\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
