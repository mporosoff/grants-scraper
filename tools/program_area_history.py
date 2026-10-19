"""Retire modern cached-evidence work only through its exact protected receipt."""
from __future__ import annotations

import json
import re
import subprocess

import yaml

from tools import release_candidate as c, release_attempt_history as history
from tools.offline_spend import identity

VERSION = 'program-area-revalidation-modern-1'
FIELD = 'program_area_revalidation'
WORKFLOW = history.WORKFLOW


def require(ok, reason):
    if not ok:
        raise ValueError('Program-area publication history rejected: ' + reason)


def canonical(child):
    return child.get('candidate_id') == c.digest(c.encoded(
        {key: value for key, value in child.items() if key != 'candidate_id'}))


def prefix(parent):
    require(re.fullmatch('[a-f0-9]{64}', str(parent)) is not None, 'parent identity')
    return 'offline-ai-program-area-' + parent


def producer(meta):
    return {'run_id': str(meta['id']), 'run_attempt': str(meta['run_attempt']),
        'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']}


def pin(row):
    return {'id': row['id'], 'name': row['name'],
        'sha256': str(row.get('digest', '')).removeprefix('sha256:')}


def selected(rows, name, expected=None):
    matches = [row for row in rows if row['name'] == name]
    require(len(matches) == 1, 'unique ' + name)
    row = matches[0]
    require(row.get('expired') is False and type(row.get('id')) is int and row['id'] > 0
        and re.fullmatch('sha256:[a-f0-9]{64}', str(row.get('digest', ''))) is not None,
        'retained artifact identity')
    require(expected is None or pin(row) == expected, 'pinned artifact changed')
    return row


def checkpoint(repository, run, rows, attempt, child, receipt, *, link=None, restored=False):
    from tools import scheduled_catalog as daily
    meta = history.authenticate_attempt(repository, run, int(attempt), api=lambda path: daily.api(repository, path))
    require(meta['event'] == 'workflow_dispatch', 'manual protected producer')
    family = prefix(receipt['parent_candidate_id'])
    state = selected(rows, f'{family}-state-{run["id"]}-{attempt}', link.get('state') if link else None)
    names = ['reservation.json', 'ledger.json', 'reconciliation.json']
    candidate_path = 'complete-candidates/' + child['candidate_id'] + '/candidate.json'
    if link is None:
        names.append(candidate_path)
    linked_restore = link is not None and link.get('restored') is True
    documents = daily._reconciliation_documents(repository, run, state, names, complete_source=linked_restore)
    voucher, ledger, context = (documents[name] for name in names[:3])
    from tools.program_area_revalidation import require_projection_kind, require_administrative_budget
    kind = require_projection_kind(context, voucher, receipt)
    require_administrative_budget(context, ledger)
    require(context.get('version') == VERSION and voucher.get('version') == VERSION
        and context.get('parent_candidate_id') == receipt['parent_candidate_id']
        and voucher.get('parent_candidate_id') == receipt['parent_candidate_id']
        and context.get('operation_sha256') == voucher.get('operation_sha256')
        and identity({k: v for k, v in context.items() if k not in
            ('operation_sha256', 'completed_candidate_id')}) == context.get('operation_sha256'),
        'sealed operation context')
    require(ledger.get('logical_id') == 'offline-' + receipt['parent_run']
        and ledger.get('limit_microusd') == 2_000_000 and ledger.get('max_requests') == 300,
        'original logical allowance')
    if link is None:
        required = ('version', 'parent_candidate_id', 'parent_run', 'parent_attempt', 'parent_generation_sha',
            'parent_manifest_sha256', 'parent_producer', 'parent_artifact', 'original_spend',
            'operation_contract', 'audit_at', 'operation_sha256')
        if kind == 'administrative_submission':
            required += ('projection_kind', 'retained_requests')
        require(all(key in context and context[key] == receipt.get(key) for key in required)
            and context.get('completed_candidate_id') == child['candidate_id']
            and documents[candidate_path] == child and identity(ledger) == receipt['ledger_sha256'],
            'exact completed child and ledger')
        owner = receipt['affected_generation']
        require(voucher.get('producer_run') == owner['generation_run_id']
            and voucher.get('producer_attempt') == owner['generation_run_attempt']
            and voucher.get('operation_sha256') == receipt['operation_sha256'], 'original operation producer')
    else:
        from tools.catalog_reconcile import request_identity
        requests = ledger.get('requests')
        require(link['producer'] == producer(meta) and identity(ledger) == link['ledger_sha256']
            and isinstance(requests, list) and len(requests) == link['request_count']
            and identity(requests) == link['request_prefix_sha256']
            and request_identity(requests) == link['request_identity_prefix_sha256']
            and sum(row['charged_microusd'] for row in requests) == link['charged_microusd'],
            'consumed checkpoint ledger')
        if linked_restore:
            source_id = context.get('completed_candidate_id')
            source = documents.get('complete-candidates/' + str(source_id) + '/candidate.json', {})
            prior = source.get(FIELD) or {}; owner = prior.get('affected_generation') or {}
            require_projection_kind(context, prior)
            require(canonical(source) and source.get('candidate_id') == source_id
                and source.get('derived_from_candidate') == receipt['parent_candidate_id']
                and prior.get('operation_sha256') == context['operation_sha256']
                and prior.get('ledger_sha256') == identity(ledger)
                and voucher.get('producer_run') == owner.get('generation_run_id')
                and voucher.get('producer_attempt') == owner.get('generation_run_attempt'),
                'consumed completed restore identity')
            completed_restore(repository, run, meta)
        else:
            require(voucher.get('producer_run') == str(run['id'])
                and voucher.get('producer_attempt') == str(attempt), 'consumed operation producer')
    require(re.fullmatch('[a-f0-9]{64}', str(voucher.get('prior_ledger_sha256', ''))) is not None,
        'prior logical ledger identity')
    reservation = None
    if linked_restore or restored:
        require(not any(row['name'] == f'{family}-reservation-{run["id"]}-{attempt}' for row in rows),
            'consumed restore allocated new work')
        original_run = json.loads(daily.api(repository, 'actions/runs/' + voucher['producer_run']))
        history.authenticate_attempt(repository, original_run, int(voucher['producer_attempt']),
            api=lambda path: daily.api(repository, path))
        originals = daily.run_artifacts(original_run['id'], lambda path: daily.api(repository, path), repository=repository)
        reservation = selected(originals,
            f'{family}-reservation-{voucher["producer_run"]}-{voucher["producer_attempt"]}',
            link['reservation'] if linked_restore else None)
        require(daily._reconciliation_documents(repository, original_run, reservation,
            ['reservation.json'])['reservation.json'] == voucher, 'consumed original reservation')
        if restored:
            completed_restore(repository, run, meta)
    elif not restored:
        reservation = selected(rows, f'{family}-reservation-{run["id"]}-{attempt}',
            link.get('reservation') if link else None)
        require(daily._reconciliation_documents(repository, run, reservation,
            ['reservation.json'])['reservation.json'] == voucher, 'paired reservation')
    return producer(meta), state, reservation, ledger


def completed_restore(repository, run, meta, *, api=None):
    from tools import scheduled_catalog as daily
    read = api or (lambda path: daily.api(repository, path))
    jobs = history._jobs(run, meta, api=read, full=False)
    job = jobs.get('program-area-revalidation') or {}
    require(job.get('conclusion') == 'success' and all(name in history.DOWNSTREAM
        or name == 'program-area-revalidation' or row['conclusion'] == 'skipped'
        for name, row in jobs.items()), 'restore-only jobs')
    workflow = yaml.safe_load(c.git(c.ROOT, 'show', meta['head_sha'] + ':' + WORKFLOW))
    declared = workflow['jobs']['program-area-revalidation']['steps']
    guarded = [step['name'] for step in declared if step.get('if', '').startswith(
        "steps.restore.outputs.candidate_id == '' && steps.prepare.outputs.candidate_id == ''")]
    preparation = [step['name'] for step in declared if step.get('id') == 'prepare']
    uploads = [step['name'] for step in declared if step.get('if', '').startswith('always()')
        and 'steps.prepare.outputs.state_artifact' in step.get('with', {}).get('name', '')]
    steps = job.get('steps')
    require(isinstance(steps, list) and len(steps) <= 100, 'restore steps unavailable')
    by_name = {step['name']: step for step in steps}
    require(len(by_name) == len(steps) and all(step.get('status') == 'completed' for step in steps)
        and len(guarded) >= 4 and len(preparation) == 1 and len(uploads) == 1
        and all(by_name.get(name, {}).get('conclusion') == 'skipped' for name in guarded)
        and all(by_name.get(name, {}).get('conclusion') == 'success' for name in preparation + uploads),
        'restore repeated reservation or generation')


def boundary(root, repository, child, pointer, revision):
    """Read the exact completed source boundary behind a later runtime assembly."""
    from tools import scheduled_catalog as daily
    receipt = child[FIELD]; affected = receipt['affected_generation']
    require(canonical(child) and child['candidate_id'] == pointer.get('candidate_id'), 'protected candidate pointer')
    if (child.get('derived_from_candidate') == receipt['parent_candidate_id']
            and child.get('assembly_sha') == affected['generation_sha']):
        return child
    run = json.loads(daily.api(repository, 'actions/runs/' + affected['generation_run_id']))
    rows = daily.run_artifacts(run['id'], lambda path: daily.api(repository, path), repository=repository)
    name = f'{prefix(receipt["parent_candidate_id"])}-state-{run["id"]}-{affected["generation_run_attempt"]}'
    row = selected(rows, name)
    docs = daily._reconciliation_documents(repository, run, row, ['reconciliation.json'], complete_source=True)
    source_id = docs['reconciliation.json']['completed_candidate_id']
    source = docs['complete-candidates/' + source_id + '/candidate.json']
    conserved = ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
        'generation_dependencies', 'generator_versions', 'generation_baseline', 'generation_files',
        'team_identity', 'semantic_identity', 'original_generation', FIELD)
    require(canonical(source) and source.get('candidate_id') == source_id
        and source.get('derived_from_candidate') == receipt['parent_candidate_id']
        and source.get('assembly_sha') == affected['generation_sha']
        and all(key in source and child.get(key) == source[key] for key in conserved)
        and all(source.get('dependency_groups', {}).get(group)
            and source['dependency_groups'][group] == child.get('dependency_groups', {}).get(group)
            for group in ('source', 'teams', 'semantic')),
        'runtime assembly changed generated identity')
    require(bool(source.get('generation_files')), 'generated inventory unavailable')
    for name, digest in source['generation_files'].items():
        c.checked_path(root, name)
        raw = subprocess.check_output(['git', '-C', str(root), 'show', revision + ':' + name], stderr=subprocess.DEVNULL)
        require(source.get('files', {}).get(name) == child.get('files', {}).get(name) == digest == c.digest(raw),
            'published generated bytes changed')
    checkpoint(repository, run, rows, affected['generation_run_attempt'], source, receipt)
    return source


def earlier_boundary(root, child, pointer, older_revisions):
    """Follow an already-published parent before auditing its private boundary.

    Later team releases may change team bytes while preserving this receipt.
    They do not invalidate the earlier protected proof of the completed repair.
    """
    require(canonical(child) and child['candidate_id'] == pointer.get('candidate_id'), 'protected descendant pointer')
    conserved = ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
        'generation_dependencies', 'generator_versions', 'original_generation', FIELD)
    for revision in older_revisions:
        parent = json.loads(c.git(root, 'show', revision + ':release/candidate.json'))
        if parent.get('candidate_id') != child.get('derived_from_candidate'):
            continue
        source = json.loads(c.git(root, 'show', revision + ':release/candidate-source.json'))
        return (canonical(parent) and parent['candidate_id'] == source.get('candidate_id')
            and re.fullmatch('[1-9][0-9]*', str(source.get('artifact_run', ''))) is not None
            and all(key in parent and parent[key] == child.get(key) for key in conserved))
    return False


def published_consumes(root, run, artifacts, *, repository):
    """Unknown candidates, new vouchers and later paid work remain active owners."""
    from tools import scheduled_catalog as daily
    if not any(row['name'].startswith('offline-ai-program-area-') for row in artifacts):
        return False
    try:
        revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
            'release/candidate-source.json').splitlines()
        for index, revision in enumerate(revisions):
            published = json.loads(c.git(root, 'show', revision + ':release/candidate.json'))
            receipt = published.get(FIELD) or {}
            if receipt.get('version') != VERSION:
                continue
            affected = receipt.get('affected_generation') or {}
            links = [link for link in receipt.get('consumed_checkpoints', [])
                if link.get('producer', {}).get('run_id') == str(run['id'])]
            pointer = json.loads(c.git(root, 'show', revision + ':release/candidate-source.json'))
            own = affected.get('generation_run_id') == str(run['id'])
            transport = pointer.get('artifact_run') == str(run['id'])
            restoring = any(re.fullmatch(re.escape(prefix(receipt['parent_candidate_id']))
                + '-state-' + str(run['id']) + '-[1-9][0-9]*', row['name']) for row in artifacts)
            if not own and not links and not transport and not restoring:
                continue
            require(repository and run.get('status') == 'completed' and run.get('path') == WORKFLOW
                and run.get('head_branch') == 'main' and run.get('event') == 'workflow_dispatch', 'native owner')
            if earlier_boundary(root, published, pointer, revisions[index + 1:]):
                continue
            child = boundary(root, repository, published, pointer, revision)
            require(child['generation_sha'] == receipt['parent_generation_sha']
                and child.get('derived_from_candidate') == receipt['parent_candidate_id'], 'original generation identity')
            covered, acknowledged, states, producers = set(), set(), set(), []
            final_ledger = None
            if own:
                owner, state, voucher, final_ledger = checkpoint(repository, run, artifacts,
                    affected['generation_run_attempt'], child, receipt)
                producers.append(owner); states.add(state['id']); acknowledged.add(voucher['id'])
            if links and final_ledger is None:
                owner_run = json.loads(daily.api(repository, 'actions/runs/' + affected['generation_run_id']))
                rows = daily.run_artifacts(owner_run['id'], lambda path: daily.api(repository, path), repository=repository)
                final_ledger = checkpoint(repository, owner_run, rows,
                    affected['generation_run_attempt'], child, receipt)[3]
            for link in links:
                from tools.catalog_reconcile import request_identity
                owner, state, voucher, ledger = checkpoint(repository, run, artifacts,
                    link['producer']['run_attempt'], child, receipt, link=link)
                producers.append(owner); states.add(state['id']); acknowledged.add(voucher['id'])
                count = link['request_count']; requests = final_ledger['requests']
                require(count <= len(requests) and request_identity(requests[:count]) == link['request_identity_prefix_sha256']
                    and sum(row['charged_microusd'] for row in requests[:count]) <= link['charged_microusd'],
                    'consumed work missing from final ledger')
                if link.get('candidate'):
                    old = link['candidate']; row = selected(artifacts, 'candidate-' + old['candidate_id'], old['artifact'])
                    document = daily._reconciliation_documents(repository, run, row, ['candidate.json'])['candidate.json']
                    require(old['producer'] == owner and canonical(document)
                        and document['candidate_id'] == old['candidate_id']
                        and c.digest(c.encoded(document)) == old['manifest_sha256'], 'consumed candidate')
                    covered.add(row['id'])
            # A complete private candidate can be transported after native upload
            # failure. Its original producer and accounting remain unchanged.
            current_candidates = [row for row in artifacts if row['name'] == 'candidate-' + child['candidate_id']]
            for row in current_candidates:
                require(daily._reconciliation_documents(repository, run, row, ['candidate.json'])['candidate.json'] == child,
                    'transported candidate changed')
                covered.add(row['id'])
            family = prefix(receipt['parent_candidate_id'])
            restores = []
            for row in artifacts:
                match = re.fullmatch(re.escape(family) + '-state-' + str(run['id']) + '-([1-9][0-9]*)', row['name'])
                if not match or row['id'] in states:
                    continue
                owner, state, _, _ = checkpoint(repository, run, artifacts, match[1], child, receipt, restored=True)
                restores.append({'producer': owner, 'state_id': state['id']}); states.add(state['id'])
            require(producers or restores, 'completed owner checkpoint unavailable')
            require(all(row['id'] in covered for row in artifacts if row['name'].startswith('candidate-')),
                'unacknowledged candidate')
            require(all(row['id'] in acknowledged for row in artifacts if '-reservation-' in row['name'])
                and all(row['id'] in states for row in artifacts if '-state-' in row['name']),
                'unacknowledged allowance or task state')
            daily._require_reconciliation_restore_history(repository, run, producers, restores, artifacts, covered)
            return True
        return False
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise daily.Hold('Published program-area correction does not authenticate its completed work: ' + str(error), run['id']) from error
