"""Distinguish native runtime assemblies from scientific allowance owners."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

import yaml

from tools import release_candidate as candidate, release_attempt_history as history
from tools import release_checkpoint_archive as archives
from tools.fetch_release_artifact import artifact_bytes

RUNTIME = ('Load the currently published candidate for data reuse',
           'Verify and materialize unchanged source and semantic inputs',
           'Assemble runtime compatibility metadata around unchanged generated data',
           'Persist derived candidate with original generation provenance')


def require(ok, reason):
    if not ok:
        raise ValueError('Runtime assembly history rejected: ' + reason)


def _bytes(repository, run, artifact, read):
    require(artifact.get('expired') is False and type(artifact.get('id')) is int
            and artifact['id'] > 0 and artifact.get('workflow_run', {}).get('id') == run['id']
            and artifact['workflow_run'].get('head_sha') == run['head_sha']
            and artifact['workflow_run'].get('head_branch') == 'main'
            and re.fullmatch('sha256:[a-f0-9]{64}', artifact.get('digest', '')), 'artifact identity')
    raw = artifact_bytes(repository, str(run['id']), artifact, read)
    require('sha256:' + hashlib.sha256(raw).hexdigest() == artifact['digest'], 'artifact digest')
    return raw


def _native_candidate(repository, run, artifact, read):
    raw = _bytes(repository, run, artifact, read)
    with archives._members(raw) as packet, tempfile.TemporaryDirectory(prefix='runtime-candidate-') as temporary:
        names = {item.filename for item in packet.infolist() if not item.is_dir()}
        manifest_raw = packet.read('candidate.json'); manifest = json.loads(manifest_raw)
        require(manifest_raw == candidate.encoded(manifest), 'canonical candidate manifest')
        require(names == {'candidate.json'} | {'files/' + name for name in manifest['files']},
                'complete candidate members')
        root = Path(temporary)
        for name in names:
            path = candidate.checked_path(root, name); path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(packet.read(name))
        value = candidate.load(root, artifact['name'].removeprefix('candidate-'))
        _generated_binding(value)
        return value


def _reuse_plan(repository, run, artifacts, attempt, manifest, read):
    plans = [(int(match[1]), row) for row in artifacts
             if (match := re.fullmatch('release-plan-([1-9][0-9]*)', row['name'])) and int(match[1]) <= attempt]
    require(bool(plans), 'reuse plan missing')
    latest = max(number for number, _ in plans)
    selected = [row for number, row in plans if number == latest]
    require(len(selected) == 1, 'ambiguous reuse plan')
    with archives._members(_bytes(repository, run, selected[0], read)) as packet:
        require({row.filename for row in packet.infolist() if not row.is_dir()} == {'release-plan.json'},
                'reuse plan members')
        plan = json.loads(packet.read('release-plan.json'))
    require(plan.get('stage') == 'reuse' and plan.get('candidate_id') == manifest.get('derived_from_candidate')
            and re.fullmatch('[1-9][0-9]*', str(plan.get('candidate_run', '')))
            and plan.get('release_sha') == manifest.get('assembly_sha')
            and re.fullmatch('[a-f0-9]{40}', str(plan.get('release_sha', ''))), 'reuse plan binding')
    return plan


def _runtime_steps(workflow, job):
    declared = workflow['jobs']['assemble']['steps']; rows = job.get('steps')
    require(isinstance(rows, list) and 1 <= len(rows) <= 150, 'native assemble steps')
    names, numbers = {}, set()
    for row in rows:
        require(isinstance(row.get('name'), str) and row['name'] not in names
                and type(row.get('number')) is int and row['number'] > 0 and row['number'] not in numbers
                and row.get('status') == 'completed' and row.get('conclusion') in history.TERMINAL,
                'complete unambiguous assemble steps')
        names[row['name']] = row; numbers.add(row['number'])
    for step in declared:
        condition = step.get('if', '')
        guarded = "needs.plan.outputs.stage != 'reuse'" in condition or 'inputs.qualification_pilot' in condition
        command = step.get('run', '')
        paid = any(key.endswith('_API_KEY') for key in step.get('env', {})) or any(part in command for part in (
            'generation_spend_checkpoint', 'build_opportunity_teams', 'team_maintenance',
            'replay_team_maintenance', 'run_budgeted_vectors', 'build_search_v2_voyage_vectors'))
        require(not paid or guarded, 'unguarded provider or allowance step')
        if guarded:
            require(step.get('name') in names and names[step['name']]['conclusion'] == 'skipped',
                    'provider, allowance, task or team step ran')
        elif command:
            require(any(command.strip().startswith(prefix) for prefix in (
                'python -m tools.restore_generation_checkpoint', 'python -m tools.fetch_release_artifact',
                'python -m tools.assemble_release_candidate', 'node tools/build_search_release_package.mjs --write',
                'python -m tools.release_candidate create')), 'unknown runtime command')
    require(all(name in names for name in RUNTIME), 'missing runtime assembly evidence')
    produced = names[RUNTIME[-1]]['conclusion'] == 'success'
    if produced:
        require(job['conclusion'] == 'success' and all(names[name]['conclusion'] == 'success' for name in RUNTIME),
                'incomplete runtime candidate producer')
    return produced


def _generated_binding(value):
    generated = value.get('generation_files')
    require(isinstance(generated, dict) and bool(generated) and all(
        re.fullmatch('[a-f0-9]{64}', str(digest)) and value['files'].get(name) == digest
        for name, digest in generated.items()), 'generated member binding')


def no_generation_allowance(root, repository, run, artifacts, *, api=None):
    """A zero-cost native runtime candidate cannot retain an offline allowance."""
    if any('-reservation-' in row['name'] or '-state-' in row['name'] for row in artifacts):
        return False  # Paid/source owners require their existing checkpoint proof.
    candidates = [row for row in artifacts if row['name'].startswith('candidate-')]
    if not candidates:
        return False
    require(len(candidates) == 1 and re.fullmatch('candidate-[a-f0-9]{64}', candidates[0]['name']),
            'competing or invalid candidate evidence')
    if api is None:
        from tools.offline_ai_checkpoint import api as github
        api = lambda path: github(repository, path)
    history._inventory(repository, run, artifacts, api=api)
    manifest = _native_candidate(repository, run, candidates[0], api)
    # Scientific producers use generation/correction jobs, and must retain their
    # normal recovery ownership even when a voucher is missing.
    if str(manifest.get('generation_run_id')) == str(run['id']) or not manifest.get('derived_from_candidate'):
        return False
    require(type(run.get('run_attempt')) is int and 1 <= run['run_attempt'] <= history.MAX_ATTEMPTS,
            'attempt bound')
    identifier = manifest['candidate_id']; producers = []
    for number in range(1, run['run_attempt'] + 1):
        meta = history.authenticate_attempt(repository, run, number, api=api)
        jobs = history._jobs(run, meta, api=api, full=number == 1)
        if any(job['conclusion'] != 'skipped' for name, job in jobs.items()
               if name in history.PRODUCERS - {'assemble'} or name == 'sam-preflight'):
            return False
        assemble = jobs.get('assemble')
        if assemble and assemble['conclusion'] != 'skipped':
            workflow = yaml.safe_load(candidate.git(root, 'show', meta['head_sha'] + ':' + history.WORKFLOW))
            if _runtime_steps(workflow, assemble):
                producers.append(number)
    require(len(producers) == 1, 'one complete native runtime producer required')
    producer = producers[0]
    _reuse_plan(repository, run, artifacts, producer, manifest, api)
    allowed = re.compile(r'release-plan-[1-9][0-9]*|candidate-' + identifier +
                         r'|(?:validation|publication|live)-' + identifier + r'-[1-9][0-9]*|github-pages')
    require(all(allowed.fullmatch(row['name']) for row in artifacts), 'unknown zero-spend artifact')
    history.require_downstream_only(repository, run, producer, artifacts, api=api)
    return True
