"""Select the protected catalog or Worker-only input for Alerts deployment."""

import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from tools import release_attempt_history as history, release_candidate as candidate
from tools.fetch_release_artifact import fetch, run_artifacts
from tools.github_read import get
from tools.release_dependencies import candidate_groups, changed_groups, snapshot
from tools.verify_release_live import validate_publication


ALERTS_PAGES_FILES = ('match_explorer.html', 'funded_awards.html', 'data/opportunities.js')


def inherited_jobs(repository, run, completed, *, api):
    needed = {'plan', 'verify-live', 'closeout'}
    outcomes = {}
    for attempt in range(completed['run_attempt'], 0, -1):
        if attempt != completed['run_attempt']:
            completed_attempt = history.authenticate_attempt(repository, run, attempt, api=api)
        else:
            completed_attempt = completed
        jobs = history._jobs(run, completed_attempt, api=api, full=False)
        # Failed-job retries omit successful prerequisites. An explicit outcome,
        # including a failure or a skip, supersedes all older evidence for that job.
        outcomes.update({name: jobs[name] for name in needed - outcomes.keys() if name in jobs})
        if needed == outcomes.keys():
            break
    return outcomes


def verify_live_receipt(root, reports, manifest, head):
    publication = candidate.read_json(reports / 'publication.json')
    validation = candidate.read_json(reports / 'validation.json')
    validate_publication(manifest, publication, validation)
    verified = candidate.read_json(reports / 'live-verification.json')
    if (verified.get('candidate_id') != manifest['candidate_id']
            or verified.get('publication_sha') != publication['publication_sha']
            or verified.get('publication_receipt_sha256') != candidate.digest(candidate.encoded(publication))
            or verified.get('verified') is not True or verified.get('differences') != []
            or verified.get('asset_verification') != 'success' or verified.get('provider_smoke') != 'success'
            or (verified.get('worker_provenance') or {}).get('verified') is not True
            or verified.get('live_release_identity') != manifest['release_identity']):
        raise ValueError('Alerts handoff did not receive exact successful live verification')
    if publication['publication_sha'] != head:
        return False  # A later protected commit has its own immutable release run.
    candidate.verify_files(root, {name: manifest['files'][name] for name in ALERTS_PAGES_FILES})
    return True


def automatic_handoff(root, repository, source, *, api, download=fetch):
    run, attempt = source.get('id'), source.get('run_attempt')
    if (type(run) is not int or run <= 0 or type(attempt) is not int or attempt <= 0
            or source.get('head_branch') != 'main'
            or (source.get('head_repository') or {}).get('full_name') != repository
            or source.get('conclusion') != 'success'):
        raise ValueError('Alerts handoff requires a successful same-repository main release attempt')
    current = json.loads(api(f'actions/runs/{run}'))
    completed = history.authenticate_attempt(repository, current, attempt, api=api)
    if (completed['conclusion'] != 'success' or completed['head_sha'] != source.get('head_sha')
            or completed['event'] != source.get('event')):
        raise ValueError('Alerts handoff recorded a different release attempt')
    if current['run_attempt'] != attempt:
        return 'skip'  # A newer retry now owns the handoff for this workflow run.
    jobs = inherited_jobs(repository, current, completed, api=api)
    live = jobs.get('verify-live', {})
    live_verified = live.get('conclusion') == 'success'
    head = candidate.git(root, 'rev-parse', 'HEAD')
    direct_push = (completed['event'] == 'push' and completed['head_sha'] == head
                   and live.get('conclusion') == 'skipped'
                   and all((jobs.get(name) or {}).get('conclusion') == 'success' for name in ('plan', 'closeout')))
    if not live_verified and not direct_push:
        return 'skip'

    manifest = candidate.read_json(root / 'release/candidate.json')
    if live_verified:
        producer = live['run_attempt']
        archives = [entry['name'] for entry in run_artifacts(run, api)
                    if re.fullmatch(rf'live-[a-f0-9]{{64}}-{producer}', entry['name'])]
        if len(archives) != 1:
            raise ValueError('Alerts handoff requires the exact attempt’s live verification artifact')
        name = f'live-{manifest["candidate_id"]}-{producer}'
        if archives[0] != name:
            return 'skip'  # A newer publication already superseded this completion.
        with TemporaryDirectory(prefix='alerts-release-') as directory:
            reports = Path(directory)
            download(repository, run, name, reports)
            return 'catalog' if verify_live_receipt(root, reports, manifest, head) else 'skip'

    # A service-only push can deploy while Pages keeps serving the same package.
    # Classifying changed Worker bytes against the serving version remains with
    # the existing deploy job, followed by its ordinary Pages and smoke gates.
    publication_sha = candidate.git(root, 'log', '--first-parent', '-1', '--format=%H', '--',
                                    'release/candidate-source.json')
    if not re.fullmatch(r'[a-f0-9]{40}', publication_sha):
        raise ValueError('Alerts handoff requires a protected catalog publication')
    changed = candidate.git(root, 'diff', '--name-only', '--no-renames', publication_sha, head, '--').splitlines()
    if not any(path.startswith('workers/alerts/') for path in changed):
        return 'skip'
    expected = candidate_groups(root, manifest)
    if set(changed_groups(expected, snapshot(root))) - {'validation'}:
        return 'skip'
    candidate.verify_files(root, {name: manifest['files'][name] for name in ALERTS_PAGES_FILES})
    return 'worker'


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    event = candidate.read_json(Path(os.environ['GITHUB_EVENT_PATH']))
    route = automatic_handoff(candidate.ROOT, repository, event['workflow_run'],
                              api=lambda path: get(repository, path))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'route={route}\n')
    print(f'Alerts release handoff: {route}')


if __name__ == '__main__':
    main()
