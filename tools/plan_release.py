"""Select the least expensive release stage at one pinned protected SHA."""
import json
import os
from pathlib import Path
import re
import tempfile

from tools import release_candidate as c
from tools.release_dependencies import snapshot, candidate_groups, changed_groups


def decide(changes, *, event, requested='', verified=False, receipt_current=False, runtime_changed=False, published=False,
           qualification_hold=False):
    if requested in ('generate', 'teams', 'backfill', 'reuse', 'validate', 'publish', 'verify'):
        return requested
    if qualification_hold and (event == 'schedule' or set(changes) & {'source', 'teams', 'semantic'}):
        return 'noop'
    if event == 'schedule' or set(changes) & {'source', 'semantic'}:
        return 'generate'
    if 'teams' in changes:
        return 'teams'
    if runtime_changed:
        return 'reuse'
    if published and not verified:
        return 'verify'
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
            report = target / {'live': 'live-verification.json', 'validation': 'validation.json', 'publication': 'publication.json'}[kind]
            if kind == 'publication':
                if not report.exists():
                    return run, None  # Pre-publication failure is not a Pages checkpoint.
                attempt = artifact['name'].rsplit('-', 1)[1]
                jobs = []
                for job_page in range(1, 101):
                    batch = json.loads(api(repository, f'actions/runs/{run}/attempts/{attempt}/jobs?per_page=100&page={job_page}'))['jobs']
                    jobs.extend(batch)
                    if len(batch) < 100:
                        break
                else:
                    raise ValueError('Pages evidence pagination exceeds bounded lookup')
                pages = [job for job in jobs if job['name'] == 'pages / deploy']
                return run, {'receipt': c.read_json(report), 'validation': c.read_json(target / 'validation.json'),
                             'run': run, 'attempt': attempt,
                             'pages_complete': len(pages) == 1 and pages[0]['conclusion'] == 'success'}
            if kind == 'validation' and not report.exists():
                report = target / 'validation-report.json'
            if report.exists():
                value = c.read_json(report)
                return run, value
            raise ValueError('Latest release evidence is incomplete; do not substitute an older passing receipt')
        if len(rows) < 100:
            return '', None
    raise ValueError('Release evidence history exceeds bounded lookup')


def publication_ready(manifest, publication):
    if not publication or not publication.get('pages_complete'):
        return False
    from tools.verify_release_live import validate_publication
    validate_publication(manifest, publication['receipt'], publication['validation'])
    return True


def completed_attempt(root, environment, destination):
    """Resume this logical run's exact candidate before considering another stage."""
    if int(environment.get('GITHUB_RUN_ATTEMPT', '1')) <= 1:
        return None
    from tools.offline_ai_checkpoint import api
    from tools.fetch_release_artifact import fetch
    repo, run = environment['GITHUB_REPOSITORY'], environment['GITHUB_RUN_ID']
    artifacts = json.loads(api(repo, f'actions/runs/{run}/artifacts?per_page=100'))['artifacts']
    candidates = [a for a in artifacts if a['name'].startswith('candidate-')]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError('Ambiguous logical-run candidate; select exact evidence without regeneration')
    fetch(repo, run, candidates[0]['name'], destination)
    manifest = c.load(destination, candidates[0]['name'].removeprefix('candidate-'))
    c.verify_dependencies(root, manifest)
    return manifest


def plan(root, environment, *, receipt=None, live=None, publication=None, resumed=None):
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
    manifest = resumed or c.read_json(root / 'release/candidate.json')
    if explicit:
        return {'stage': requested, 'release_sha': sha, 'candidate_id': candidate, 'candidate_run': run, 'changes': {},
                'publication_run': environment.get('PUBLICATION_RUN', ''),
                'publication_attempt': environment.get('PUBLICATION_ATTEMPT', ''),
                'reason': 'Exact named checkpoint; dependency verification must pass without substitution'}
    published = publication_ready(manifest, publication)
    if resumed:
        return {'stage': 'verify' if published else 'publish', 'release_sha': sha,
                'candidate_id': manifest['candidate_id'], 'candidate_run': environment['GITHUB_RUN_ID'],
                'publication_run': publication['run'] if published else '',
                'publication_attempt': publication['attempt'] if published else '', 'changes': {},
                'reason': 'Resume the exact persisted logical-run candidate at its latest completed checkpoint'}
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
    qualification_path = root / 'config/sonnet_production_qualification.json'
    qualification = c.read_json(qualification_path) if qualification_path.exists() else {}
    hold = qualification.get('automatic_generation') == 'hold'
    stage = decide(changes, event=environment['GITHUB_EVENT_NAME'], requested=requested,
                   verified=verified, receipt_current=receipt_current, runtime_changed=bool(runtime), published=published,
                   qualification_hold=hold)
    model = c.read_json(root / 'config/opportunity_team_model.json')
    pilot = environment.get('QUALIFICATION_PILOT') == 'true'
    if pilot and (environment['GITHUB_EVENT_NAME'] != 'workflow_dispatch' or stage not in ('generate', 'teams')):
        raise ValueError('Qualification pilot requires explicit manual team/source generation')
    mode = 'pilot' if pilot else 'backfill' if stage == 'backfill' else 'maintenance'
    return {'stage': stage, 'release_sha': sha, 'candidate_id': candidate, 'candidate_run': run,
            'team_mode': mode, 'changes': changes, 'runtime_changes': runtime, 'live_verified': verified,
            'publication_run': publication['run'] if published else '',
            'publication_attempt': publication['attempt'] if published else '',
            'receipt_current': receipt_current, 'qualification_hold': hold,
            'reason': 'Generation held for bounded service qualification' if hold and stage == 'noop' else
                      'Dependency fingerprints and retained release evidence'}


def main():
    environment = dict(os.environ)
    pointer = c.read_json(c.ROOT / 'release/candidate-source.json')
    requested = environment.get('REQUESTED_STAGE', '')
    receipt = live = publication = resumed = None
    receipt_run = environment.get('RECEIPT_RUN', '')
    with tempfile.TemporaryDirectory() as directory:
        if requested not in ('validate', 'publish', 'verify'):
            resumed = completed_attempt(c.ROOT, environment, Path(directory) / 'candidate')
        if requested not in ('generate', 'validate', 'publish', 'verify') or resumed:
            candidate = resumed['candidate_id'] if resumed else pointer['candidate_id']
            _, live = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'live', Path(directory) / 'live')
            receipt_run, receipt = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'validation', Path(directory) / 'validation')
            _, publication = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'publication', Path(directory) / 'publication')
    result = plan(c.ROOT, environment, receipt=receipt, live=live, publication=publication, resumed=resumed)
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
