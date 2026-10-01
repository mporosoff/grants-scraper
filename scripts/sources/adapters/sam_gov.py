"""Opt-in SAM research pilot: discovery alone never establishes eligibility."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from scripts.solicitation_identity import normalized_number, sponsor_identity
from ..base import CanonicalOpportunity, SourceAdapter, to_iso_date
from ..registry import register
from ..sam_api import NOTICE_ID, SamError, fetch_listing

CONFIG_PATH = Path(__file__).resolve().parents[3] / 'config/sam_gov.json'
APPROVAL_FIELDS = {'notice_id', 'solicitation_number', 'organization_path', 'sponsor',
    'evidence_url', 'academic_eligibility_quote', 'verified_on', 'review_after'}
_BAA = re.compile(r'\bbroad agency announcement\b|\bBAA\b', re.I)
_NON_CALL = re.compile(r'\b(?:request for information|RFI|sources sought|special notice|'
    r'proposers?[’\']? day|industry day|information session|registration|draft|forecast|'
    r'presolicitation|pre-solicitation|future program)\b', re.I)
_CANCELLED = re.compile(r'\b(?:cancelled|canceled|withdrawn)\b', re.I)
_CURRENT_TYPES = {'solicitation', 'combined synopsis/solicitation', 'combined synopsis solicitation'}
_UNRESTRICTED = {'', 'none', 'n/a', 'not applicable', 'no set aside', 'no set-aside',
    'no set aside used', 'no set-aside used', 'unrestricted', 'full and open competition'}


def _iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid date')
    return date.fromisoformat(value)


def _evidence_url(value, notice_id):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        sam_notice = re.fullmatch(r'/(?:workspace/contract/)?opp/([a-f0-9]{32})/view/?', parsed.path)
        return (parsed.scheme == 'https' and (host.endswith('.gov') or host.endswith('.mil'))
                and not parsed.username and not parsed.password and parsed.port is None
                and not parsed.query and not parsed.fragment and bool(parsed.path)
                and not re.search(r'api[_-]?key|api\.sam\.gov', value, re.I)
                and not (host in {'sam.gov', 'www.sam.gov'} and sam_notice and sam_notice[1] != notice_id))
    except ValueError:
        return False


def load_config(path=CONFIG_PATH):
    """Validate a small, explicit human-reviewed allowlist; never fetch evidence."""
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValueError('Too large')
        config = json.loads(raw)
        if (not isinstance(config, dict) or set(config) != {'schema_version', 'enabled', 'approved_notices'}
                or type(config['schema_version']) is not int or config['schema_version'] != 1
                or type(config['enabled']) is not bool or not isinstance(config['approved_notices'], list)
                or len(config['approved_notices']) > 20
                or (config['enabled'] and not config['approved_notices'])):
            raise ValueError('Invalid configuration')
        ids, identities = set(), set()
        for entry in config['approved_notices']:
            if (not isinstance(entry, dict) or set(entry) != APPROVAL_FIELDS
                    or any(not isinstance(value, str) or value != value.strip()
                           or not value or len(value) > 600 or any(ord(c) < 32 for c in value)
                           for value in entry.values())
                    or not NOTICE_ID.fullmatch(entry['notice_id'])
                    or not 15 <= len(entry['academic_eligibility_quote']) <= 600
                    or not _evidence_url(entry['evidence_url'], entry['notice_id'])):
                raise ValueError('Invalid approval')
            verified, expires = _iso_date(entry['verified_on']), _iso_date(entry['review_after'])
            sponsor = sponsor_identity({'agency': entry['sponsor'], 'agency_authority': 'source_listed'})
            number = normalized_number(entry['solicitation_number'])
            identity = (sponsor, number)
            if (not sponsor or not number or expires < verified or expires > verified + timedelta(days=30)
                    or entry['notice_id'] in ids or identity in identities):
                raise ValueError('Ambiguous approval')
            ids.add(entry['notice_id'])
            identities.add(identity)
        return config
    except (OSError, ValueError, TypeError, KeyError):
        raise SamError('invalid_config', {'request_count': 0}) from None


def approval_sha256(approval):
    return hashlib.sha256(json.dumps(approval, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf8')).hexdigest()


def _text(row, key):
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ''


def _deadline(row):
    values = [_text(row, field) for field in ('responseDeadLine', 'reponseDeadLine')]
    values = [value for value in values if value]
    if not values or len(set(values)) != 1:
        return None
    value = values[0]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?', value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value, parsed
    except ValueError:
        return None


def _reasons(row, as_of):
    reasons = []
    if not _BAA.search(_text(row, 'title')):
        reasons.append('not_baa')
    if _NON_CALL.search(_text(row, 'title')) or _CANCELLED.search(_text(row, 'title')):
        reasons.append('not_open_call')
    if not re.fullmatch(r'A[A-Z0-9]{1,7}', _text(row, 'classificationCode').upper()):
        reasons.append('not_research_classification')
    if _text(row, 'type').casefold() not in _CURRENT_TYPES:
        reasons.append('not_current_solicitation')
    if _text(row, 'active').casefold() != 'yes':
        reasons.append('not_active')
    deadline = _deadline(row)
    if deadline is None:
        reasons.append('unverified_deadline')
    elif deadline[1].date() < as_of:
        reasons.append('expired')
    if any(_text(row, field).casefold() not in _UNRESTRICTED
           or (row.get(field) is not None and not isinstance(row.get(field), str))
           for field in ('typeOfSetAside', 'typeOfSetAsideDescription', 'setAside', 'setAsideCode')):
        reasons.append('restrictive_set_aside')
    archive = to_iso_date(row.get('archiveDate'))
    if archive and archive < as_of.isoformat():
        reasons.append('archived')
    posted = to_iso_date(row.get('postedDate'))
    if not posted or posted > as_of.isoformat():
        reasons.append('unverified_posted_date')
    return reasons


def discovery_candidates(rows, as_of):
    """A public metadata prefilter, not permission to publish or infer eligibility."""
    return [{key: value for key, value in row.items() if key != 'description_route'} |
            {'passes_metadata_prefilter': not (reasons := _reasons(row, as_of)), 'reasons': reasons}
            for row in rows]


def _approval_current(approval, as_of):
    return _iso_date(approval['verified_on']) <= as_of <= _iso_date(approval['review_after'])


def _terminal_status(row, as_of):
    kind = _text(row, 'type').casefold()
    if (kind in {'cancellation', 'cancelled', 'canceled', 'cancelled notice', 'cancellation notice'}
            or _CANCELLED.search(_text(row, 'title'))):
        return 'cancelled'
    if kind in {'award', 'award notice'} or _text(row, 'active').casefold() == 'no':
        return 'closed'
    deadline = _deadline(row)
    if deadline and deadline[1].date() < as_of:
        return 'expired'
    archive = to_iso_date(row.get('archiveDate'))
    if archive and archive < as_of.isoformat():
        return 'archived'
    return 'unverified'


class SamGovAdapter(SourceAdapter):
    slug = 'sam-gov'
    display_name = 'SAM.gov'
    source_type = 'Federal'
    min_records = 0
    max_records = 200
    snapshot_complete = False
    retain_on_failure = False
    disabled_reason = 'SAM pilot awaits reviewed academic eligibility and explicit enablement'

    def __init__(self, config_path=CONFIG_PATH, client=None):
        super().__init__()
        self.config_path = Path(config_path)
        self.client = client or fetch_listing

    @property
    def enabled(self):
        try:
            return load_config(self.config_path)['enabled']
        except SamError:
            # The registry evaluates enabled outside its isolation boundary.
            # Let collect report a malformed config as an unhealthy source.
            return True

    def _record(self, row, approval, as_of, reasons):
        identity_matches = (_text(row, 'solicitationNumber') == approval['solicitation_number']
                            and _text(row, 'fullParentPathName') == approval['organization_path'])
        deadline = _deadline(row)
        extra_deadlines = []
        if deadline and len(deadline[0]) > 10:
            parsed = deadline[1]
            offset = parsed.strftime('%z')
            extra_deadlines.append({'kind': 'application', 'date': parsed.date().isoformat(),
                'time': parsed.strftime('%H:%M:%S'),
                'timezone': 'UTC' if offset == '+0000' else offset[:3] + ':' + offset[3:] if offset else None})
        record = CanonicalOpportunity(
            title=_text(row, 'title') or 'SAM notice requiring verification',
            external_id=row['noticeId'], opportunity_number=_text(row, 'solicitationNumber'),
            url=f"https://sam.gov/opp/{row['noticeId']}/view",
            agency=approval['sponsor'] if identity_matches else _text(row, 'fullParentPathName') or self.display_name,
            description=None, eligibility_text=approval['academic_eligibility_quote'] if not reasons else None,
            close_date=deadline[0] if deadline else None, posted_date=row.get('postedDate'),
            additional_deadlines=extra_deadlines,
        ).to_record(slug=self.slug, source=self.display_name, source_type=self.source_type)
        # CanonicalOpportunity deliberately normalizes statuses for ordinary
        # producers. Terminal observations must survive that conversion here.
        record['status'] = 'posted' if not reasons else _terminal_status(row, as_of)
        record['archive_date'] = to_iso_date(row.get('archiveDate'))
        record['source_review_after'] = min(as_of + timedelta(days=7),
            _iso_date(approval['review_after'])).isoformat()
        record['sam_approval_sha256'] = approval_sha256(approval)
        record['sam_organization_path'] = _text(row, 'fullParentPathName')
        if not reasons:
            record['page_field_provenance'] = {'eligibility_text': {
                'source_url': approval['evidence_url'], 'fetched_at': approval['verified_on'],
                'source_excerpt': approval['academic_eligibility_quote'],
                'extraction_method': 'reviewed_sam_pilot', 'confidence': 'source_verified', 'status': 'verified'}}
        return record

    def collect(self):
        self.diagnostics = {'request_count': 0}
        try:
            config = load_config(self.config_path)
            as_of = self.context.get('as_of') or datetime.now(timezone.utc).date()
            if not isinstance(as_of, date):
                as_of = _iso_date(as_of)
            if not config['enabled'] and not config['approved_notices']:
                rows = []
                self.diagnostics['outcome'] = 'disabled'
            else:
                key = os.environ.get('SAM_API_KEY', '').strip()
                if not key:
                    raise SamError('missing_key', {'request_count': 0})
                rows, diagnostics = self.client(key, today=as_of)
                self.diagnostics = dict(diagnostics)
        except SamError as error:
            self.diagnostics = error.diagnostics
            raise
        except Exception:
            raise SamError('collection_failed', self.diagnostics) from None
        approvals = {entry['notice_id']: entry for entry in config['approved_notices']}
        records, seen, counts = [], set(), Counter()
        for row in rows:
            notice_id = row.get('noticeId')
            approval = approvals.get(notice_id)
            if not approval:
                counts['unapproved'] += 1
                continue
            seen.add(notice_id)
            reasons = _reasons(row, as_of)
            if (_text(row, 'solicitationNumber') != approval['solicitation_number']
                    or _text(row, 'fullParentPathName') != approval['organization_path']):
                reasons.append('identity_changed')
            if not _approval_current(approval, as_of):
                reasons.append('approval_not_current')
            counts.update(reasons)
            records.append(self._record(row, approval, as_of, reasons))
        # Revocation does not depend on the old notice remaining in the bounded
        # listing. The exact approval also binds any unobserved retained record.
        snapshots = self.context.get('source_snapshots', {})
        for cached in snapshots.get(self.slug, []) if isinstance(snapshots, dict) else []:
            record_id = str(cached.get('opportunity_id') or '')
            notice_id = record_id.removeprefix(self.slug + ':')
            if not record_id.startswith(self.slug + ':') or notice_id in seen:
                continue
            approval = approvals.get(notice_id)
            valid = (approval and _approval_current(approval, as_of)
                and cached.get('sam_approval_sha256') == approval_sha256(approval)
                and cached.get('sam_organization_path') == approval['organization_path']
                and cached.get('agency') == approval['sponsor']
                and cached.get('opportunity_number') == approval['solicitation_number'])
            if not valid:
                records.append(dict(cached, status='unverified'))
                counts['cached_approval_revoked'] += 1
                seen.add(notice_id)
        admitted = sum(record['status'] == 'posted' for record in records)
        self.diagnostics.update(discovered=len(rows), admitted=admitted,
            deferred=len(rows) - admitted, observations=len(records), exclusion_reasons=dict(counts))
        return records


register(SamGovAdapter())
