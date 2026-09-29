"""Read-only daily release selection; a retry never creates another allowance."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

from tools import release_candidate as c
from tools.fetch_release_artifact import fetch
from tools.offline_ai_checkpoint import api
from tools.release_dependencies import candidate_groups, changed_groups, snapshot

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
            artifacts = [item for batch in _pages(repository, f'actions/runs/{identifier}/artifacts', 'artifacts')
                         for item in batch]
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
                producers = [job for job in jobs if job.get('name') in ('generate', 'assemble')]
                corrections = [job for job in jobs if job.get('name') == 'program-area-revalidation']
                if (int(run.get('run_attempt', 1)) > 1 or len(producers) != 2 or len(corrections) > 1
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


def _recover(root, environment, result, destination, run, identifier, reports, fields, now):
    fields['recovery_run'] = str(run)
    bundle = Path(destination) / 'recovery-candidate'
    fetch(environment['GITHUB_REPOSITORY'], run, 'candidate-' + identifier, bundle)
    manifest = c.load(bundle, identifier)
    c.verify_dependencies(root, manifest)
    if set(changed_groups(candidate_groups(root, manifest), snapshot(root))) - {'validation'}:
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
