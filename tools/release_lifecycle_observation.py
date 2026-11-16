"""Summarize an authenticated release attempt for observation only."""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import zipfile

from tools import release_candidate as candidate
from tools import release_checkpoint_archive as archive


SHA = r'[a-f0-9]{40}'
DIGEST = r'[a-f0-9]{64}'
NUMBER = r'[1-9][0-9]*'
MAX_REPORT_BYTES = 4 * 1024 * 1024
ARTIFACT = re.compile(
    rf'(?:release-plan-{NUMBER}|candidate-{DIGEST}|'
    rf'(?:validation|publication|live)-{DIGEST}-{NUMBER}|'
    rf'generation-spend-(?:reservation|state)-{NUMBER}-{NUMBER}|'
    rf'(?:offline-ai-[A-Za-z0-9_.-]+|program-area-vectors-{DIGEST})-'
    rf'(?:reservation|state)-{NUMBER}-{NUMBER})')
STAGES = frozenset({
    'plan', 'sam-preflight', 'generate', 'assemble', 'catalog-reconcile',
    'catalog-correction', 'program-area-revalidation', 'catalog-source-recovery',
    'catalog-access-correction', 'catalog-identity-correction',
    'catalog-url-correction', 'candidate', 'validate', 'publish',
    'pages', 'verify-live', 'closeout',
})
PLAN_STAGES = STAGES | {'noop', 'teams', 'backfill', 'reuse', 'verify', 'catalog-projection',
                       'submission-revalidation', 'document-fact-revalidation', 'primary-document-revalidation'}
DAILY_STATES = {'already_current', 'due', 'held', 'recovering'}


def binding(value, pattern, label):
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not re.fullmatch(pattern, str(value)):
        raise ValueError(f'Invalid lifecycle {label}')
    return str(value)


def members(directory, artifact, names):
    """Read bounded, named reports without extracting an original archive."""
    path = directory / 'artifacts' / f"{artifact['id']}.zip"
    with path.open('rb') as binary:
        if hashlib.file_digest(binary, 'sha256').hexdigest() != artifact['sha256']:
            raise ValueError('Lifecycle evidence ZIP differs from its retained digest')
        binary.seek(0)
        with zipfile.ZipFile(binary) as bundle:
            reports = {}
            for member in bundle.infolist():
                if member.filename not in names:
                    continue
                if member.filename in reports or member.file_size > MAX_REPORT_BYTES:
                    raise ValueError('Lifecycle evidence member is duplicate or oversized')
                report = archive._decode(bundle.read(member))
                if not isinstance(report, dict):
                    raise ValueError('Invalid lifecycle evidence member')
                reports[member.filename] = report
            return reports


def observe_jobs(read, source):
    run, attempt = source['run_id'], source['run_attempt']
    observed, identifiers = {}, set()
    jobs = archive._pages(read, f'actions/runs/{run}/attempts/{attempt}/jobs', 'jobs', require_total=True)
    for job in jobs:
        name, outcome = job.get('name'), job.get('conclusion')
        if name == 'pages / deploy':
            name = 'pages'
        identifier = archive._positive(job.get('id'))
        if (name not in STAGES or name in observed or identifier in identifiers
                or str(job.get('run_id')) != run or job.get('run_attempt') != attempt
                or job.get('head_branch') != source['head_branch']
                or job.get('head_sha') != source['head_sha'] or job.get('status') != 'completed'
                or not isinstance(outcome, str) or outcome not in archive.TERMINAL_CONCLUSIONS):
            raise ValueError('Untrusted lifecycle job metadata')
        identifiers.add(identifier)
        observed[name] = {'job_id': identifier, 'conclusion': outcome}
    return observed


def observe_artifacts(directory, source, conclusion, inventory):
    if not inventory:
        if (directory / 'manifest.json').exists():
            raise ValueError('Lifecycle archive inventory unexpectedly disappeared')
        return []
    captured = archive._decode((directory / 'manifest.json').read_bytes())
    if (captured.get('source') != source or captured.get('source_conclusion') != conclusion
            or captured.get('artifact_name') != archive.artifact_name(
                source['run_id'], source['run_attempt'], inventory)):
        raise ValueError('Lifecycle archive does not match native attempt')
    archived = [item['metadata'] for item in captured['artifacts']]
    if sorted(archived, key=lambda item: item['id']) != sorted(inventory, key=lambda item: item['id']):
        raise ValueError('Lifecycle archive does not match native artifact inventory')
    result, labels = [], set()
    for item in archived:
        identifier = archive._artifact(item, source)
        if ARTIFACT.fullmatch(item['name']):
            if item['name'] in labels:
                raise ValueError('Conflicting lifecycle artifact labels')
            labels.add(item['name'])
            result.append({'id': identifier, 'name': item['name'], 'sha256': item['digest'][7:]})
    return result


def observe_plan(value):
    stage = value.get('stage')
    if not isinstance(stage, str) or stage not in PLAN_STAGES:
        raise ValueError('Unknown observed release plan stage')
    observed = {'stage': stage, 'release_sha': binding(value.get('release_sha'), SHA, 'plan SHA')}
    if value.get('daily_status') in DAILY_STATES:
        observed['daily_status'] = value['daily_status']
    if value.get('held_stage') in PLAN_STAGES:
        observed['held_stage'] = value['held_stage']
    for name, pattern in (('candidate_id', DIGEST), ('candidate_run', NUMBER), ('recovery_run', NUMBER)):
        if value.get(name):
            observed[name] = binding(value[name], pattern, name)
    return observed


def observe_candidate(value, identifier):
    actual = candidate.digest(candidate.encoded({key: data for key, data in value.items() if key != 'candidate_id'}))
    if value.get('candidate_id') != identifier or actual != identifier:
        raise ValueError('Lifecycle candidate manifest has conflicting identity')
    observed = {'candidate_id': identifier}
    for name, pattern in (('generation_run_id', NUMBER), ('generation_run_attempt', NUMBER), ('generation_sha', SHA)):
        observed[name] = binding(value.get(name), pattern, name)
    if value.get('derived_from_candidate'):
        observed['parent_candidate_id'] = binding(value['derived_from_candidate'], DIGEST, 'parent candidate')
    recovery = value.get('source_recovery') or {}
    if recovery.get('superseded_recovery_candidate'):
        observed['rejected_sibling_candidate_id'] = binding(
            recovery['superseded_recovery_candidate'], DIGEST, 'rejected sibling candidate')
        observed['rejected_sibling_artifact_run'] = binding(
            recovery.get('superseded_recovery_run'), NUMBER, 'rejected sibling run')
    return observed


def observe_review(name, report, repository, identifier):
    if type(report.get('schema_version')) is not int or report['schema_version'] != 1 or report.get('candidate_id') != identifier:
        raise ValueError('Lifecycle review checkpoint has conflicting identity')
    if name == 'review-ready.json':
        if 'pr_url' in report and report['pr_url'] is None:
            status, number = 'protected_publication_resume', None
        else:
            match = re.fullmatch(rf'https://github\.com/{re.escape(repository)}/pull/({NUMBER})', str(report.get('pr_url')))
            if not match:
                raise ValueError('Untrusted lifecycle review PR')
            status, number = 'review_ready', match[1]
    else:
        status, number = report.get('status'), report.get('pr_number')
        allowed = {'review_findings'} if name == 'review-blocked.json' else {'awaiting_review', 'review_failed'}
        if status not in allowed or report.get('repository') != repository or report.get('production_mutated') is not False:
            raise ValueError('Invalid lifecycle review state')
    observed = {
        'status': status, 'candidate_id': identifier,
        'artifact_run': binding(report.get('artifact_run'), NUMBER, 'review candidate run'),
        'head_sha': binding(report.get('head_sha'), SHA, 'review head'),
    }
    if status != 'protected_publication_resume':
        observed['pr_number'] = binding(number, NUMBER, 'review PR')
    return observed


def verify_protected_resume(read, review, readiness, release_sha, validation_digest):
    base = binding(readiness.get('base_sha'), SHA, 'review base')
    expected_digest = binding(readiness.get('validation_receipt_sha256'), DIGEST, 'review validation digest')
    if base != review['head_sha'] or base != release_sha or expected_digest != validation_digest:
        raise ValueError('Lifecycle protected resume disagrees with the plan or validation receipt')
    path = 'release/candidate.json'
    marker = archive._decode(read(f'contents/{path}?ref={base}'))
    size = marker.get('size')
    if (marker.get('path') != path or marker.get('encoding') != 'base64'
            or type(size) is not int or not 0 < size <= MAX_REPORT_BYTES
            or not isinstance(marker.get('content'), str) or len(marker['content']) > 2 * MAX_REPORT_BYTES):
        raise ValueError('Untrusted lifecycle protected candidate marker')
    raw = base64.b64decode(marker['content'].replace('\n', ''), validate=True)
    if len(raw) != size:
        raise ValueError('Lifecycle protected candidate marker size differs')
    observe_candidate(archive._decode(raw), review['candidate_id'])


def checkpoints(directory, origin, artifacts, read):
    attempt, repository = origin['run_attempt'], origin['repository']
    observed = {}
    readiness, validation_digest = None, None
    for artifact in artifacts:
        label = artifact['name']
        if label == f'release-plan-{attempt}':
            report = members(directory, artifact, {'release-plan.json'})['release-plan.json']
            observed['plan'] = observe_plan(report)
        elif label.startswith('candidate-'):
            report = members(directory, artifact, {'candidate.json'})['candidate.json']
            observed['persisted_candidate'] = observe_candidate(report, label.removeprefix('candidate-'))
        elif label.endswith(f'-{attempt}'):
            kind, identifier, *_ = label.split('-')
            if kind == 'validation':
                report = members(directory, artifact, {'validation.json'}).get('validation.json')
                if report is not None:
                    if report.get('candidate_id') != identifier:
                        raise ValueError('Lifecycle validation checkpoint has conflicting identity')
                    observed['validation'] = {'candidate_id': identifier,
                        'validation_sha': binding(report.get('validation_sha'), SHA, 'validation SHA')}
                    validation_digest = candidate.digest(candidate.encoded(report))
            elif kind == 'publication':
                reports = members(directory, artifact, {
                    'review-ready.json', 'review-pending.json', 'review-blocked.json', 'publication.json'})
                reviews = [(name, report) for name, report in reports.items() if name.startswith('review-')]
                if len(reviews) > 1:
                    raise ValueError('Conflicting lifecycle review checkpoints for the attempt')
                if reviews:
                    name, report = reviews[0]
                    observed['review'] = observe_review(name, report, repository, identifier)
                    if observed['review']['status'] == 'protected_publication_resume':
                        readiness = report
                if 'publication.json' in reports:
                    report = reports['publication.json']
                    if report.get('candidate_id') != identifier:
                        raise ValueError('Lifecycle publication checkpoint has conflicting identity')
                    observed['publication'] = {'candidate_id': identifier,
                        'publication_sha': binding(report.get('publication_sha'), SHA, 'publication SHA')}
            elif kind == 'live':
                report = members(directory, artifact, {'live-verification.json'}).get('live-verification.json')
                if report and report.get('verified') is True:
                    if report.get('candidate_id') != identifier:
                        raise ValueError('Lifecycle live checkpoint has conflicting identity')
                    observed['live'] = {'candidate_id': identifier,
                        'publication_sha': binding(report.get('publication_sha'), SHA, 'live publication SHA')}
    review, plan = observed.get('review'), observed.get('plan', {})
    if review:
        if 'persisted_candidate' in observed:
            expected_run = origin['run_id']
        elif review['candidate_id'] == plan.get('candidate_id'):
            expected_run = plan.get('candidate_run')
        else:
            expected_run = None
        if expected_run is not None and review['artifact_run'] != expected_run:
            raise ValueError('Lifecycle review names a different candidate artifact run')
        if readiness is not None:
            if expected_run is None:
                raise ValueError('Lifecycle protected resume needs an exact candidate artifact run')
            verify_protected_resume(read, review, readiness, plan.get('release_sha'), validation_digest)
            for stage in ('publication', 'live'):
                if stage in observed and observed[stage]['publication_sha'] != review['head_sha']:
                    raise ValueError('Lifecycle protected resume changed publication SHA')
    if 'live' in observed and 'publication' in observed and observed['live'] != observed['publication']:
        raise ValueError('Lifecycle publication and live observations differ')
    return observed


def observe(repository, run, attempt, directory, *, api=None):
    repository, run, attempt = archive._repository(repository), str(archive._positive(run)), archive._positive(attempt)
    read = (lambda path: archive.api(repository, path)) if api is None else api
    native = archive._decode(read(f'actions/runs/{run}/attempts/{attempt}'))
    source = archive._run_identity(repository, native, run, attempt)
    jobs = observe_jobs(read, source)
    inventory = archive._pages(read, f'actions/runs/{run}/artifacts', 'artifacts', require_total=True)
    conclusion = native['conclusion']
    if not jobs and (attempt != 1 or conclusion != 'cancelled' or inventory):
        raise ValueError('Missing native lifecycle jobs for completed release attempt')
    artifacts = observe_artifacts(Path(directory), source, conclusion, inventory)
    summary = checkpoints(Path(directory), source, artifacts, read)
    latest = archive._decode(read(f'actions/runs/{run}'))
    if archive._run_identity(repository, latest, run, attempt) != source or latest['conclusion'] != conclusion:
        raise ValueError('Native release attempt changed during observation')
    payload = {'schema_version': 1, 'mode': 'shadow', 'source': source,
               'source_conclusion': conclusion, 'stages': jobs, 'artifact_references': artifacts,
               'artifact_visibility': 'authenticated_archive' if inventory else 'no_visible_artifacts',
               'checkpoints': summary}
    return payload | {'receipt_sha256': candidate.digest(candidate.encoded(payload))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('run', 'attempt', 'archive', 'output'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    result = observe(os.environ['GITHUB_REPOSITORY'], args.run, args.attempt, args.archive)
    candidate.write_json(args.output, result)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        source, review = result['source'], result['checkpoints'].get('review')
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as output:
            output.write(
                f"Shadow observation for release run {source['run_id']} attempt {source['run_attempt']}. "
                f"Run conclusion `{result['source_conclusion']}`, artifact status `{result['artifact_visibility']}`.\n")
            if review:
                review_location = (f"review PR #{review['pr_number']}" if 'pr_number' in review
                                   else 'protected main')
                output.write(
                    f"Observed `{review['status']}` for {review_location} "
                    f"at `{review['head_sha']}`, candidate `{review['candidate_id']}` "
                    f"from run {review['artifact_run']}.\n")


if __name__ == '__main__':
    main()
