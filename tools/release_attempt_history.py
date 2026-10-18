"""Authenticate bounded release-attempt history without resetting any allowance."""
from __future__ import annotations

import hashlib
import json
import re

import yaml

from tools import release_candidate as candidate
from tools.fetch_release_artifact import run_artifacts

WORKFLOW = '.github/workflows/refresh-opportunities.yml'
MAX_ATTEMPTS = 10
MAX_JOB_PAGES = 10
KNOWN_JOBS = frozenset({'plan', 'sam-preflight', 'generate', 'assemble', 'catalog-correction',
    'catalog-reconcile', 'program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction',
    'catalog-identity-correction', 'catalog-url-correction', 'candidate', 'validate', 'publish', 'pages',
    'verify-live', 'closeout'})
PRODUCERS = frozenset({'generate', 'assemble', 'catalog-correction', 'catalog-reconcile',
    'program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction',
    'catalog-identity-correction', 'catalog-url-correction'})
DOWNSTREAM = frozenset({'plan', 'candidate', 'validate', 'publish', 'pages', 'verify-live', 'closeout'})
TERMINAL = frozenset({'success', 'failure', 'cancelled', 'skipped', 'neutral', 'timed_out',
                      'action_required', 'stale', 'startup_failure'})


def require(ok, reason):
    if not ok:
        raise ValueError('Release attempt history rejected: ' + reason)


def _trusted_meta(meta):
    require(isinstance(meta, dict) and type(meta.get('id')) is int and meta['id'] > 0
        and type(meta.get('run_attempt')) is int and 1 <= meta['run_attempt'] <= MAX_ATTEMPTS
        and meta.get('path') == WORKFLOW and meta.get('head_branch') == 'main'
        and meta.get('event') in ('push', 'schedule', 'workflow_dispatch')
        and isinstance(meta.get('head_sha'), str) and re.fullmatch('[a-f0-9]{40}', meta['head_sha']),
        'protected workflow/run identity')


def authenticate_attempt(repository, run_meta, attempt, *, api):
    """Return the original immutable attempt, separately from the latest run."""
    _trusted_meta(run_meta)
    require(type(attempt) is int and 1 <= attempt <= run_meta['run_attempt'], 'attempt bound')
    value = json.loads(api(f'actions/runs/{run_meta["id"]}/attempts/{attempt}'))
    _trusted_meta(value)
    require(value.get('run_attempt') == attempt and all(value.get(key) == run_meta.get(key)
        for key in ('id', 'path', 'head_branch', 'head_sha', 'event'))
        and value.get('status') == 'completed' and value.get('conclusion') in TERMINAL,
        'completed matching attempt metadata')
    return value


def workflow_job_names(head_sha):
    """Use exact protected workflow bytes, including finite reusable Pages names."""
    require(isinstance(head_sha, str) and re.fullmatch('[a-f0-9]{40}', head_sha), 'workflow SHA')
    workflow = yaml.safe_load(candidate.git(candidate.ROOT, 'show', head_sha + ':' + WORKFLOW))
    jobs = workflow.get('jobs') if isinstance(workflow, dict) else None
    require(isinstance(jobs, dict) and {'plan', 'generate', 'assemble', 'closeout'} <= set(jobs)
            and set(jobs) <= KNOWN_JOBS, 'known protected workflow job inventory')
    for name, job in jobs.items():
        require(isinstance(job, dict) and job.get('name', name) == name, 'declared job name')
        if 'uses' in job:
            require(name == 'pages' and job['uses'] == './.github/workflows/pages.yml', 'known reusable job')
            pages = yaml.safe_load(candidate.git(candidate.ROOT, 'show', head_sha + ':.github/workflows/pages.yml'))
            require(isinstance(pages, dict) and set(pages.get('jobs') or {}) == {'deploy'}
                    and pages['jobs']['deploy'].get('name', 'deploy') == 'deploy', 'known Pages expansion')
    return frozenset(jobs)


def _jobs(run_meta, attempt_meta, *, api, full):
    expected = workflow_job_names(attempt_meta['head_sha'])
    rows, count = [], None
    for page in range(1, MAX_JOB_PAGES + 1):
        value = json.loads(api(f'actions/runs/{run_meta["id"]}/attempts/{attempt_meta["run_attempt"]}/jobs?per_page=100&page={page}'))
        batch, total = value.get('jobs'), value.get('total_count')
        require(isinstance(batch, list) and len(batch) <= 100 and type(total) is int
                and 0 <= total <= 100 * MAX_JOB_PAGES and (count is None or count == total),
                'complete stable job pagination')
        count = total
        rows.extend(batch)
        require(len(rows) <= count, 'duplicate/inconsistent job pages')
        if len(rows) == count:
            break
        require(bool(batch), 'missing job page')
    else:
        raise ValueError('Release attempt history rejected: job pagination bound')
    require(len(rows) == count, 'complete attempt jobs')
    result, ids = {}, set()
    for job in rows:
        require(isinstance(job, dict), 'job object')
        raw_name = job.get('name')
        # GitHub emits "pages" when skipped and "pages / deploy" when called.
        name = 'pages' if raw_name == 'pages / deploy' and 'pages' in expected else raw_name
        require(name in expected and name not in result and type(job.get('id')) is int
                and job['id'] > 0 and job['id'] not in ids
                and job.get('run_id') == run_meta['id']
                and job.get('run_attempt') == attempt_meta['run_attempt']
                and job.get('head_sha') == run_meta['head_sha']
                and job.get('head_branch') == 'main'
                and job.get('status') == 'completed' and job.get('conclusion') in TERMINAL,
                'unknown, duplicate, active or mismatched job')
        result[name] = job
        ids.add(job['id'])
    require(not full or set(result) == expected, 'missing declared workflow jobs')
    require(bool(result) or attempt_meta['conclusion'] == 'cancelled', 'empty noncancelled attempt')
    return result


def _inventory(repository, run_meta, artifacts, *, api):
    require(isinstance(artifacts, list), 'complete artifact inventory required')
    def identities(rows):
        result, ids = [], set()
        for item in rows:
            require(isinstance(item, dict) and type(item.get('id')) is int and item['id'] > 0
                    and item['id'] not in ids and isinstance(item.get('name'), str), 'artifact identity')
            ids.add(item['id'])
            result.append((item['id'], item['name'], item.get('digest'), item.get('expired'),
                           json.dumps(item.get('workflow_run'), sort_keys=True)))
        return sorted(result)
    expected = identities(artifacts)
    actual = run_artifacts(run_meta['id'], api, repository=repository)
    require(identities(actual) == expected, 'incomplete or changing native/archive artifact inventory')
    return expected


def _generate_stopped_before_allocation(head_sha, job):
    """Authenticate a failed public/setup prefix, never an uncheckpointed dispatch."""
    require(job.get('conclusion') in ('failure', 'cancelled'), 'generate was not a pre-allocation stop')
    workflow = yaml.safe_load(candidate.git(candidate.ROOT, 'show', head_sha + ':' + WORKFLOW))
    declared = workflow['jobs']['generate']['steps']
    allocation = [index for index, step in enumerate(declared)
                  if 'python -m tools.generation_spend_checkpoint' in step.get('run', '')]
    require(len(allocation) == 1 and allocation[0] >= 3, 'known generation allocation boundary')
    tail = declared[allocation[0]:]
    require(len(tail) >= 20 and all(isinstance(step.get('name'), str) for step in tail),
            'complete named allocation and generation steps')
    # These existing always() steps only report or upload already-existing files.
    # The independently authenticated artifact inventory must still contain no
    # allowance, private state, source output or candidate from any attempt.
    diagnostics = {'Preserve source refresh diagnostics after any outcome',
                   'Report automatic team coverage and remaining work',
                   'Retain linked task accounting and exact completed responses',
                   'Retain spend and completed safe stages after any outcome'}
    require(all('always()' in step.get('if', '') for step in tail if step['name'] in diagnostics),
            'known bounded public diagnostics')
    steps = job.get('steps')
    require(isinstance(steps, list) and 1 <= len(steps) <= 150, 'native pre-allocation step evidence')
    by_name, numbers = {}, set()
    for step in steps:
        require(isinstance(step, dict) and isinstance(step.get('name'), str)
                and step['name'] not in by_name and type(step.get('number')) is int
                and step['number'] > 0 and step['number'] not in numbers
                and step.get('status') == 'completed' and step.get('conclusion') in TERMINAL,
                'complete unambiguous native pre-allocation steps')
        by_name[step['name']] = step
        numbers.add(step['number'])
    require(all(step['name'] in by_name for step in tail), 'missing allocation or generation step evidence')
    require(all(by_name[step['name']]['conclusion'] == 'skipped'
                for step in tail if step['name'] not in diagnostics),
            'allocation, source or provider work started')
    boundary = by_name[tail[0]['name']]['number']
    require(all(by_name[step['name']]['number'] >= boundary for step in tail)
            and any(step['number'] < boundary and step['conclusion'] in ('failure', 'cancelled')
                    for step in steps), 'failure did not precede allocation')
    return {'job_id': job['id'], 'allocation_step_number': boundary,
            'native_steps_sha256': hashlib.sha256(candidate.encoded(steps)).hexdigest()}


def require_preflight_only_before_allocation(repository, run_meta, current_attempt, artifacts, *, api):
    """Prove this is the first reservation despite earlier preflight-only attempts."""
    _trusted_meta(run_meta)
    require(type(current_attempt) is int and 1 < current_attempt == run_meta['run_attempt'] <= MAX_ATTEMPTS
            and run_meta.get('status') == 'in_progress', 'current first-allocation attempt')
    inventory = _inventory(repository, run_meta, artifacts, api=api)
    require(len({item['name'] for item in artifacts}) == len(artifacts), 'conflicting preflight artifact names')
    for artifact in artifacts:
        name = artifact['name']
        match = re.fullmatch(r'release-plan-([1-9][0-9]*)|sam-preflight-' + str(run_meta['id']) + r'-([1-9][0-9]*)', name)
        require(match is not None and int(next(value for value in match.groups() if value)) <= current_attempt,
                'prior work or unknown artifact cannot initialize an allowance')
    attempts, inherited, generate_stop = [], {}, None
    for number in range(1, current_attempt):
        prior = authenticate_attempt(repository, run_meta, number, api=api)
        require(prior['conclusion'] in ('failure', 'cancelled'), 'prior attempt was not a preflight stop')
        # Failed-job retries omit successful prerequisite jobs from their native
        # attempt inventory. Only the first complete authenticated inventory can
        # seed inherited outcomes; each later returned job replaces its old row.
        jobs = _jobs(run_meta, prior, api=api, full=number == 1)
        inherited.update(jobs)
        preflight = inherited.get('sam-preflight', {}).get('conclusion')
        if 'generate' in jobs:
            generate_stop = (_generate_stopped_before_allocation(prior['head_sha'], jobs['generate'])
                             if preflight == 'success' and jobs['generate']['conclusion'] in ('failure', 'cancelled') else None)
        generate = inherited['generate']['conclusion']
        require(inherited['plan']['conclusion'] == 'success'
                and ((preflight in ('failure', 'cancelled') and generate == 'skipped')
                     or (preflight == 'success' and generate in ('failure', 'cancelled') and generate_stop))
                and all(job['conclusion'] == 'skipped' for name, job in inherited.items()
                        if name not in ('plan', 'sam-preflight', 'generate', 'closeout')),
                'prior generation or downstream work started')
        attempts.append({'attempt': number, 'head_sha': prior['head_sha'],
                         'jobs': {name: {'id': job['id'], 'conclusion': job['conclusion']}
                                  for name, job in sorted(jobs.items())},
                         **({'generate_preallocation_stop': generate_stop} if generate_stop else {})})
    return {'version': 'first-allocation-after-preflight-1', 'run_id': str(run_meta['id']),
            'current_attempt': current_attempt, 'head_sha': run_meta['head_sha'], 'prior_attempts': attempts,
            'artifact_inventory_sha256': hashlib.sha256(candidate.encoded(inventory)).hexdigest(),
            'prior_allowance_reserved': False, 'prior_provider_dispatch': False}


def require_downstream_only(repository, run_meta, producer_attempt, artifacts, *, api, allowed_candidate_ids=None):
    """Keep the original producer identity across later downstream-only retries."""
    original = authenticate_attempt(repository, run_meta, producer_attempt, api=api)
    require(run_meta.get('status') == 'completed' and run_meta.get('conclusion') in TERMINAL,
            'latest downstream attempt is not terminal')
    _inventory(repository, run_meta, artifacts, api=api)
    candidates = {item['id'] for item in artifacts if item['name'].startswith('candidate-')}
    require(len(candidates) <= 1 if allowed_candidate_ids is None else candidates == set(allowed_candidate_ids),
            'competing candidate evidence')
    for artifact in artifacts:
        name = artifact['name']
        if '-reservation-' in name or '-state-' in name:
            match = re.search(r'-' + str(run_meta['id']) + r'-([1-9][0-9]*)$', name)
            require(match is not None and int(match[1]) <= producer_attempt,
                    'later or unknown allowance/task accounting')
    for number in range(producer_attempt + 1, run_meta['run_attempt'] + 1):
        later = authenticate_attempt(repository, run_meta, number, api=api)
        jobs = _jobs(run_meta, later, api=api, full=False)
        require(all(job['conclusion'] == 'skipped' or name in DOWNSTREAM for name, job in jobs.items()),
                'later generation or correction work started')
    return original
