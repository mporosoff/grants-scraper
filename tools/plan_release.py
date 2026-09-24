"""Select the least expensive release stage at one pinned protected SHA."""
import json
import base64
import os
from pathlib import Path
import re
import tempfile

from tools import release_candidate as c
from tools.release_dependencies import snapshot, candidate_groups, changed_groups


def decide(changes, *, event, requested='', verified=False, receipt_current=False, runtime_changed=False, published=False,
           qualification_hold=False, team_generation_ready=True):
    if requested in ('generate', 'teams', 'backfill', 'reuse', 'validate', 'publish', 'verify'):
        return requested
    if qualification_hold and (event == 'schedule' or set(changes) & {'source', 'teams', 'semantic'}):
        return 'noop'
    if event == 'schedule' or set(changes) & {'source', 'semantic'}:
        return 'generate'
    if 'teams' in changes:
        return 'teams' if team_generation_ready else 'noop'
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
        artifact_kind = 'validation' if kind == 'browser' else 'publication' if kind == 'review' else kind
        matches = [a for a in rows if re.fullmatch(f'{artifact_kind}-{candidate}-[1-9][0-9]*', a['name']) and not a['expired']]
        for artifact in sorted(matches, key=lambda a: a['id'], reverse=True):
            run = str(artifact['workflow_run']['id'])
            target = Path(destination) / str(artifact['id'])
            fetch(repository, run, artifact['name'], target)
            report = target / {'live': 'live-verification.json', 'validation': 'validation.json',
                              'publication': 'publication.json', 'browser': 'final-integration.json',
                              'review': 'review-pending.json'}[kind]
            if kind == 'review':
                return run, c.read_json(report) if report.exists() else None
            if kind == 'browser' and not report.exists():
                for receipt_name in ('validation.json', 'validation-report.json'):
                    receipt_path = target / receipt_name
                    if receipt_path.exists():
                        nested = c.read_json(receipt_path).get('final_integration', {})
                        if nested.get('identity'):
                            # A killed explicit browser step may leave only its
                            # pre-dispatch failed/unfinished marker. Do not skip
                            # that marker in favor of an older passing run.
                            return run, nested
                continue  # Ordinary-only validation is not a newer browser result.
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


def pending_publication(root, repository, destination):
    """Reuse an exact compatible review checkpoint before scheduled generation.

    PR files are selectors, never executable inputs or approval. The trusted
    artifact, protected generation ancestry and normal validation remain required.
    """
    from tools.wait_release_review import api
    from tools.fetch_release_artifact import fetch
    prs = api(f'repos/{repository}/pulls?state=open&base=main&per_page=100')
    if len(prs) >= 100:
        raise ValueError('Open publication history exceeds bounded lookup')
    for pr in sorted(prs, key=lambda p: p['number'], reverse=True):
        branch, head = pr['head']['ref'], pr['head']['sha']
        if (pr['user']['login'] != 'github-actions[bot]' or pr['base']['ref'] != 'main'
                or not re.fullmatch(r'automation/release-[a-f0-9]{16}-[1-9][0-9]*-[1-9][0-9]*', branch)
                or (pr['head'].get('repo') or {}).get('full_name') != repository):
            continue
        data = api(f'repos/{repository}/contents/release/candidate-source.json?ref={head}')
        if data.get('encoding') != 'base64' or data.get('size', 10000) > 4096:
            raise ValueError('Invalid publication selector')
        pointer = json.loads(base64.b64decode(data['content'], validate=False))
        run, candidate = str(pointer.get('artifact_run', '')), pointer.get('candidate_id', '')
        if (not re.fullmatch('[1-9][0-9]*', run) or not re.fullmatch('[a-f0-9]{64}', candidate)
                or not branch.startswith('automation/release-' + candidate[:16] + '-')):
            raise ValueError('Invalid publication candidate selector')
        _, pending = latest_report(repository, candidate, 'review', Path(destination) / candidate / 'review')
        if not pending:
            continue
        if (pending.get('schema_version') != 1 or pending.get('status') != 'awaiting_review'
                or pending.get('candidate_id') != candidate or pending.get('artifact_run') != run
                or pending.get('repository') != repository or pending.get('pr_number') != pr['number']
                or pending.get('head_sha') != head or pending.get('production_mutated') is not False):
            raise ValueError('Pending publication does not match its exact PR and artifact')
        bundle = Path(destination) / candidate / 'candidate'
        fetch(repository, run, 'candidate-' + candidate, bundle)
        manifest = c.load(bundle, candidate)
        changes = changed_groups(candidate_groups(root, manifest), snapshot(root))
        if set(changes) - {'validation'}:
            continue  # An actual changed input needs the ordinary dependency plan.
        c.verify_dependencies(root, manifest)
        return {'REQUESTED_STAGE': 'publish', 'CANDIDATE_RUN': run, 'CANDIDATE_ID': candidate}
    return None


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


def plan(root, environment, *, receipt=None, live=None, publication=None, resumed=None, selected=None):
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
    manifest = resumed or selected or c.read_json(root / 'release/candidate.json')
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
    settings_path = root / 'config/offline_ai.json'
    settings = c.read_json(settings_path) if settings_path.exists() else {}
    service = settings.get('production_services', {}).get('teams', {'enabled': True})
    pilot = environment.get('QUALIFICATION_PILOT') == 'true'
    team_ready = bool(service.get('enabled') and (not service.get('pilot_only') or pilot))
    stage = decide(changes, event=environment['GITHUB_EVENT_NAME'], requested=requested,
                   verified=verified, receipt_current=receipt_current, runtime_changed=bool(runtime), published=published,
                   qualification_hold=hold, team_generation_ready=team_ready)
    model = c.read_json(root / 'config/opportunity_team_model.json')
    if pilot and (environment['GITHUB_EVENT_NAME'] != 'workflow_dispatch' or stage not in ('generate', 'teams')):
        raise ValueError('Qualification pilot requires explicit manual team/source generation')
    mode = 'pilot' if pilot else 'backfill' if stage == 'backfill' else 'maintenance'
    return {'stage': stage, 'release_sha': sha, 'candidate_id': candidate, 'candidate_run': run,
            'team_mode': mode, 'changes': changes, 'runtime_changes': runtime, 'live_verified': verified,
            'publication_run': publication['run'] if published else '',
            'publication_attempt': publication['attempt'] if published else '',
            'receipt_current': receipt_current, 'qualification_hold': hold, 'team_generation_ready': team_ready,
            'reason': 'Generation held for bounded service qualification' if hold and stage == 'noop' else
                      'Dependency fingerprints and retained release evidence'}


def main(*, automatic_paid_hold=False):
    environment = dict(os.environ)
    pointer = c.read_json(c.ROOT / 'release/candidate-source.json')
    requested = environment.get('REQUESTED_STAGE', '')
    receipt = live = publication = resumed = selected = result = None
    receipt_run = environment.get('RECEIPT_RUN', '')
    with tempfile.TemporaryDirectory() as directory:
        if (requested in ('', 'auto') and environment.get('GITHUB_RUN_ATTEMPT', '1') == '1'
                and not any(environment.get(k) for k in ('CANDIDATE_RUN', 'CANDIDATE_ID'))):
            pending = pending_publication(c.ROOT, environment['GITHUB_REPOSITORY'], Path(directory) / 'pending')
            if pending:
                environment.update(pending)
                requested = 'publish'
        if requested in ('validate', 'publish'):
            result = plan(c.ROOT, environment)  # Validate the exact named selector first.
            latest_run, receipt = latest_report(environment['GITHUB_REPOSITORY'], result['candidate_id'],
                                                'validation', Path(directory) / 'validation')
            if latest_run:
                # An omitted or older receipt selector cannot erase a required
                # gate recorded by a later attempt for this same candidate.
                receipt_run = latest_run
        if requested not in ('validate', 'publish', 'verify'):
            resumed = completed_attempt(c.ROOT, environment, Path(directory) / 'candidate')
        if not resumed and requested in ('reuse', 'teams', 'backfill') and any(
                environment.get(key) for key in ('CANDIDATE_RUN', 'CANDIDATE_ID')):
            run, candidate_id = (environment.get(key, '') for key in ('CANDIDATE_RUN', 'CANDIDATE_ID'))
            if not re.fullmatch(r'[1-9][0-9]*', run) or not re.fullmatch(r'[a-f0-9]{64}', candidate_id):
                raise ValueError('An exact candidate run and identity are required; no implicit replacement')
            from tools.fetch_release_artifact import fetch
            bundle = Path(directory) / 'selected'
            fetch(environment['GITHUB_REPOSITORY'], run, 'candidate-' + candidate_id, bundle)
            selected = c.load(bundle, candidate_id)
            c.verify_dependencies(c.ROOT, selected, allowed=('teams',) if requested != 'reuse' else ())
        if requested not in ('generate', 'validate', 'publish', 'verify') or resumed:
            candidate = (resumed or selected or pointer)['candidate_id']
            _, live = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'live', Path(directory) / 'live')
            receipt_run, receipt = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'validation', Path(directory) / 'validation')
            _, publication = latest_report(environment['GITHUB_REPOSITORY'], candidate, 'publication', Path(directory) / 'publication')
    if result is None:
        result = plan(c.ROOT, environment, receipt=receipt, live=live, publication=publication, resumed=resumed, selected=selected)
    # A completed finite repair is evidence of past work, not recurring spend
    # authorization. Its caller can retain this hold without changing the
    # ordinary planner's dependency decisions or named manual authorizations.
    paid_stages = ('generate', 'teams', 'backfill')
    if automatic_paid_hold and environment['GITHUB_EVENT_NAME'] in ('push', 'schedule') and result['stage'] in paid_stages:
        result = dict(result, held_stage=result['stage'], stage='noop',
            reason='Finite catalog continuation keeps automatic paid generation and team work held; no new provider work is authorized')
    result['receipt_run'] = receipt_run
    from tools.team_provider import provider_names
    providers = () if automatic_paid_hold and result['stage'] not in paid_stages else provider_names()
    result['openai'] = str('openai' in providers).lower()
    result['anthropic'] = str('anthropic' in providers).lower()
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
