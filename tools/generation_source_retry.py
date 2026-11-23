"""Queue at most two exact-job retries of a proved pre-provider XML transport stop.

Planning is read-only. A separate workflow, after the queueing release has
completed and released its lock, persists both intent and request before POST.
An uncertain acknowledgement never authorizes another request for that attempt.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

import yaml

from tools import release_candidate as c, release_attempt_history as attempts
from tools.fetch_release_artifact import artifact_bytes, run_artifacts
from tools.github_job_log_bytes import read_job_log
from tools.offline_ai import identity
from tools.offline_ai_checkpoint import api
from tools.release_dependencies import snapshot

WORKFLOW = '.github/workflows/refresh-opportunities.yml'
RECOVERY = '.github/workflows/recover-generation.yml'
PREFIX = 'generation-source-retry-'
XML_STEP = 'Build and validate complete public opportunity catalog'
DISPATCH_STEP = 'Request one exact original failed generate job'
MAX_RETRIES = 2


def require(ok, reason):
    if not ok:
        raise ValueError('Automatic source retry held: ' + reason)


def pages(read, path, key):
    rows, expected = [], None
    separator = '&' if '?' in path else '?'
    for page in range(1, 11):
        value = json.loads(read(f'{path}{separator}per_page=100&page={page}'))
        chunk, total = value.get(key), value.get('total_count')
        require(isinstance(chunk, list) and len(chunk) <= 100 and type(total) is int
                and total >= 0 and (expected is None or expected == total), 'complete stable pagination')
        expected = total
        rows.extend(chunk)
        require(len(rows) <= total, 'duplicate history page')
        if len(rows) == total:
            return rows
        require(bool(chunk), 'missing history page')
    raise ValueError('Automatic source retry held: history exceeds bounded lookup')


def packet(repository, run, artifact, read):
    require(artifact.get('expired') is False and type(artifact.get('id')) is int
            and re.fullmatch(r'sha256:[a-f0-9]{64}', artifact.get('digest', '')) is not None
            and artifact.get('workflow_run', {}).get('id') == int(run), 'live artifact identity')
    raw = artifact_bytes(repository, run, artifact, read)
    require(c.digest(raw) == artifact['digest'][7:] and len(raw) <= 2 * 1024 * 1024, 'artifact ZIP digest/size')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        names = [item.filename for item in members]
        require(len(names) == len(set(names)) and len(names) <= 4
                and sum(item.file_size for item in members) <= 2 * 1024 * 1024, 'bounded unique packet members')
        return {name: archive.read(name) for name in names}


def select(rows, name):
    selected = [row for row in rows if row.get('name') == name]
    require(len(selected) == 1, 'missing/ambiguous artifact ' + name)
    return selected[0]


def protected_run(value, path=WORKFLOW):
    require(type(value.get('id')) is int and value['id'] > 0
            and type(value.get('run_attempt')) is int and 1 <= value['run_attempt'] <= 10
            and value.get('path') == path and value.get('head_branch') == 'main'
            and re.fullmatch('[a-f0-9]{40}', value.get('head_sha', '')) is not None,
            'protected workflow/run identity')


def compatible(root, generation_sha, current_sha):
    require(c.git(root, 'rev-parse', 'HEAD') == current_sha, 'checked-out protected main advanced')
    c.git(root, 'merge-base', '--is-ancestor', generation_sha, current_sha)
    old, new = snapshot(root, generation_sha), snapshot(root, current_sha)
    groups = ('source', 'teams', 'semantic')
    require(all(old[group] == new[group] for group in groups), 'original generation inputs changed')
    before = yaml.safe_load(c.git(root, 'show', generation_sha + ':' + WORKFLOW))
    after = yaml.safe_load(c.git(root, 'show', current_sha + ':' + WORKFLOW))
    require(all(before['jobs'][job] == after['jobs'][job] for job in ('generate', 'sam-preflight')),
            'original generation job contract changed')
    for path in ('.github/actions/release-setup/action.yml', 'tools/generation_spend_checkpoint.py',
                 'tools/restore_generation_checkpoint.py'):
        require(c.git(root, 'show', generation_sha + ':' + path)
                == c.git(root, 'show', current_sha + ':' + path), 'generation orchestration changed: ' + path)
    return {group: old[group]['fingerprint'] for group in groups}


def source_stop(job, workflow, raw_log):
    declared = workflow['jobs']['generate']['steps']
    positions = [index for index, step in enumerate(declared) if step.get('name') == XML_STEP]
    require(len(positions) == 1, 'known XML collection boundary')
    boundary = positions[0]
    tail = declared[boundary:]
    require(all(isinstance(step.get('name'), str) for step in tail), 'complete named generation tail')
    native = job.get('steps')
    require(isinstance(native, list) and 1 <= len(native) <= 150, 'complete native steps')
    by_name, numbers = {}, set()
    for step in native:
        require(isinstance(step.get('name'), str) and step['name'] not in by_name
                and type(step.get('number')) is int and step['number'] not in numbers
                and step.get('status') == 'completed', 'unambiguous native steps')
        by_name[step['name']] = step
        numbers.add(step['number'])
    require(all(step['name'] in by_name for step in tail), 'missing source/provider tail evidence')
    require(by_name[XML_STEP]['conclusion'] == 'failure', 'XML collection did not fail')
    successful = ('Restore an already persisted generation on workflow rerun',
                  'Verify current public SAM receipt before any allowance',
                  'Restore the logical spend checkpoint',
                  'Reserve the complete logical allowance before provider dispatch',
                  'Pin the prior accepted scope snapshot before changes',
                  'Preserve the prior catalog for change detection')
    require(all(by_name.get(name, {}).get('conclusion') == 'success' for name in successful),
            'source failure prefix is incomplete')
    diagnostics = {'Preserve source refresh diagnostics after any outcome',
                   'Report automatic team coverage and remaining work',
                   'Retain spend and completed safe stages after any outcome'}
    for step in tail[1:]:
        outcome = by_name[step['name']]['conclusion']
        require(outcome == 'skipped' or step['name'] in diagnostics
                and 'always()' in step.get('if', '') and outcome == 'success',
                'source/enrichment/provider stage already ran: ' + step['name'])
    log = raw_log.decode('utf-8-sig')
    marker = '##[group]Run python -m scripts.build_catalog'
    require(log.count(marker) == 1, 'exact XML command log boundary')
    section = log.split(marker, 1)[1].split('##[group]', 1)[0]
    markers = [line.split('GRANTS_SOURCE_TRANSPORT_FAILURE ', 1)[1] for line in section.splitlines()
               if 'GRANTS_SOURCE_TRANSPORT_FAILURE ' in line]
    require(len(markers) <= 1, 'ambiguous transport failure markers')
    if markers:
        diagnosis = json.loads(markers[0])
        transport = (set(diagnosis) == {'version', 'operation', 'host', 'kind', 'attempts',
                                      'certificate_verification', 'source_complete', 'retry_safe'}
                     and type(diagnosis['version']) is int and diagnosis['version'] == 1
                     and diagnosis['operation'] in ('extract-index', 'extract-archive')
                     and (diagnosis['host'] in ('grants.gov', 'www.grants.gov')
                          or diagnosis['operation'] == 'extract-archive'
                          and diagnosis['host'] == 'prod-grants-gov-chatbot.s3.amazonaws.com')
                     and diagnosis['kind'] in ('tls', 'timeout', 'connection', 'transient_http')
                     and type(diagnosis['attempts']) is int and 1 <= diagnosis['attempts'] <= 3
                     and diagnosis['certificate_verification'] is True
                     and diagnosis['source_complete'] is False and diagnosis['retry_safe'] is True)
    else:
        # Retained pre-hardening evidence is admissible only while every pinned
        # generator input remains compatible. A source repair blocks this route.
        transport = (re.search(r'requests\.exceptions\.(?:SSLError|ConnectionError|ConnectTimeout|ReadTimeout|Timeout):', section)
                     and "host='www.grants.gov'" in section and '/xml-extract' in section)
    require('download_latest_extract' in section and 'scripts/build_catalog.py' in section
            and transport and '##[error]Process completed with exit code 1.' in section,
            'not the observed Grants.gov XML transport failure')
    return c.digest(raw_log)


def qualify(root, repository, owner, *, read=None, log_reader=None):
    """Prove every completed attempt has only the same pre-provider source stop."""
    read = read or (lambda path: api(repository, path))
    log_reader = log_reader or (lambda job: read_job_log(repository, job))
    run = json.loads(read(f'actions/runs/{owner}'))
    protected_run(run)
    require(run['id'] == int(owner) and run.get('event') == 'schedule'
            and run.get('status') == 'completed' and run.get('conclusion') == 'failure',
            'original owner is not a completed failed scheduled generation')
    current = json.loads(read('git/ref/heads/main'))['object']['sha']
    artifacts = run_artifacts(owner, read, repository=repository)
    allowed = re.compile(r'(?:release-plan-[1-9][0-9]*|(?:sam-preflight|generation-spend-(?:reservation|state))-'
                         + str(owner) + r'-[1-9][0-9]*)')
    require(all(allowed.fullmatch(row['name']) for row in artifacts), 'candidate/source output or unknown checkpoint exists')
    plans = sorted((int(row['name'].removeprefix('release-plan-')), row) for row in artifacts
                   if row['name'].startswith('release-plan-'))
    require(plans and len({number for number, _ in plans}) == len(plans)
            and max(number for number, _ in plans) <= run['run_attempt'], 'inherited plan inventory')
    proof, latest_job = [], None
    for number in range(1, run['run_attempt'] + 1):
        meta = attempts.authenticate_attempt(repository, run, number, api=read)
        require(meta['conclusion'] == 'failure', 'another attempt outcome requires diagnosis')
        jobs = attempts._jobs(run, meta, api=read, full=number == 1)
        job = jobs.get('generate')
        require(job is not None and job['conclusion'] == 'failure', 'missing exact failed generate job')
        require(all(row['conclusion'] == 'skipped' for name, row in jobs.items()
                    if name not in ('plan', 'sam-preflight', 'generate', 'closeout')),
                'another lifecycle stage started')
        applicable = [(n, row) for n, row in plans if n <= number]
        require(bool(applicable), 'missing inherited generation plan')
        plan_attempt, plan_artifact = applicable[-1]
        members = packet(repository, owner, plan_artifact, read)
        require(set(members) == {'release-plan.json'}, 'generation plan members')
        plan = json.loads(members['release-plan.json'])
        require(plan.get('stage') == 'generate' and plan.get('team_mode') == 'maintenance', 'original ordinary generation plan')
        producer = attempts.authenticate_attempt(repository, run, plan_attempt, api=read)
        require(attempts._jobs(run, producer, api=read, full=False).get('plan', {}).get('conclusion') == 'success',
                'generation plan producer was not successful')
        fingerprints = compatible(root, plan['release_sha'], current)
        workflow = yaml.safe_load(c.git(root, 'show', plan['release_sha'] + ':' + WORKFLOW))
        log_hash = source_stop(job, workflow, log_reader(job['id']))
        reservation = select(artifacts, f'generation-spend-reservation-{owner}-{number}')
        state = select(artifacts, f'generation-spend-state-{owner}-{number}')
        rm, sm = packet(repository, owner, reservation, read), packet(repository, owner, state, read)
        require(set(rm) == {'spend-reservation.json'} and set(sm) in
                ({'ledger.json'}, {'ledger.json', 'ledger.lock'}), 'no completed generation/cache state')
        r, ledger = json.loads(rm['spend-reservation.json']), json.loads(sm['ledger.json'])
        require(set(ledger) == {'version', 'logical_id', 'limit_microusd', 'max_requests', 'requests', 'events', 'blocked_providers'}
                and ledger.get('version') == 1 and ledger.get('logical_id') == 'offline-' + str(owner)
                and ledger.get('requests') == [] and ledger.get('events') == []
                and isinstance(ledger.get('blocked_providers'), dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in ledger['blocked_providers'].items()),
                'provider usage/events or ambiguous accounting')
        require(set(r) == {'run_id', 'attempt', 'mode', 'maximum_logical_spend_usd', 'prior_ledger_hash'}
                and r['run_id'] == str(owner) and r['attempt'] == str(number) and r['mode'] == 'maintenance'
                and r['maximum_logical_spend_usd'] == 2 and ledger.get('limit_microusd') == 2_000_000
                and ledger.get('max_requests') == 300 and r['prior_ledger_hash'] == identity(ledger),
                'original allowance/paired zero-dispatch state')
        proof.append({'attempt': number, 'job_id': job['id'], 'generation_sha': plan['release_sha'],
                      'plan_artifact_id': plan_artifact['id'], 'plan_zip_sha256': plan_artifact['digest'][7:],
                      'state_artifact_id': state['id'], 'state_zip_sha256': state['digest'][7:],
                      'reservation_artifact_id': reservation['id'], 'reservation_zip_sha256': reservation['digest'][7:],
                      'ledger_sha256': identity(ledger), 'log_sha256': log_hash, 'fingerprints': fingerprints})
        latest_job = job
    require(len(artifacts) == len(plans) + 2 * run['run_attempt']
            + len([row for row in artifacts if row['name'].startswith('sam-preflight-')]), 'complete paired artifact inventory')
    return {'schema_version': 1, 'owner_run': str(owner), 'owner_attempt': run['run_attempt'],
            'job_id': latest_job['id'], 'event_sha': run['head_sha'], 'protected_sha': current,
            'attempts': proof, 'provider_requests': 0, 'source_completed': False}


def request_history(repository, owner, *, read, current_run=''):
    """Missing post-intent evidence and unknown acknowledgements fail closed."""
    records = []
    runs = pages(read, 'actions/workflows/recover-generation.yml/runs?branch=main', 'workflow_runs')
    for run in runs:
        if int(run['id']) < int(owner):
            continue
        protected_run(run, RECOVERY)
        require(run['run_attempt'] == 1, 'retry executor was rerun; prior acknowledgement requires diagnosis')
        if str(run['id']) == str(current_run):
            continue
        require(run.get('event') == 'workflow_run', 'retry workflow event identity')
        if run.get('status') == 'queued':
            continue
        require(run.get('status') == 'completed', 'another retry executor is active')
        rows = pages(read, f'actions/runs/{run["id"]}/artifacts', 'artifacts')
        intents = [a for a in rows if a['name'].startswith(PREFIX + 'intent-')]
        requests = [a for a in rows if a['name'].startswith(PREFIX + 'request-')]
        jobs = pages(read, f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs', 'jobs')
        dispatches = [s for j in jobs for s in j.get('steps', []) if s.get('name') == DISPATCH_STEP]
        if not intents and not requests and len(jobs) == 1 and jobs[0].get('conclusion') == 'skipped' and jobs[0].get('steps') == []:
            continue
        require(len(dispatches) == 1, 'complete retry executor dispatch evidence')
        if not intents and not requests:
            require(dispatches[0]['conclusion'] == 'skipped', 'missing durable dispatch accounting')
            continue
        require(len(intents) == len(requests) == 1, 'unpaired/ambiguous retry intent or request')
        im, rm = packet(repository, run['id'], intents[0], read), packet(repository, run['id'], requests[0], read)
        require(set(im) == {'intent.json'} and set(rm) == {'request.json'}, 'retry packet members')
        intent, request = json.loads(im['intent.json']), json.loads(rm['request.json'])
        require(request.get('intent_sha256') == c.digest(im['intent.json'])
                and intent.get('executor_run') == str(run['id']) and intent.get('executor_attempt') == run['run_attempt']
                and request.get('owner_run') == intent.get('proof', {}).get('owner_run')
                and request.get('owner_attempt') == intent.get('proof', {}).get('owner_attempt'), 'authenticated retry accounting')
        if request['owner_run'] == str(owner):
            records.append(request)
    require(len(records) <= MAX_RETRIES and len({r['owner_attempt'] for r in records}) == len(records), 'duplicate/exhausted retry history')
    return sorted(records, key=lambda r: r['owner_attempt'])


def queue(root, environment, owner, *, read=None, log_reader=None):
    repository = environment['GITHUB_REPOSITORY']
    read = read or (lambda path: api(repository, path))
    proof = qualify(root, repository, owner, read=read, log_reader=log_reader)
    history = request_history(repository, owner, read=read)
    require(len(history) < MAX_RETRIES, 'two automatic retries already reserved')
    require(all(row['owner_attempt'] < proof['owner_attempt'] for row in history), 'prior request acknowledgement is unknown; no redispatch')
    return {'stage': 'queued-recovery', 'daily_status': 'recovering', 'recovery_run': str(owner),
            'source_retry': proof, 'reason': 'Queue one exact original failed generation job after this release completes; no new allowance'}


def prepare(root, environment, caller, caller_attempt, directory, *, read=None, log_reader=None):
    require(environment.get('GITHUB_RUN_ATTEMPT') == '1', 'executor reruns cannot repeat a request')
    repository = environment['GITHUB_REPOSITORY']
    read = read or (lambda path: api(repository, path))
    meta = json.loads(read(f'actions/runs/{caller}'))
    protected_run(meta)
    require(meta['run_attempt'] == int(caller_attempt) and meta.get('event') == 'schedule'
            and meta.get('status') == 'completed' and meta.get('conclusion') == 'failure', 'queueing release has not completed and freed its lock')
    rows = run_artifacts(caller, read, repository=repository)
    plans = [(int(row['name'].removeprefix('release-plan-')), row) for row in rows
             if re.fullmatch(r'release-plan-[1-9][0-9]*', row['name'])
             and int(row['name'].removeprefix('release-plan-')) <= int(caller_attempt)]
    require(bool(plans), 'missing release plan')
    latest = max(number for number, _ in plans)
    chosen = [row for number, row in plans if number == latest]
    require(len(chosen) == 1, 'ambiguous latest release plan')
    members = packet(repository, caller, chosen[0], read)
    require(set(members) == {'release-plan.json'}, 'queue plan members')
    plan = json.loads(members['release-plan.json'])
    if plan.get('stage') != 'queued-recovery':
        return None
    require(latest == int(caller_attempt), 'queueing plan must be produced by the completed caller attempt')
    caller_meta = attempts.authenticate_attempt(repository, meta, int(caller_attempt), api=read)
    require(attempts._jobs(meta, caller_meta, api=read, full=True)['plan']['conclusion'] == 'success', 'successful queue producer')
    owner = plan['recovery_run']
    proof = qualify(root, repository, owner, read=read, log_reader=log_reader)
    require(proof == plan.get('source_retry') and proof['protected_sha'] == plan.get('release_sha'), 'queue proof/main or owner changed')
    history = request_history(repository, owner, read=read, current_run=environment['GITHUB_RUN_ID'])
    require(len(history) < MAX_RETRIES and all(row['owner_attempt'] < proof['owner_attempt'] for row in history),
            'retry exhausted or acknowledgement unknown')
    intent = {'schema_version': 1, 'caller_run': str(caller), 'caller_attempt': int(caller_attempt),
              'executor_run': environment['GITHUB_RUN_ID'], 'executor_attempt': int(environment['GITHUB_RUN_ATTEMPT']),
              'proof': proof, 'retry_number': len(history) + 1}
    c.write_json(Path(directory) / 'intent.json', intent)
    return intent


def arm(directory):
    directory = Path(directory)
    raw = (directory / 'intent.json').read_bytes()
    intent = json.loads(raw)
    request = {'schema_version': 1, 'intent_sha256': c.digest(raw), 'owner_run': intent['proof']['owner_run'],
               'owner_attempt': intent['proof']['owner_attempt'], 'job_id': intent['proof']['job_id'],
               'retry_number': intent['retry_number'], 'status': 'reserved_before_dispatch'}
    c.write_json(directory / 'request.json', request)
    return request


def post_job(repository, job):
    # A mutation is submitted once. Transport uncertainty is never auto-retried.
    raw = subprocess.check_output(['gh', 'api', '--method', 'POST', '--include',
                                  f'repos/{repository}/actions/jobs/{job}/rerun'], stderr=subprocess.PIPE, timeout=60)
    require(re.match(rb'HTTP/\S+ 201\b', raw) is not None, 'retry POST acknowledgement unknown')


def dispatch(root, environment, directory, *, read=None, log_reader=None, post=None):
    require(environment.get('GITHUB_RUN_ATTEMPT') == '1', 'executor reruns cannot repeat a request')
    repository = environment['GITHUB_REPOSITORY']
    read = read or (lambda path: api(repository, path))
    directory = Path(directory)
    intent = json.loads((directory / 'intent.json').read_bytes())
    require(intent['executor_run'] == environment['GITHUB_RUN_ID']
            and intent['executor_attempt'] == int(environment['GITHUB_RUN_ATTEMPT']), 'exact executor attempt')
    rows = pages(read, f'actions/runs/{environment["GITHUB_RUN_ID"]}/artifacts', 'artifacts')
    for kind in ('intent', 'request'):
        name = f'{PREFIX}{kind}-{environment["GITHUB_RUN_ID"]}-{environment["GITHUB_RUN_ATTEMPT"]}'
        members = packet(repository, environment['GITHUB_RUN_ID'], select(rows, name), read)
        require(members == {kind + '.json': (directory / (kind + '.json')).read_bytes()}, 'durable exact ' + kind + ' required before POST')
    fresh = prepare(root, environment, intent['caller_run'], intent['caller_attempt'], directory / 'rechecked',
                    read=read, log_reader=log_reader)
    require(fresh == intent, 'retry authority changed before POST')
    outcome = {'schema_version': 1, 'owner_run': intent['proof']['owner_run'],
               'owner_attempt': intent['proof']['owner_attempt'], 'job_id': intent['proof']['job_id'],
               'retry_number': intent['retry_number'], 'status': 'acknowledgement_unknown', 'verified_live': False}
    try:
        (post or post_job)(repository, intent['proof']['job_id'])
        outcome['status'] = 'requested'
    finally:
        c.write_json(directory / 'outcome.json', outcome)
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'arm', 'dispatch'))
    parser.add_argument('--caller'); parser.add_argument('--caller-attempt')
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(c.ROOT, os.environ, args.caller, args.caller_attempt, args.directory)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write('ready=' + str(result is not None).lower() + '\n')
    elif args.action == 'arm':
        result = arm(args.directory)
    else:
        result = dispatch(c.ROOT, os.environ, args.directory)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
