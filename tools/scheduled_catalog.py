"""Read-only daily release selection; a retry never creates another allowance."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import yaml

from tools import release_candidate as c
from tools.fetch_release_artifact import artifact_bytes, fetch, run_artifacts
from tools.offline_ai_checkpoint import api
from tools.release_dependencies import candidate_groups, changed_groups, snapshot, unpublished_input_changes

WORKFLOW = '.github/workflows/refresh-opportunities.yml'
METADATA = 'data/catalog-metadata.js'
MAX_PAGES = 10


class Hold(ValueError):
    def __init__(self, message, run=''):
        super().__init__(message)
        self.run = str(run)


def utc_timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Missing catalog timestamp')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Catalog timestamp requires a timezone')
    return stamp.astimezone(timezone.utc)


def iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def daily_window(now):
    if now.tzinfo is None:
        raise ValueError('Schedule clock requires a timezone')
    now = now.astimezone(timezone.utc)
    start = now.replace(hour=10, minute=17, second=0, microsecond=0)
    return start if now >= start else start - timedelta(days=1)


def catalog_generated_at(root, manifest):
    """Read source freshness only from the exact candidate-bound metadata bytes."""
    try:
        raw = (Path(root) / METADATA).read_bytes()
    except OSError as error:
        raise ValueError('Candidate catalog metadata is unavailable') from error
    if c.digest(raw) != manifest.get('files', {}).get(METADATA):
        raise ValueError('Catalog metadata does not match the candidate hash')
    match = re.fullmatch(r'\s*(?:/\*.*?\*/\s*)?globalThis\.GRANT_CATALOG_METADATA\s*=\s*(\{.*\})\s*;\s*',
                         raw.decode('utf-8'), flags=re.S)
    if not match:
        raise ValueError('Invalid catalog metadata assignment')
    metadata = json.loads(match[1])
    if type(metadata.get('schema_version')) is not int or metadata['schema_version'] != 1:
        raise ValueError('Unsupported catalog metadata schema')
    return iso(utc_timestamp(metadata.get('generated_at')))


def _pages(repository, path, key):
    separator = '&' if '?' in path else '?'
    for page in range(1, MAX_PAGES + 1):
        value = json.loads(api(repository, f'{path}{separator}per_page=100&page={page}'))
        rows = value[key]
        if not isinstance(rows, list):
            raise Hold('Invalid release history response')
        yield rows
        if len(rows) < 100:
            return
    raise Hold('Release history exceeds the bounded recovery lookup')


def _published(root):
    """Protected pointers identify superseded publications, never passing gates."""
    revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
                      'release/candidate-source.json').splitlines()
    return {(str(value['artifact_run']), value['candidate_id']) for value in
            (json.loads(c.git(root, 'show', sha + ':release/candidate-source.json')) for sha in revisions)}


def _published_access_supersedes(root, run, artifacts):
    """Recognize only the authenticated ac68 parent of a published access child.

    This is publication lineage, not permission to retire arbitrary zero-spend
    runs. A later attempt or changed artifact identity remains a recovery owner.
    """
    from tools import catalog_access_correction as access
    if run.get('id') != access.RUN:
        return False
    expected = {'run_attempt': access.ATTEMPT, 'head_sha': access.EVENT_SHA,
                'head_branch': 'main', 'path': WORKFLOW, 'event': 'workflow_dispatch',
                'status': 'completed', 'conclusion': 'failure'}
    if (type(run.get('run_attempt')) is not int
            or any(run.get(key) != value for key, value in expected.items())):
        return False
    if any(item['name'].startswith('generation-spend-reservation-')
           or item['name'].startswith('program-area-vectors-') and '-reservation-' in item['name']
           for item in artifacts):
        return False
    if sum(item['name'].startswith('candidate-') for item in artifacts) != 1:
        return False
    for identifier, name, digest in access.ARTIFACTS.values():
        matches = [item for item in artifacts if item.get('id') == identifier or item.get('name') == name]
        if (len(matches) != 1 or matches[0].get('id') != identifier or matches[0].get('name') != name
                or matches[0].get('digest') != 'sha256:' + digest or matches[0].get('expired') is not False):
            return False
    revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
                      'release/candidate-source.json').splitlines()
    for sha in revisions:
        pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
        child = json.loads(c.git(root, 'show', sha + ':release/candidate.json'))
        receipt = child.get('access_correction') or {}
        if (receipt.get('parent_candidate') != access.PARENT
                or child.get('derived_from_candidate') != access.PARENT):
            continue
        valid_identity = (child.get('candidate_id') == pointer.get('candidate_id')
            == c.digest(c.encoded({key: value for key, value in child.items() if key != 'candidate_id'})))
        prior = child.get('source_recovery') or {}
        producer = receipt.get('affected_generation') or {}
        parent_producer = prior.get('affected_generation') or {}
        if not (valid_identity and child.get('derived_from_candidate') == access.PARENT
                and child.get('generation_run_id') == '36896442720'
                and receipt.get('version') == access.VERSION and receipt.get('parent_run') == access.RUN
                and receipt.get('parent_manifest_sha256') == access.MANIFEST_SHA
                and producer.get('generation_run_id') == pointer.get('artifact_run')
                and parent_producer.get('generation_run_id') == str(access.RUN)
                and parent_producer.get('generation_run_attempt') == str(access.ATTEMPT)
                and parent_producer.get('generation_sha') == access.EVENT_SHA):
            raise Hold('Published access-correction lineage does not authenticate its exact parent', access.RUN)
        return True
    return False


def _published_url_supersedes(root, run, artifacts):
    """Recognize the exact 051d parent and rejected3912 sibling after publication.

    This is publication lineage, not permission to retire arbitrary zero-spend
    runs. A later attempt or changed artifact identity remains a recovery owner.
    """
    from tools import catalog_url_correction as url
    superseded = url.SUPERSEDED_URL_CORRECTION
    sibling = run.get('id') == superseded['producer']['run_id']
    if run.get('id') == url.RUN:
        attempt, event_sha, pins = url.ATTEMPT, url.EVENT_SHA, url.ARTIFACTS.values()
    elif sibling:
        owner = superseded['producer']
        attempt, event_sha = owner['run_attempt'], owner['event_sha']
        names = {'candidate': 'candidate-' + superseded['candidate_id'],
                 'receipt': f"url-correction-{owner['run_id']}-{attempt}"}
        pins = [(item['id'], names[role], item['sha256'])
                for role, item in superseded['artifacts'].items()]
    else:
        return False
    expected = {'run_attempt': attempt, 'head_sha': event_sha,
                'head_branch': 'main', 'path': WORKFLOW, 'event': 'workflow_dispatch',
                'status': 'completed', 'conclusion': 'failure'}
    if (type(run.get('run_attempt')) is not int
            or any(run.get(key) != value for key, value in expected.items())):
        return False
    if any(item['name'].startswith('generation-spend-reservation-')
           or item['name'].startswith('program-area-vectors-') and '-reservation-' in item['name']
           for item in artifacts):
        return False
    if sum(item['name'].startswith('candidate-') for item in artifacts) != 1:
        return False
    for identifier, name, digest in pins:
        matches = [item for item in artifacts if item.get('id') == identifier or item.get('name') == name]
        if (len(matches) != 1 or matches[0].get('id') != identifier or matches[0].get('name') != name
                or matches[0].get('digest') != 'sha256:' + digest or matches[0].get('expired') is not False):
            return False
    revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
                      'release/candidate-source.json').splitlines()
    for sha in revisions:
        pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
        child = json.loads(c.git(root, 'show', sha + ':release/candidate.json'))
        receipt = child.get('url_correction') or {}
        if (receipt.get('parent_candidate') != url.PARENT
                or child.get('derived_from_candidate') != url.PARENT):
            continue
        if sibling and c.encoded(receipt.get('superseded_url_correction')) != c.encoded(superseded):
            # Sharing the same parent never retires an unpublished sibling.
            # The reviewed v2 projection must carry its full authenticated proof.
            continue
        valid_identity = (child.get('candidate_id') == pointer.get('candidate_id')
            == c.digest(c.encoded({key: value for key, value in child.items() if key != 'candidate_id'})))
        prior = child.get('identity_correction') or {}
        producer = receipt.get('affected_generation') or {}
        parent_producer = prior.get('affected_generation') or {}
        if not (valid_identity and child.get('derived_from_candidate') == url.PARENT
                and child.get('generation_run_id') == '38275115281'
                and receipt.get('version') == url.VERSION and receipt.get('parent_run') == url.RUN
                and receipt.get('parent_manifest_sha256') == url.MANIFEST_SHA
                and producer.get('generation_run_id') == pointer.get('artifact_run')
                and parent_producer.get('generation_run_id') == str(url.RUN)
                and parent_producer.get('generation_run_attempt') == str(url.ATTEMPT)
                and parent_producer.get('generation_sha') == url.EVENT_SHA):
            raise Hold('Published URL-correction lineage does not authenticate its exact owner', run['id'])
        return True
    return False


def _require_reconciliation_history(repository, run, producers, artifacts, *, allowed_candidate_ids=None):
    """Original artifact producers remain distinct from downstream retries."""
    latest = run['run_attempt']
    attempts = {int(producer['run_attempt']): producer for producer in producers}
    if min(attempts) == latest:
        return
    if not repository:
        raise Hold('Original reconciliation attempt history is unavailable', run['id'])
    from tools.release_attempt_history import authenticate_attempt, require_downstream_only
    read = lambda path: api(repository, path)
    def matches(meta, producer):
        return producer == {'run_id': str(meta['id']), 'run_attempt': str(meta['run_attempt']),
                            'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']}
    try:
        acknowledged = max(attempts)
        for attempt, producer in attempts.items():
            if attempt < latest and (attempt != acknowledged or acknowledged == latest):
                if not matches(authenticate_attempt(repository, run, attempt, api=read), producer):
                    raise ValueError('Original checkpoint producer changed')
        if acknowledged < latest:
            options = {} if allowed_candidate_ids is None else {'allowed_candidate_ids': allowed_candidate_ids}
            original = require_downstream_only(repository, run, acknowledged, artifacts, api=read, **options)
            if not matches(original, attempts[acknowledged]):
                raise ValueError('Original checkpoint producer changed')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise Hold('Later release attempts do not authenticate unchanged reconciliation work: ' + str(error),
                   run['id']) from error


def _published_reconciliation_supersedes(root, run, artifacts, *, repository=None):
    """Retire one exact original owner through its protected corrected child."""
    candidates = [row for row in artifacts if row['name'].startswith('candidate-')]
    if len(candidates) != 1:
        return False
    artifact = candidates[0]
    parent = artifact['name'].removeprefix('candidate-')
    revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
                      'release/candidate-source.json').splitlines()
    for sha in revisions:
        child = json.loads(c.git(root, 'show', sha + ':release/candidate.json'))
        receipt = child.get('source_reconciliation') or {}
        if (receipt.get('parent_candidate_id') != parent or receipt.get('parent_run') != str(run['id'])
                or child.get('derived_from_candidate') != parent):
            continue
        pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
        producer = receipt.get('parent_producer') or {}
        original_attempt = receipt.get('parent_attempt')
        expected_producer = {'run_id': str(run['id']), 'run_attempt': original_attempt,
                            'head_sha': run.get('head_sha'), 'event': run.get('event'), 'path': WORKFLOW}
        pin = receipt.get('parent_artifact') or {}
        affected = receipt.get('affected_generation') or {}
        valid = (receipt.get('version') == 'catalog-source-reconciliation-1'
            and receipt.get('source_slug') == 'sam-gov'
            and child.get('derived_from_candidate') == parent
            and child.get('candidate_id') == pointer.get('candidate_id')
            == c.digest(c.encoded({k: v for k, v in child.items() if k != 'candidate_id'}))
            and run.get('head_branch') == 'main' and run.get('path') == WORKFLOW
            and run.get('status') == 'completed' and producer == expected_producer
            and type(run.get('run_attempt')) is int
            and re.fullmatch('[1-9][0-9]*', str(original_attempt)) is not None
            and 1 <= int(original_attempt) <= run['run_attempt']
            and receipt.get('parent_generation_sha') == child.get('generation_sha')
            and original_attempt == str(producer.get('run_attempt'))
            and pin == {'id': artifact.get('id'), 'name': artifact['name'],
                        'sha256': str(artifact.get('digest', '')).removeprefix('sha256:')}
            and artifact.get('expired') is False
            and re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')) is not None
            and affected.get('generation_run_id') == pointer.get('artifact_run')
            and affected.get('generation_sha') == child.get('assembly_sha')
            and re.fullmatch('[a-f0-9]{64}', receipt.get('parent_manifest_sha256', '')) is not None)
        if not valid:
            raise Hold('Published source reconciliation does not authenticate its exact original owner', run['id'])
        _require_reconciliation_history(repository, run, [producer], artifacts)
        return True
    return False


def _published_reconciliation_consumes(root, run, artifacts, *, repository=None, _source_boundary=None):
    """A corrected publication may consume exact earlier repair checkpoints."""
    vouchers = [row for row in artifacts if re.fullmatch(
        r'offline-ai-reconcile-[a-f0-9]{64}-reservation-' + str(run['id']) + r'-[1-9][0-9]*', row['name'])]
    if not vouchers and (run.get('event') != 'workflow_dispatch'
                         or not any(row['name'].startswith('candidate-') for row in artifacts)):
        return False
    def pin_matches(pin):
        return (isinstance(pin, dict) and re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')) is not None
            and any(row.get('id') == pin.get('id') and row.get('name') == pin.get('name')
                    and row.get('digest') == 'sha256:' + pin['sha256'] for row in artifacts))
    revisions = ([None] if _source_boundary is not None else
        c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
              'release/candidate-source.json').splitlines())
    for index, sha in enumerate(revisions):
        child = _source_boundary[0] if sha is None else json.loads(c.git(root, 'show', sha + ':release/candidate.json'))
        receipt = child.get('source_reconciliation') or {}
        if not receipt:
            continue
        links = [link for link in receipt.get('consumed_checkpoints', [])
                 if (link.get('producer') or {}).get('run_id') == str(run['id'])]
        affected = receipt.get('affected_generation') or {}
        pointer = _source_boundary[1] if sha is None else None
        # A first publication can assemble runtime around an unpublished source
        # child. Authenticate that exact private child before retiring its owner.
        if (child.get('derived_from_candidate') != receipt.get('parent_candidate_id')
                or affected.get('generation_sha') != child.get('assembly_sha')):
            source_id = child.get('derived_from_candidate')
            transporting = any(row['name'] == 'candidate-' + str(source_id) for row in artifacts)
            restoring = any(re.fullmatch(r'offline-ai-reconcile-' + re.escape(str(receipt.get('parent_candidate_id')))
                + '-state-' + str(run['id']) + r'-[1-9][0-9]*', row['name']) for row in artifacts)
            if affected.get('generation_run_id') != str(run['id']) and not links and not transporting and not restoring:
                continue
            pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
            if _later_reconciliation_publication(root, child, pointer, revisions[index + 1:]):
                continue
            child = _runtime_reconciliation_source(root, repository, run, artifacts, child, pointer, sha)
            receipt, affected = child['source_reconciliation'], child['source_reconciliation']['affected_generation']
            transporting = any(row['name'] == 'candidate-' + child['candidate_id'] for row in artifacts)
            # This is the authenticated source boundary behind the publication,
            # not a claim that its unchanged package was itself published.
            pointer = {'candidate_id': child['candidate_id'], 'artifact_run':
                str(run['id']) if transporting and not links else affected['generation_run_id']}
        own = affected.get('generation_run_id') == str(run['id'])
        if pointer is None:
            pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
        transport = pointer.get('artifact_run') == str(run['id']) and not own
        if not links and not own and not transport:
            continue
        parent = receipt.get('parent_candidate_id', '')
        valid = (receipt.get('version') == 'catalog-source-reconciliation-1'
            and receipt.get('source_slug') == 'sam-gov'
            and child.get('derived_from_candidate') == parent
            and child.get('candidate_id') == pointer.get('candidate_id')
            == c.digest(c.encoded({k: v for k, v in child.items() if k != 'candidate_id'}))
            and re.fullmatch('[1-9][0-9]*', str(affected.get('generation_run_id', ''))) is not None
            and re.fullmatch('[1-9][0-9]*', str(pointer.get('artifact_run', ''))) is not None
            and affected.get('generation_sha') == child.get('assembly_sha')
            and run.get('path') == WORKFLOW and run.get('head_branch') == 'main'
            and run.get('event') == 'workflow_dispatch' and run.get('status') == 'completed'
            and type(run.get('run_attempt')) is int)
        acknowledged = set()
        for link in links:
            producer = link['producer']
            valid = valid and (producer.get('head_sha') == run.get('head_sha')
                and producer.get('event') == run.get('event') and producer.get('path') == WORKFLOW
                and re.fullmatch('[1-9][0-9]*', producer.get('run_attempt', '')) is not None
                and int(producer['run_attempt']) <= run['run_attempt']
                and pin_matches(link.get('reservation')) and pin_matches(link.get('state'))
                and all(link[role]['name'] == f'offline-ai-reconcile-{parent}-{role}-{run["id"]}-{producer["run_attempt"]}'
                        for role in ('reservation', 'state'))
                and type(link.get('request_count')) is int and 0 <= link['request_count'] <= 300
                and type(link.get('charged_microusd')) is int and 0 <= link['charged_microusd'] <= 2_000_000
                and all(re.fullmatch('[a-f0-9]{64}', link.get(name, '')) is not None for name in
                        ('ledger_sha256', 'request_prefix_sha256', 'request_identity_prefix_sha256')))
            acknowledged.add(link.get('reservation', {}).get('id'))
            candidate = link.get('candidate')
            if candidate:
                valid = valid and (candidate.get('producer') == producer and pin_matches(candidate.get('artifact'))
                    and candidate['artifact'].get('name') == 'candidate-' + candidate.get('candidate_id', '')
                    and re.fullmatch('[a-f0-9]{64}', candidate.get('manifest_sha256', '')) is not None)
        # An unacknowledged reservation or candidate remains an owner. Later
        # state-only uploads cannot grant provider dispatch without a voucher.
        candidates = [row for row in artifacts if row['name'].startswith('candidate-')]
        covered = {link['candidate']['artifact']['id'] for link in links if link.get('candidate')}
        producers = [link['producer'] for link in links]
        restores = []
        if own:
            if not valid:
                raise Hold('Published source reconciliation does not authenticate its producing run', run['id'])
            producer, reservation, candidate, restores = _published_reconciliation_producer(
                root, repository, run, artifacts, child, receipt)
            producers.append(producer)
            acknowledged.add(reservation['id'])
            if candidate:
                covered.add(candidate['id'])
        elif transport:
            if not valid:
                raise Hold('Published source reconciliation does not authenticate its restoring run', run['id'])
            candidate, restores = _published_reconciliation_transport(root, repository, run, artifacts, child, receipt,
                after=max((int(producer['run_attempt']) for producer in producers), default=0))
            covered.add(candidate['id'])
        valid = valid and all(row['id'] in acknowledged for row in vouchers) and all(row['id'] in covered for row in candidates)
        if not valid:
            raise Hold('Published source reconciliation does not authenticate its consumed repair checkpoint', run['id'])
        if restores:
            _require_reconciliation_restore_history(repository, run, producers, restores, artifacts, covered)
        else:
            _require_reconciliation_history(repository, run, producers, artifacts,
                                            allowed_candidate_ids=covered)
        return True
    return False


def _later_reconciliation_publication(root, published, pointer, older_revisions):
    """Skip a later descendant only through its exact earlier protected parent."""
    def canonical(manifest, source):
        identifier = manifest.get('candidate_id')
        return (re.fullmatch('[a-f0-9]{64}', str(identifier)) is not None
            and identifier == source.get('candidate_id')
            == c.digest(c.encoded({key: value for key, value in manifest.items() if key != 'candidate_id'}))
            and re.fullmatch('[1-9][0-9]*', str(source.get('artifact_run', ''))) is not None)
    if not canonical(published, pointer):
        return False
    parent_id = published.get('derived_from_candidate')
    receipt = published['source_reconciliation']
    affected = receipt.get('affected_generation') or {}
    origin = ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
              'generation_dependencies', 'generator_versions', 'original_generation', 'source_reconciliation')
    for revision in older_revisions:
        parent = json.loads(c.git(root, 'show', revision + ':release/candidate.json'))
        if parent.get('candidate_id') != parent_id:
            continue
        source = json.loads(c.git(root, 'show', revision + ':release/candidate-source.json'))
        # A direct source child must still pass the private checkpoint proof.
        # Runtime and team descendants may change generated team bytes, so only
        # immutable source origin is compared before reaching that proof later.
        return (canonical(parent, source)
            and pointer.get('artifact_run') != affected.get('generation_run_id')
            and source.get('artifact_run') != affected.get('generation_run_id')
            and any(parent.get(key) != value for key, value in
                    (('derived_from_candidate', receipt.get('parent_candidate_id')),
                     ('assembly_sha', affected.get('generation_sha'))))
            and all(key in parent and key in published and parent[key] == published[key] for key in origin))
    return False


def _runtime_reconciliation_source(root, repository, run, artifacts, published, pointer, revision):
    """Prove published runtime bytes conserve the authenticated completed source."""
    try:
        assembly_parent = published.get('derived_from_candidate')
        receipt = published['source_reconciliation']; affected = receipt['affected_generation']
        attempt = affected['generation_run_attempt']
        if (not repository or re.fullmatch('[a-f0-9]{64}', str(assembly_parent)) is None
                or published.get('candidate_id') != pointer.get('candidate_id')
                or published['candidate_id'] != c.digest(c.encoded({key: value for key, value in published.items()
                                                                  if key != 'candidate_id'}))
                or re.fullmatch('[1-9][0-9]*', str(pointer.get('artifact_run', ''))) is None
                or pointer['artifact_run'] == affected.get('generation_run_id')
                or re.fullmatch('[1-9][0-9]*', str(affected.get('generation_run_id', ''))) is None
                or re.fullmatch('[1-9][0-9]*', str(attempt)) is None):
            raise ValueError('Invalid runtime descendant identity')
        source_run = affected['generation_run_id']
        owner = run if source_run == str(run['id']) else json.loads(api(repository, f'actions/runs/{source_run}'))
        if owner.get('id') != int(source_run):
            raise ValueError('Completed source producer identity changed')
        owned = artifacts if source_run == str(run['id']) else run_artifacts(source_run,
            lambda path: api(repository, path), repository=repository)
        name = f'offline-ai-reconcile-{receipt["parent_candidate_id"]}-state-{source_run}-{attempt}'
        states = [row for row in owned if row['name'] == name]
        if len(states) != 1:
            raise ValueError('Exact completed source checkpoint unavailable')
        documents = _reconciliation_documents(repository, owner, states[0], ['reconciliation.json'], complete_source=True)
        source_id = documents['reconciliation.json']['completed_candidate_id']
        path = 'complete-candidates/' + source_id + '/candidate.json'
        source, context = documents[path], documents['reconciliation.json']
        conserved = ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
            'generation_dependencies', 'generator_versions', 'generation_baseline', 'generation_files',
            'team_identity', 'semantic_identity', 'original_generation', 'source_reconciliation')
        if (source.get('candidate_id') != source_id or context.get('completed_candidate_id') != source_id
                or source_id != c.digest(c.encoded({key: value for key, value in source.items() if key != 'candidate_id'}))
                or source.get('derived_from_candidate') != receipt.get('parent_candidate_id')
                or source.get('assembly_sha') != affected.get('generation_sha')
                or any(key not in source or published.get(key) != source[key] for key in conserved)
                or any(published.get('dependency_groups', {}).get(group) != source.get('dependency_groups', {}).get(group)
                       or not source.get('dependency_groups', {}).get(group) for group in ('source', 'teams', 'semantic'))):
            raise ValueError('Runtime assembly changed source provenance or generation identity')
        generated = source['generation_files']
        if not isinstance(generated, dict) or not generated:
            raise ValueError('Completed source output inventory unavailable')
        for name, digest in generated.items():
            c.checked_path(root, name)
            if (source.get('files', {}).get(name) != digest or published.get('files', {}).get(name) != digest
                    or c.digest(subprocess.check_output(['git', '-C', str(root), 'show', revision + ':' + name],
                                                       stderr=subprocess.DEVNULL)) != digest):
                raise ValueError('Published generated bytes differ from the completed source child')
        if source_run != str(run['id']) and not _published_reconciliation_consumes(root, owner, owned,
                repository=repository, _source_boundary=(source,
                    {'candidate_id': source_id, 'artifact_run': source_run})):
            raise ValueError('Completed source owner is not fully covered by its checkpoint')
        return source
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise Hold('Published runtime assembly does not authenticate its completed source child: ' + str(error),
                   run['id']) from error


def _published_reconciliation_producer(root, repository, run, artifacts, child, receipt):
    """Authenticate the publishing attempt separately from restored checkpoints."""
    from tools.offline_spend import identity
    from tools.release_attempt_history import authenticate_attempt
    try:
        attempt = receipt['affected_generation']['generation_run_attempt']
        if (not repository or re.fullmatch('[1-9][0-9]*', str(attempt)) is None
                or not 1 <= int(attempt) <= run['run_attempt']):
            raise ValueError('Invalid published producer attempt')
        meta = authenticate_attempt(repository, run, int(attempt), api=lambda path: api(repository, path))
        producer = {'run_id': str(meta['id']), 'run_attempt': str(meta['run_attempt']),
                    'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']}
        parent = receipt['parent_candidate_id']
        names = {role: f'offline-ai-reconcile-{parent}-{role}-{run["id"]}-{attempt}'
                 for role in ('reservation', 'state')}
        if any(row['name'] == 'candidate-' + child['candidate_id'] for row in artifacts):
            names['candidate'] = 'candidate-' + child['candidate_id']
        selected = {}
        for role, name in names.items():
            rows = [row for row in artifacts if row['name'] == name]
            if len(rows) != 1:
                raise ValueError('Missing or conflicting producer ' + role)
            row = rows[0]; workflow = row.get('workflow_run') or {}
            if (row.get('expired') is not False or type(row.get('id')) is not int or row['id'] <= 0
                    or re.fullmatch('sha256:[a-f0-9]{64}', str(row.get('digest', ''))) is None
                    or workflow.get('id') != run['id'] or workflow.get('head_sha') != run['head_sha']
                    or workflow.get('head_branch') != 'main'):
                raise ValueError('Invalid producer artifact identity')
            selected[role] = row
        if any(row['workflow_run'] != selected['state']['workflow_run'] for row in selected.values()):
            raise ValueError('Producer artifact origins disagree')
        reservation = _reconciliation_documents(repository, run, selected['reservation'], ['reservation.json'])['reservation.json']
        candidate_path = 'complete-candidates/' + child['candidate_id'] + '/candidate.json'
        state = _reconciliation_documents(repository, run, selected['state'],
            ['reservation.json', 'ledger.json', 'reconciliation.json', candidate_path])
        context, ledger = state['reconciliation.json'], state['ledger.json']
        if (reservation != state['reservation.json']
                or reservation.get('version') != 'catalog-source-reconciliation-1'
                or reservation.get('producer_run') != str(run['id']) or reservation.get('producer_attempt') != str(attempt)
                or reservation.get('parent_candidate_id') != parent
                or reservation.get('operation_sha256') != receipt.get('operation_sha256')
                or re.fullmatch('[a-f0-9]{64}', str(reservation.get('prior_ledger_sha256', ''))) is None
                or context.get('completed_candidate_id') != child['candidate_id']
                or context.get('operation_sha256') != receipt.get('operation_sha256')
                or identity({key: value for key, value in context.items()
                             if key not in ('operation_sha256', 'completed_candidate_id')}) != context.get('operation_sha256')
                or any(context.get(key) != receipt.get(key) for key in
                       ('parent_candidate_id', 'parent_run', 'parent_attempt', 'parent_generation_sha', 'parent_manifest_sha256'))
                or ledger.get('logical_id') != 'offline-' + receipt.get('parent_run', '')
                or ledger.get('limit_microusd') != 2_000_000 or ledger.get('max_requests') != 300
                or identity(ledger) != receipt.get('ledger_sha256') or state[candidate_path] != child):
            raise ValueError('Published producer checkpoint does not match its exact receipt')
        restores = []
        for later in range(int(attempt) + 1, run['run_attempt'] + 1):
            name = f'offline-ai-reconcile-{parent}-state-{run["id"]}-{later}'
            rows = [row for row in artifacts if row['name'] == name]
            if not rows:
                continue
            voucher = name.replace('-state-', '-reservation-')
            if len(rows) != 1 or any(row['name'] == voucher for row in artifacts):
                raise ValueError('Later reconciliation work has a new or ambiguous allowance')
            row = rows[0]
            if row.get('workflow_run') != selected['state']['workflow_run']:
                raise ValueError('Completed restore artifact origin changed')
            candidate_path = 'complete-candidates/' + child['candidate_id'] + '/candidate.json'
            restored = _reconciliation_documents(repository, run, row,
                ['reservation.json', 'ledger.json', 'reconciliation.json', candidate_path])
            if (restored['reservation.json'] != reservation or restored['reconciliation.json'] != context
                    or identity(restored['ledger.json']) != receipt['ledger_sha256'] or restored[candidate_path] != child):
                raise ValueError('Completed restore changed candidate, context, or budget')
            later_meta = authenticate_attempt(repository, run, later, api=lambda path: api(repository, path))
            _require_completed_restore_jobs(root, repository, run, later_meta)
            restores.append({'producer': {'run_id': str(run['id']), 'run_attempt': str(later),
                'head_sha': later_meta['head_sha'], 'event': later_meta['event'], 'path': later_meta['path']}, 'state_id': row['id']})
        return producer, selected['reservation'], selected.get('candidate'), restores
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise Hold('Published source reconciliation does not authenticate its producing checkpoint: ' + str(error), run['id']) from error


def _published_reconciliation_transport(root, repository, run, artifacts, child, receipt, *, after):
    """An exact complete child may be reuploaded without becoming new generation."""
    from tools.offline_spend import identity
    from tools.release_attempt_history import authenticate_attempt
    try:
        if not repository:
            raise ValueError('Restoring run history unavailable')
        candidates = [row for row in artifacts if row['name'] == 'candidate-' + child['candidate_id']]
        if len(candidates) != 1 or _reconciliation_documents(repository, run, candidates[0], ['candidate.json'])['candidate.json'] != child:
            raise ValueError('Restoring candidate is not the exact published child')
        parent = receipt['parent_candidate_id']; affected = receipt['affected_generation']
        pattern = re.compile(f'offline-ai-reconcile-{parent}-state-{run["id"]}-([1-9][0-9]*)')
        restores = []
        for row in artifacts:
            match = pattern.fullmatch(row['name'])
            if not match or int(match[1]) <= after:
                continue
            attempt = int(match[1])
            if (attempt > run['run_attempt'] or len([item for item in artifacts if item['name'] == row['name']]) != 1
                    or any(item['name'] == row['name'].replace('-state-', '-reservation-') for item in artifacts)):
                raise ValueError('Restoring run has new or ambiguous accounting')
            candidate_path = 'complete-candidates/' + child['candidate_id'] + '/candidate.json'
            state = _reconciliation_documents(repository, run, row,
                ['reservation.json', 'ledger.json', 'reconciliation.json', candidate_path])
            reservation, context, ledger = (state[name] for name in ('reservation.json', 'reconciliation.json', 'ledger.json'))
            if (reservation.get('version') != 'catalog-source-reconciliation-1'
                    or reservation.get('producer_run') != affected.get('generation_run_id')
                    or reservation.get('producer_attempt') != affected.get('generation_run_attempt')
                    or reservation.get('parent_candidate_id') != parent
                    or reservation.get('operation_sha256') != receipt.get('operation_sha256')
                    or re.fullmatch('[a-f0-9]{64}', str(reservation.get('prior_ledger_sha256', ''))) is None
                    or context.get('completed_candidate_id') != child['candidate_id']
                    or context.get('operation_sha256') != receipt.get('operation_sha256')
                    or identity({key: value for key, value in context.items()
                                 if key not in ('operation_sha256', 'completed_candidate_id')}) != context.get('operation_sha256')
                    or any(context.get(key) != receipt.get(key) for key in
                           ('parent_candidate_id', 'parent_run', 'parent_attempt', 'parent_generation_sha', 'parent_manifest_sha256'))
                    or ledger.get('logical_id') != 'offline-' + receipt.get('parent_run', '')
                    or ledger.get('limit_microusd') != 2_000_000 or ledger.get('max_requests') != 300
                    or identity(ledger) != receipt.get('ledger_sha256') or state[candidate_path] != child):
                raise ValueError('Restoring run changed completed child or original accounting')
            meta = authenticate_attempt(repository, run, attempt, api=lambda path: api(repository, path))
            _require_completed_restore_jobs(root, repository, run, meta)
            restores.append({'producer': {'run_id': str(run['id']), 'run_attempt': str(attempt),
                'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']}, 'state_id': row['id']})
        if not restores:
            raise ValueError('Exact completed-child restore checkpoint unavailable')
        return candidates[0], restores
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise Hold('Published source reconciliation does not authenticate its restoring checkpoint: ' + str(error), run['id']) from error


def _reconciliation_documents(repository, run, artifact, expected, *, complete_source=False):
    from tools import release_checkpoint_archive as archive
    workflow = artifact.get('workflow_run') or {}
    if (artifact.get('expired') is not False or type(artifact.get('id')) is not int
            or re.fullmatch('sha256:[a-f0-9]{64}', str(artifact.get('digest', ''))) is None
            or workflow.get('id') != run['id'] or workflow.get('head_sha') != run['head_sha']
            or workflow.get('head_branch') != 'main'):
        raise ValueError('Invalid reconciliation checkpoint identity')
    raw = artifact_bytes(repository, str(run['id']), artifact, lambda path: api(repository, path))
    if c.digest(raw) != artifact['digest'].removeprefix('sha256:'):
        raise ValueError('Producer artifact digest changed')
    with archive._members(raw) as packet:
        def document(name):
            if packet.getinfo(name).file_size > archive.MAX_MANIFEST_BYTES:
                raise ValueError('Producer checkpoint JSON exceeds bound')
            value = archive._decode(packet.read(name))
            if not isinstance(value, dict):
                raise ValueError('Producer checkpoint JSON must be an object')
            return value
        result = {name: document(name) for name in expected}
        if complete_source:
            identifier = result['reconciliation.json'].get('completed_candidate_id')
            if re.fullmatch('[a-f0-9]{64}', str(identifier)) is None:
                raise ValueError('Completed source identity unavailable')
            name = 'complete-candidates/' + identifier + '/candidate.json'
            result[name] = document(name)
        return result


def _require_completed_restore_jobs(root, repository, run, meta):
    from tools import release_attempt_history as history
    jobs = history._jobs(run, meta, api=lambda path: api(repository, path), full=False)
    job = jobs.get('catalog-reconcile') or {}
    if (job.get('conclusion') != 'success'
            or any(row['conclusion'] != 'skipped' and name not in history.DOWNSTREAM | {'catalog-reconcile'}
                   for name, row in jobs.items())):
        raise ValueError('Later reconciliation did not only restore its completed checkpoint')
    workflow = yaml.safe_load(c.git(root, 'show', meta['head_sha'] + ':' + WORKFLOW))
    declared = workflow['jobs']['catalog-reconcile']['steps']
    guarded = [step['name'] for step in declared if step.get('if') == "steps.restore.outputs.candidate_id == ''"]
    restore = [step['name'] for step in declared if step.get('id') == 'restore']
    uploads = [step['name'] for step in declared if step.get('if') == 'always()'
               and '-state-' in step.get('with', {}).get('name', '')]
    steps = job.get('steps')
    if not isinstance(steps, list) or len(steps) > 100:
        raise ValueError('Completed restore step evidence unavailable')
    by_name = {}
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get('name'), str)
                or step['name'] in by_name or step.get('status') != 'completed'):
            raise ValueError('Completed restore step evidence is incomplete or ambiguous')
        by_name[step['name']] = step
    if (len(guarded) < 6 or len(restore) != 1 or len(uploads) != 1
            or any(by_name.get(name, {}).get('conclusion') != 'skipped' for name in guarded)
            or any(by_name.get(name, {}).get('conclusion') != 'success' for name in restore + uploads)):
        raise ValueError('Completed restore did not skip every reservation and generation step')


def _require_reconciliation_restore_history(repository, run, producers, restores, artifacts, covered):
    """Keep ordinary downstream rules, admitting only proved completed restores."""
    from tools import release_attempt_history as history
    read = lambda path: api(repository, path)
    try:
        history._inventory(repository, run, artifacts, api=read)
        if {row['id'] for row in artifacts if row['name'].startswith('candidate-')} != covered:
            raise ValueError('Competing candidate evidence')
        original = {int(producer['run_attempt']): producer for producer in producers}
        restored = {int(row['producer']['run_attempt']): row for row in restores}
        for artifact in artifacts:
            if '-reservation-' in artifact['name'] or '-state-' in artifact['name']:
                match = re.search(r'-' + str(run['id']) + r'-([1-9][0-9]*)$', artifact['name'])
                if (not match or int(match[1]) > max(original, default=0)
                        and artifact['id'] != restored.get(int(match[1]), {}).get('state_id')):
                    raise ValueError('Unacknowledged allowance or task accounting')
        for attempt in range(min(original, default=1), run['run_attempt'] + 1):
            meta = history.authenticate_attempt(repository, run, attempt, api=read)
            expected = original.get(attempt) or restored.get(attempt, {}).get('producer')
            if expected:
                if expected != {'run_id': str(meta['id']), 'run_attempt': str(meta['run_attempt']),
                                'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']}:
                    raise ValueError('Reconciliation producer changed')
            elif any(job['conclusion'] != 'skipped' and name not in history.DOWNSTREAM
                     for name, job in history._jobs(run, meta, api=read, full=False).items()):
                raise ValueError('Later generation or correction work started')
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        raise Hold('Later release attempts do not authenticate completed reconciliation restore: ' + str(error), run['id']) from error


def _only_preflight_stops(repository, run, jobs):
    """A repeated source preflight may fail without ever starting generation."""
    attempt = run.get('run_attempt')
    if type(attempt) is not int or not 1 < attempt <= 10:
        return False
    def stopped(rows):
        preflight = [job for job in rows if job.get('name') == 'sam-preflight']
        producers = [job for job in rows if job.get('name') in ('generate', 'assemble')]
        other = [job for job in rows if job.get('name') in ('catalog-reconcile', 'catalog-correction',
            'program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction',
            'catalog-identity-correction', 'catalog-url-correction')]
        return (len(preflight) == 1 and preflight[0].get('conclusion') in ('failure', 'cancelled')
                and len(producers) == 2 and all(job.get('conclusion') == 'skipped' for job in producers + other))
    if not stopped(jobs):
        return False
    return all(stopped([job for batch in _pages(repository,
        f'actions/runs/{run["id"]}/attempts/{prior}/jobs', 'jobs') for job in batch])
        for prior in range(1, attempt))


def prior_generation(root, environment, manifest):
    """Find one unfinished owner after the current source generation, or hold."""
    from tools.runtime_assembly_history import no_generation_allowance
    from tools.program_area_history import published_consumes as program_area_consumes
    repository = environment['GITHUB_REPOSITORY']
    floor, current = int(manifest['generation_run_id']), int(environment['GITHUB_RUN_ID'])
    published = _published(root)
    owners = []
    boundary = False
    for rows in _pages(repository, 'actions/workflows/refresh-opportunities.yml/runs?branch=main', 'workflow_runs'):
        for run in rows:
            identifier = int(run['id'])
            if identifier <= floor:
                boundary = True
                continue
            if identifier >= current:
                continue
            if (run.get('path') != WORKFLOW or run.get('head_branch') != 'main'
                    or run.get('event') not in ('push', 'schedule', 'workflow_dispatch')):
                raise Hold('Untrusted release run in recovery history', identifier)
            artifacts = run_artifacts(identifier, lambda path: api(repository, path), repository=repository)
            try:
                unpublished = any(row['name'].startswith('candidate-')
                    and (str(identifier), row['name'].removeprefix('candidate-')) not in published for row in artifacts)
                if unpublished and no_generation_allowance(root, repository, run, artifacts,
                                                           api=lambda path: api(repository, path)):
                    continue
            except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
                raise Hold('Prior runtime assembly does not authenticate zero-spend reuse: ' + str(error), identifier) from error
            if _published_reconciliation_consumes(root, run, artifacts, repository=repository):
                continue
            if program_area_consumes(root, run, artifacts, repository=repository):
                continue
            candidates = [a for a in artifacts if a['name'].startswith('candidate-')]
            reservations = [a for a in artifacts
                            if a['name'].startswith(f'generation-spend-reservation-{identifier}-')
                            or re.fullmatch(r'program-area-vectors-[a-f0-9]{64}-reservation-'
                                            + str(identifier) + r'-[1-9][0-9]*', a['name'])
                            or re.fullmatch(r'offline-ai-program-area-[a-f0-9]{64}-reservation-'
                                            + str(identifier) + r'-[1-9][0-9]*', a['name'])]
            if len(candidates) > 1:
                raise Hold('Multiple candidate identities require an exact named recovery', identifier)
            if candidates:
                artifact = candidates[0]
                candidate_id = artifact['name'].removeprefix('candidate-')
                if (str(identifier), candidate_id) in published:
                    continue
                if (_published_access_supersedes(root, run, artifacts)
                        or _published_url_supersedes(root, run, artifacts)
                        or _published_reconciliation_supersedes(root, run, artifacts, repository=repository)):
                    continue
                if artifact.get('expired') or not re.fullmatch('[a-f0-9]{64}', candidate_id):
                    raise Hold('Unpublished candidate evidence is expired or invalid', identifier)
                owners.append((str(identifier), candidate_id))
            elif reservations:
                raise Hold('Generation reserved its allowance but no complete candidate is retained; recover this original run', identifier)
            elif run.get('status') == 'completed':
                jobs = [job for batch in _pages(repository, f'actions/runs/{identifier}/jobs', 'jobs') for job in batch]
                # A superseded concurrency-queued run may be cancelled before
                # creating any job. Only an explicit first attempt with no
                # retained evidence can prove that it never started spending.
                if (run.get('conclusion') == 'cancelled' and type(run.get('run_attempt')) is int
                        and run['run_attempt'] == 1 and not jobs and not artifacts):
                    continue
                if _only_preflight_stops(repository, run, jobs):
                    continue
                producers = [job for job in jobs if job.get('name') in ('generate', 'assemble')]
                corrections = [job for job in jobs if job.get('name') in ('catalog-reconcile', 'program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction', 'catalog-identity-correction', 'catalog-url-correction')]
                if (int(run.get('run_attempt', 1)) > 1 or len(producers) != 2 or len(corrections) > 6
                        or any(job.get('conclusion') != 'skipped' for job in producers + corrections)):
                    raise Hold('Prior generation has no complete accounting/candidate evidence; inspect its original run', identifier)
            else:
                raise Hold('Prior generation is still pending; preserve its original allowance', identifier)
        if boundary:
            break
    if not boundary:
        raise Hold('Source-generation boundary is missing from the retained workflow history')
    if len(owners) > 1:
        raise Hold('Multiple unfinished generation runs require a named recovery: ' + ', '.join(run for run, _ in owners))
    return owners[0] if owners else None


def completed_live(manifest, live, publication):
    """An intermediate asset check must not stand in for complete live proof."""
    from tools.plan_release import publication_ready
    if not publication_ready(manifest, publication) or not live:
        return False
    return (live.get('verified') is True and live.get('candidate_id') == manifest['candidate_id']
            and live.get('asset_verification') == live.get('provider_smoke') == 'success'
            and isinstance(live.get('completed_at'), str)
            and live.get('publication_sha') == publication['receipt']['publication_sha']
            and live.get('publication_receipt_sha256') == c.digest(c.encoded(publication['receipt']))
            and live.get('live_release_identity') == manifest['release_identity'])


def hold_competing_generation(root, environment, result):
    """Keep automatic paid work behind its unfinished owner, without daily policy."""
    try:
        manifest = c.read_json(Path(root) / 'release/candidate.json')
        if manifest.get('candidate_id') != c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'})):
            raise Hold('Protected candidate identity is invalid')
        owner = prior_generation(root, environment, manifest)
        if owner:
            raise Hold('An unpublished candidate retains the generation allowance; recover its original run', owner[0])
        return result
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        run = getattr(error, 'run', '')
        detail = str(error).replace('\r', ' ').replace('\n', ' ')[:300]
        owner = f' Original run: {run}.' if run else ''
        return result | {'stage': 'noop', 'held_stage': result['stage'], 'recovery_run': run,
                         'reason': 'Automatic generation held: ' + detail + owner}


def _recover(root, environment, result, destination, run, identifier, reports, fields, now):
    fields['recovery_run'] = str(run)
    bundle = Path(destination) / 'recovery-candidate'
    fetch(environment['GITHUB_REPOSITORY'], run, 'candidate-' + identifier, bundle)
    manifest = c.load(bundle, identifier)
    fields.update(candidate_id=identifier, candidate_run=str(run))
    c.verify_dependencies(root, manifest)
    current = snapshot(root)
    changes = unpublished_input_changes(manifest,
        changed_groups(candidate_groups(root, manifest), current), current)
    if set(changes) - {'validation'}:
        raise Hold('Retained candidate inputs changed; preserve it for a named recovery', run)
    stamp = catalog_generated_at(bundle / 'files', manifest)
    if utc_timestamp(stamp) > now:
        raise Hold('Retained candidate has a future source timestamp', run)
    fields.update(catalog_generated_at=stamp, recovery_run=str(run))
    repository = environment['GITHUB_REPOSITORY']
    receipt_run, receipt = reports(repository, identifier, 'validation', Path(destination) / 'recovery-validation')
    if (receipt and receipt.get('identity') == c.validation_identity(root, manifest)
            and receipt.get('gates') != {gate: 'passed' for gate in c.GATES}):
        raise Hold('Retained candidate failed unchanged validation; repair the reported findings before another full gate', run)
    _, publication = reports(repository, identifier, 'publication', Path(destination) / 'recovery-publication')
    from tools.plan_release import publication_ready
    published = publication_ready(manifest, publication)
    if not published:
        _, review = reports(repository, identifier, 'review', Path(destination) / 'recovery-review')
        if review and review.get('status') == 'review_findings':
            if (review.get('candidate_id') != identifier or review.get('artifact_run') != str(run)
                    or review.get('repository') != repository or review.get('production_mutated') is not False
                    or type(review.get('pr_number')) is not int or review['pr_number'] <= 0
                    or not re.fullmatch('[a-f0-9]{40}', review.get('head_sha', ''))):
                raise Hold('Terminal review checkpoint does not match the retained candidate', run)
            raise Hold(f"Retained candidate has terminal review findings in PR #{review['pr_number']}; "
                       'repair its source/code inputs before publication retry', run)
    return result | fields | {'stage': 'verify' if published else 'publish', 'daily_status': 'recovering',
        'candidate_id': identifier, 'candidate_run': str(run), 'receipt_run': receipt_run,
        'publication_run': publication['run'] if published else '',
        'publication_attempt': publication['attempt'] if published else '',
        'reason': f'Resume retained candidate from run {run}; no new generation allowance'}


def resolve(root, environment, result, destination, *, live=None, publication=None,
            explicit_resume=False, reports=None, now=None):
    """Apply only to automatic scheduled planning, under the existing release lock."""
    if reports is None:
        from tools.plan_release import latest_report
        reports = latest_report
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = daily_window(now)
    fields = {'daily_window_start': iso(start), 'catalog_generated_at': '', 'recovery_run': ''}
    try:
        if explicit_resume:
            return _recover(root, environment, result, destination, result['candidate_run'],
                            result['candidate_id'], reports, fields, now)
        manifest = c.read_json(Path(root) / 'release/candidate.json')
        if manifest.get('candidate_id') != c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'})):
            raise Hold('Protected candidate identity is invalid')
        owner = prior_generation(root, environment, manifest)
        if owner:
            return _recover(root, environment, result, destination, *owner, reports, fields, now)
        stamp = catalog_generated_at(root, manifest)
        fields['catalog_generated_at'] = stamp
        generated = utc_timestamp(stamp)
        if generated > now:
            raise Hold('Published source timestamp is in the future')
        verified = completed_live(manifest, live, publication)
        affected = set(result.get('changes', {})) - {'validation', 'runtime'}
        if result.get('runtime_changes'):
            affected.add('runtime')
        if verified and generated >= start and not affected:
            return result | fields | {'stage': 'noop', 'daily_status': 'already_current', 'live_verified': True,
                'reason': 'This daily window already has a source refresh with exact completed live verification'}
        if verified and generated >= start:
            from tools.plan_release import decide
            stage = decide(result.get('changes', {}), event='push', verified=True,
                           receipt_current=result.get('receipt_current', False),
                           runtime_changed=bool(result.get('runtime_changes')), published=True,
                           qualification_hold=result.get('qualification_hold', False),
                           team_generation_ready=result.get('team_generation_ready', True))
            return result | fields | {'stage': stage, 'daily_status': 'held' if stage == 'noop' else 'due',
                'reason': 'Daily source refresh is verified; apply the current dependency changes using the ordinary release stage'}
        if not verified:
            return _recover(root, environment, result, destination, result['candidate_run'],
                            result['candidate_id'], reports, fields, now)
        if result['stage'] == 'noop':
            return result | fields | {'daily_status': 'held'}
        return result | fields | {'daily_status': 'due'}
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        fields['recovery_run'] = getattr(error, 'run', '') or fields['recovery_run']
        detail = str(error).replace('\r', ' ').replace('\n', ' ')[:300]
        owner = f" Original run: {fields['recovery_run']}." if fields['recovery_run'] else ''
        return result | fields | {'stage': 'noop', 'daily_status': 'held',
            'reason': 'Scheduled refresh held: ' + detail + owner}
