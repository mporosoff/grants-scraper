"""Read-only daily release selection; a retry never creates another allowance."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

from tools import release_candidate as c
from tools.fetch_release_artifact import fetch, run_artifacts
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


def _published_reconciliation_supersedes(root, run, artifacts):
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
        expected_producer = {'run_id': str(run['id']), 'run_attempt': str(run.get('run_attempt')),
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
            and receipt.get('parent_generation_sha') == child.get('generation_sha')
            and receipt.get('parent_attempt') == str(run['run_attempt'])
            and pin == {'id': artifact.get('id'), 'name': artifact['name'],
                        'sha256': str(artifact.get('digest', '')).removeprefix('sha256:')}
            and artifact.get('expired') is False
            and re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')) is not None
            and affected.get('generation_run_id') == pointer.get('artifact_run')
            and affected.get('generation_sha') == child.get('assembly_sha')
            and re.fullmatch('[a-f0-9]{64}', receipt.get('parent_manifest_sha256', '')) is not None)
        if not valid:
            raise Hold('Published source reconciliation does not authenticate its exact original owner', run['id'])
        return True
    return False


def _published_reconciliation_consumes(root, run, artifacts):
    """A corrected publication may consume exact earlier repair checkpoints."""
    vouchers = [row for row in artifacts if re.fullmatch(
        r'offline-ai-reconcile-[a-f0-9]{64}-reservation-' + str(run['id']) + r'-[1-9][0-9]*', row['name'])]
    if not vouchers:
        return False
    def pin_matches(pin):
        return (isinstance(pin, dict) and re.fullmatch('[a-f0-9]{64}', pin.get('sha256', '')) is not None
            and any(row.get('id') == pin.get('id') and row.get('name') == pin.get('name')
                    and row.get('digest') == 'sha256:' + pin['sha256'] for row in artifacts))
    revisions = c.git(root, 'log', '--first-parent', '--format=%H', '-100', '--',
                      'release/candidate-source.json').splitlines()
    for sha in revisions:
        child = json.loads(c.git(root, 'show', sha + ':release/candidate.json'))
        receipt = child.get('source_reconciliation') or {}
        links = [link for link in receipt.get('consumed_checkpoints', [])
                 if (link.get('producer') or {}).get('run_id') == str(run['id'])]
        if not links:
            continue
        pointer = json.loads(c.git(root, 'show', sha + ':release/candidate-source.json'))
        parent = receipt.get('parent_candidate_id', '')
        affected = receipt.get('affected_generation') or {}
        valid = (receipt.get('version') == 'catalog-source-reconciliation-1'
            and receipt.get('source_slug') == 'sam-gov'
            and child.get('derived_from_candidate') == parent
            and child.get('candidate_id') == pointer.get('candidate_id')
            == c.digest(c.encoded({k: v for k, v in child.items() if k != 'candidate_id'}))
            and affected.get('generation_run_id') == pointer.get('artifact_run')
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
        covered = {link.get('candidate', {}).get('artifact', {}).get('id') for link in links}
        valid = valid and all(row['id'] in acknowledged for row in vouchers) and all(row['id'] in covered for row in candidates)
        if not valid:
            raise Hold('Published source reconciliation does not authenticate its consumed repair checkpoint', run['id'])
        return True
    return False


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
            if _published_reconciliation_consumes(root, run, artifacts):
                continue
            candidates = [a for a in artifacts if a['name'].startswith('candidate-')]
            reservations = [a for a in artifacts
                            if a['name'].startswith(f'generation-spend-reservation-{identifier}-')
                            or re.fullmatch(r'program-area-vectors-[a-f0-9]{64}-reservation-'
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
                        or _published_reconciliation_supersedes(root, run, artifacts)):
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
