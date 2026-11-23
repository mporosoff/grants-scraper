"""Select the protected catalog or service-only input for Worker deployment."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time

from tools import release_attempt_history as history, release_candidate as candidate
from tools.artifact_chronology import latest
from tools.fetch_release_artifact import fetch, repository_artifacts, run_artifacts
from tools.github_read import get
from tools.release_dependencies import candidate_groups, changed_groups, snapshot
from tools.publish_release_candidate import committed_candidate_matches
from tools.verify_release_live import SITE, fetch as fetch_pages, validate_publication


ALERTS_PAGES_FILES = ('match_explorer.html', 'funded_awards.html', 'data/opportunities.js')
SERVICES = ('alerts', 'award-api')


def inherited_jobs(repository, run, completed, *, api, needed=None):
    needed = {'plan', 'verify-live', 'closeout'} if needed is None else set(needed)
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


def latest_receipt_artifact(rows, candidate_id, kind):
    matches = [row for row in rows if re.fullmatch(rf'{kind}-{candidate_id}-[1-9][0-9]*', row['name'])]
    if not matches:
        raise ValueError('Worker handoff is missing retained ' + kind + ' evidence')
    try:
        selected = latest(matches)
    except ValueError as error:
        raise ValueError('Worker handoff has conflicting or unavailable latest ' + kind +
                         ' evidence: ' + str(error)) from None
    if selected.get('expired') is not False:
        raise ValueError('Worker handoff has conflicting or expired latest ' + kind + ' evidence')
    return selected


def authenticate_receipt_producer(repository, artifact, job, *, api):
    run = str(artifact['workflow_run']['id'])
    attempt = int(artifact['name'].rsplit('-', 1)[1])
    current = json.loads(api(f'actions/runs/{run}'))
    completed = history.authenticate_attempt(repository, current, current['run_attempt'], api=api)
    outcome = inherited_jobs(repository, current, completed, api=api, needed={job}).get(job, {})
    if outcome.get('conclusion') != 'success' or outcome.get('run_attempt') != attempt:
        raise ValueError('Worker handoff latest receipt lacks its exact successful producer: ' + job)
    return current['head_sha']


def verify_pages_identity(manifest, publication, *, http=fetch_pages, sleep=time.sleep, attempts=3):
    query = '?handoff=' + candidate.digest(candidate.encoded(publication))
    paths = ('release/candidate.json', 'release/publication.json', 'pages-release-sha.txt')
    for attempt in range(attempts):
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                values = list(executor.map(lambda path: http(SITE + path + query), paths))
            if (json.loads(values[0]) != manifest or json.loads(values[1]) != publication
                    or values[2] != (publication['publication_sha'] + '\n').encode()):
                raise ValueError('Pages identity differs from the retained publication')
            return
        except Exception as error:
            if attempt + 1 == attempts:
                raise ValueError('Worker handoff could not verify the current Pages publication') from error
            sleep(5)


def protected_publication(root, repository, manifest, *, api, download=fetch):
    rows = repository_artifacts(repository, api, candidate=manifest['candidate_id'])
    publication_artifact = latest_receipt_artifact(rows, manifest['candidate_id'], 'publication')
    live_artifact = latest_receipt_artifact(rows, manifest['candidate_id'], 'live')
    producers = [authenticate_receipt_producer(repository, artifact, job, api=api)
                 for artifact, job in ((publication_artifact, 'publish'), (live_artifact, 'verify-live'))]
    with TemporaryDirectory(prefix='worker-publication-') as directory:
        reports = Path(directory)
        for artifact, name in ((publication_artifact, 'publication'), (live_artifact, 'live')):
            download(repository, str(artifact['workflow_run']['id']), artifact['name'], reports / name)
        publication = candidate.read_json(reports / 'publication/publication.json')
        validation = candidate.read_json(reports / 'publication/validation.json')
        validate_publication(manifest, publication, validation)
        if publication != candidate.read_json(reports / 'live/publication.json'):
            raise ValueError('Worker handoff latest publication lacks matching live evidence')
        publication_sha = publication['publication_sha']
        chain = candidate.git(root, 'rev-list', '--first-parent', 'HEAD').splitlines()
        if any(sha not in chain for sha in (publication_sha, *producers)):
            raise ValueError('Worker handoff publication or producer is outside protected main history')
        if not committed_candidate_matches(root, publication_sha, manifest):
            raise ValueError('Worker handoff protected publication differs from the exact candidate bytes')
        verify_live_receipt(root, reports / 'live', manifest, publication_sha)
        verify_pages_identity(manifest, publication)
        return publication_sha


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


def automatic_handoff(root, repository, source, *, api, download=fetch, service='alerts', outputs=None):
    if service not in SERVICES:
        raise ValueError('Unknown Worker release handoff service')
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
    # Candidate history is only a conservative scope hint. Idempotent publication
    # can advance Pages without touching this file; serving authority comes from
    # the exact publication/live receipts below, never this historical commit.
    hint = candidate.git(root, 'log', '--first-parent', '-1', '--format=%H', '--',
                         'release/candidate-source.json')
    if not re.fullmatch(r'[a-f0-9]{40}', hint):
        raise ValueError('Worker handoff requires protected candidate history')
    changed = candidate.git(root, 'diff', '--name-only', '--no-renames', hint, head, '--').splitlines()
    if not any(path.startswith(f'workers/{service}/') for path in changed):
        return 'skip'
    expected = candidate_groups(root, manifest)
    if set(changed_groups(expected, snapshot(root))) - {'validation'}:
        return 'skip'
    publication_sha = protected_publication(root, repository, manifest, api=api, download=download)
    changed = candidate.git(root, 'diff', '--name-only', '--no-renames', publication_sha, head, '--').splitlines()
    if not any(path.startswith(f'workers/{service}/') for path in changed):
        return 'skip'
    candidate.verify_files(root, {name: manifest['files'][name] for name in ALERTS_PAGES_FILES})
    if outputs is not None:
        outputs['pages_publication_sha'] = publication_sha
    return 'worker'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=SERVICES, default='alerts')
    args = parser.parse_args(argv)
    repository = os.environ['GITHUB_REPOSITORY']
    event = candidate.read_json(Path(os.environ['GITHUB_EVENT_PATH']))
    outputs = {}
    route = automatic_handoff(candidate.ROOT, repository, event['workflow_run'],
                              api=lambda path: get(repository, path), service=args.service, outputs=outputs)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'route={route}\n')
        if route == 'worker':
            output.write(f'pages_publication_sha={outputs["pages_publication_sha"]}\n')
    print(f'{args.service} release handoff: {route}')


if __name__ == '__main__':
    main()
