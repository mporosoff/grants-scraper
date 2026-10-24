"""Safe, same-run SAM preflight receipts; replay never makes a network request."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from . import sam_reviewed
from .sam_api import NOTICE_ID, SamError
from .sam_public import digest, fetch_notice

MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_AGE = timedelta(hours=2)
KIND = 'sam-reviewed-preflight'
RECEIPT_FIELDS = {'schema_version', 'kind', 'completed', 'outcome', 'config_sha256', 'release_sha',
                  'github_sha', 'run_id', 'run_attempt', 'as_of', 'checked_at', 'snapshots',
                  'failed_reads', 'diagnostics'}
FAILED_READ_FIELDS = {'request_count', 'http_status', 'failure_class', 'endpoint'}


def utc_now():
    return datetime.now(timezone.utc)


def checkout_sha(root):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                            text=True, capture_output=True, timeout=10)
    return result.stdout.strip()


def config_and_binding(config_path, as_of, environment):
    config_path = Path(config_path).resolve()
    raw = config_path.read_bytes()
    if len(raw) > MAX_RECEIPT_BYTES or not isinstance(as_of, date):
        raise ValueError('Invalid preflight configuration or date')
    config = sam_reviewed.validate_config(json.loads(raw.decode('utf8')))
    actual = checkout_sha(config_path.parent.parent)
    release = environment.get('SAM_PREFLIGHT_RELEASE_SHA') or actual
    event = environment.get('GITHUB_SHA') or None
    run = environment.get('GITHUB_RUN_ID') or None
    attempt = environment.get('GITHUB_RUN_ATTEMPT') or None
    if (not re.fullmatch('[a-f0-9]{40}', release) or release != actual
            or event is not None and not re.fullmatch('[a-f0-9]{40}', event)
            or run is not None and not re.fullmatch('[1-9][0-9]{0,19}', run)
            or attempt is not None and not re.fullmatch('[1-9][0-9]{0,8}', attempt)
            or environment.get('GITHUB_ACTIONS') == 'true' and not all((run, attempt, event,
                environment.get('SAM_PREFLIGHT_RELEASE_SHA')))):
        raise ValueError('SAM preflight checkout or run identity does not match')
    return config, {'config_sha256': hashlib.sha256(raw).hexdigest(), 'release_sha': release,
                    'github_sha': event, 'run_id': run, 'run_attempt': attempt, 'as_of': as_of.isoformat()}


def validate_snapshot(notice, identifier):
    if (not isinstance(notice, dict) or set(notice) != sam_reviewed.SNAPSHOT_FIELDS
            or not isinstance(identifier, str) or not NOTICE_ID.fullmatch(identifier)
            or notice['notice_id'] != identifier
            or not isinstance(notice['latest_notice_id'], str) or not NOTICE_ID.fullmatch(notice['latest_notice_id'])
            or any(type(notice[key]) is not bool for key in ('latest', 'archived', 'cancelled', 'deleted'))
            or notice['latest'] and notice['latest_notice_id'] != identifier
            or digest({key: value for key, value in notice.items() if key != 'review_sha256'}) != notice['review_sha256']):
        raise ValueError('Invalid safe SAM preflight snapshot')
    for key in sam_reviewed.SNAPSHOT_FIELDS - {'latest', 'archived', 'cancelled', 'deleted', 'naics_codes', 'set_asides'}:
        if notice[key] is not None and not sam_reviewed.text(notice[key], 2000):
            raise ValueError('Invalid SAM preflight field')
    for key in ('description_sha256', 'resources_sha256', 'review_sha256'):
        if not isinstance(notice[key], str) or not re.fullmatch('[a-f0-9]{64}', notice[key]):
            raise ValueError('Invalid SAM preflight digest')
    for key in ('naics_codes', 'set_asides'):
        if (not isinstance(notice[key], list) or len(notice[key]) > 30
                or any(not sam_reviewed.text(value, 100) for value in notice[key])):
            raise ValueError('Invalid SAM preflight list')


def safe_failed_read(detail):
    """Retain only bounded transport facts, never an exception or response body."""
    count, status = detail.get('request_count', 0), detail.get('http_status')
    failure_class, endpoint = detail.get('failure_class', 'invalid_client'), detail.get('endpoint')
    if type(count) is not int or not 0 <= count <= 4:
        count, failure_class = 0, 'invalid_client'
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        status, failure_class = None, 'invalid_client'
    if failure_class not in sam_reviewed.FAILURE_CLASSES:
        failure_class = 'invalid_client'
    if endpoint not in {None, 'notice', 'resources', 'snapshot'}:
        endpoint, failure_class = None, 'invalid_client'
    if (failure_class == 'transient_transport' and status is not None
            and status not in {403, 429} and not 500 <= status <= 599
            or failure_class == 'timeout' and status is not None):
        failure_class = 'invalid_client'
    return {'request_count': count, 'http_status': status,
            'failure_class': failure_class, 'endpoint': endpoint}


def receipt_outcome(diagnostics):
    return 'verified_degraded' if diagnostics['outcome'] == 'degraded' else 'verified'


def build_receipt(config_path, as_of, *, environment=None, client=None, checked_at=None):
    checked_at = utc_now() if checked_at is None else checked_at
    if checked_at.utcoffset() != timedelta(0) or checked_at.date() != as_of:
        raise ValueError('SAM preflight timestamp must match its UTC source date')
    environment = os.environ if environment is None else environment
    config, binding = config_and_binding(config_path, as_of, environment)
    client = fetch_notice if client is None else client
    snapshots, failed_reads = {}, {}

    def capture(identifier):
        try:
            notice, detail = client(identifier)
            try:
                validate_snapshot(notice, identifier)
            except (ValueError, TypeError, KeyError):
                raise SamError('invalid_preflight_snapshot', {
                    'request_count': detail.get('request_count', 0), 'failure_class': 'validation_failure'}) from None
        except SamError as error:
            failed_reads[identifier] = safe_failed_read(error.diagnostics)
            raise SamError('public_notice_unavailable', failed_reads[identifier]) from None
        except Exception:
            failed_reads[identifier] = safe_failed_read({'failure_class': 'invalid_client'})
            raise SamError('public_notice_unavailable', failed_reads[identifier]) from None
        snapshots[identifier] = deepcopy(notice)
        return notice, detail

    _, diagnostics = sam_reviewed.collect(config, as_of, {}, client=capture)
    sam_reviewed.require_reviewed_observations(config, diagnostics)
    return {'schema_version': 2, 'kind': KIND, 'completed': True, 'outcome': receipt_outcome(diagnostics),
            **binding, 'checked_at': checked_at.isoformat(), 'snapshots': snapshots,
            'failed_reads': failed_reads, 'diagnostics': diagnostics}


def replay_client(receipt_path, config_path, as_of, *, environment=None, now=None):
    """Authenticate local checkout/run bindings and recheck admission, without I/O."""
    environment = os.environ if environment is None else environment
    now = utc_now() if now is None else now
    if now.utcoffset() != timedelta(0) or as_of != now.date():
        raise ValueError('SAM preflight admission must use the current UTC date')
    config, binding = config_and_binding(config_path, as_of, environment)
    with Path(receipt_path).open('rb') as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('SAM preflight receipt exceeds its bound')
    receipt = json.loads(raw.decode('utf8'))
    if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS
            or type(receipt['schema_version']) is not int or receipt['schema_version'] != 2
            or receipt['kind'] != KIND or receipt['completed'] is not True
            or receipt['outcome'] not in {'verified', 'verified_degraded'}
            or any(receipt[key] != value for key, value in binding.items() if key != 'as_of')
            or not isinstance(receipt['snapshots'], dict)
            or len(receipt['snapshots']) > 2 * sam_reviewed.MAX_APPROVALS
            or not isinstance(receipt['failed_reads'], dict)
            or len(receipt['failed_reads']) > sam_reviewed.MAX_APPROVALS
            or not isinstance(receipt['diagnostics'], dict)):
        raise ValueError('SAM preflight receipt is incomplete or belongs to different inputs')
    checked_at = datetime.fromisoformat(receipt['checked_at'])
    original_as_of = sam_reviewed.iso(receipt['as_of'])
    if (checked_at.utcoffset() != timedelta(0) or original_as_of != checked_at.date()
            or not timedelta(0) <= now - checked_at <= MAX_RECEIPT_AGE):
        raise ValueError('SAM preflight receipt is stale or has an invalid source timestamp')
    snapshots = receipt['snapshots']
    failed_reads = receipt['failed_reads']
    if set(snapshots) & set(failed_reads):
        raise ValueError('SAM preflight read has conflicting outcomes')
    for identifier, notice in snapshots.items():
        validate_snapshot(notice, identifier)
    for identifier, failure in failed_reads.items():
        if (not isinstance(identifier, str) or not NOTICE_ID.fullmatch(identifier)
                or not isinstance(failure, dict) or set(failure) != FAILED_READ_FIELDS
                or safe_failed_read(failure) != failure):
            raise ValueError('Invalid safe SAM preflight failed read')
    read_ids = set()

    def read(identifier):
        read_ids.add(identifier)
        if identifier in failed_reads:
            raise SamError('public_notice_unavailable', dict(failed_reads[identifier], request_count=0))
        if identifier not in snapshots:
            raise SamError('missing_preflight_snapshot', {'request_count': 0, 'failure_class': 'validation_failure'})
        return deepcopy(snapshots[identifier]), {'request_count': 0, 'outcome': 'preflight_replay'}

    # Authenticate the original receipt at its original source date, then
    # independently reevaluate entry/closure rules at today's merge date.
    _, diagnostics = sam_reviewed.collect(config, original_as_of, {}, client=read)
    sam_reviewed.require_reviewed_observations(config, diagnostics)
    recorded = receipt['diagnostics']
    count = recorded.get('request_count')
    if (type(count) is not int or not 0 <= count <= 8 * sam_reviewed.MAX_APPROVALS
            or dict(recorded, request_count=0) != diagnostics
            or read_ids != set(snapshots) | set(failed_reads)
            or receipt['outcome'] != receipt_outcome(diagnostics)):
        raise ValueError('SAM preflight observations do not match the retained snapshots')
    if as_of != original_as_of:
        _, current = sam_reviewed.collect(config, as_of, {}, client=read)
        sam_reviewed.require_reviewed_observations(config, current)
    read.preflight_provenance = {'receipt_sha256': hashlib.sha256(raw).hexdigest(), **binding,
                                'as_of': receipt['as_of'], 'checked_at': receipt['checked_at'],
                                'admission_as_of': as_of.isoformat(),
                                'public_request_count': count, 'snapshot_count': len(snapshots),
                                'failed_read_count': len(failed_reads), 'outcome': receipt['outcome']}
    return read
