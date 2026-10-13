"""Evidence-pinned SAM research calls with explicitly reviewed entry stages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from scripts.solicitation_identity import normalized_number, sponsor_identity
from .base import CanonicalOpportunity, to_iso_date
from .sam_api import NOTICE_ID, SamError
from .sam_public import digest, fetch_notice

MAX_APPROVALS = 100
FIELDS = {'notice_id', 'solicitation_number', 'organization_id', 'sponsor', 'evidence_url',
          'academic_eligibility_quote', 'verified_on', 'review_after', 'review_sha256',
          'summary', 'scope_note', 'cycles'}
EVENT_FIELDS = {'kind', 'date', 'time', 'timezone', 'required', 'invitation_required',
                'note', 'source_url', 'quote'}
ENTRY_KINDS = {'application', 'full_application', 'white_paper', 'concept_paper',
               'preproposal', 'preapplication', 'letter_of_intent'}


def iso(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid date')
    return date.fromisoformat(value)


def official_url(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and (parsed.netloc.endswith('.gov') or parsed.netloc.endswith('.mil'))
                and not parsed.query and not parsed.fragment and not parsed.username
                and not parsed.password and parsed.port is None and bool(parsed.path)
                and not re.search(r'api[_-]?key|api\.sam\.gov', value, re.I))
    except (ValueError, TypeError):
        return False


def text(value, maximum=3000, required=True):
    return (isinstance(value, str) and len(value) <= maximum and value == value.strip()
            and (bool(value) or not required) and not any(ord(c) < 32 for c in value))


def validate_event(event, *, entry):
    if (not isinstance(event, dict) or set(event) != EVENT_FIELDS
            or event['kind'] not in (ENTRY_KINDS if entry else {'full_application'})
            or type(event['required']) is not bool or type(event['invitation_required']) is not bool
            or not text(event['note'], required=False) or not text(event['quote'], 1000)
            or not official_url(event['source_url'])):
        raise ValueError('Invalid reviewed event')
    if entry and (event['invitation_required'] or event['date'] is None):
        raise ValueError('An open dated entry is required')
    if event['date'] is None:
        if not event['invitation_required'] or event['time'] is not None or event['timezone'] is not None:
            raise ValueError('Undated full submissions require invitation')
    else:
        iso(event['date'])
        if event['time'] is not None:
            if not re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', event['time']):
                raise ValueError('Invalid time')
            datetime.fromisoformat(event['date'] + 'T' + event['time'])
            if event['timezone'] is None:
                raise ValueError('Timed deadlines require a reviewed timezone')
        if event['timezone'] is not None:
            ZoneInfo(event['timezone'])


def validate_config(config):
    try:
        if (not isinstance(config, dict) or set(config) != {'schema_version', 'enabled', 'approved_notices'}
                or type(config['schema_version']) is not int or config['schema_version'] != 2
                or type(config['enabled']) is not bool or not isinstance(config['approved_notices'], list)
                or len(config['approved_notices']) > MAX_APPROVALS
                or config['enabled'] and not config['approved_notices']):
            raise ValueError('Invalid reviewed configuration')
        ids, identities = set(), set()
        for approval in config['approved_notices']:
            if (not isinstance(approval, dict) or set(approval) != FIELDS
                    or any(not text(approval[k], 3000, required=k != 'scope_note') for k in FIELDS - {'cycles'})
                    or not NOTICE_ID.fullmatch(approval['notice_id'])
                    or not re.fullmatch(r'\d{1,20}', approval['organization_id'])
                    or not re.fullmatch(r'[0-9a-f]{64}', approval['review_sha256'])
                    or not official_url(approval['evidence_url'])
                    or not 15 <= len(approval['academic_eligibility_quote']) <= 1000):
                raise ValueError('Invalid reviewed approval')
            verified, expires = iso(approval['verified_on']), iso(approval['review_after'])
            sponsor = sponsor_identity({'agency': approval['sponsor'], 'agency_authority': 'source_listed'})
            number = normalized_number(approval['solicitation_number'])
            identity = (sponsor, number)
            if (not sponsor or not number or not verified <= expires <= verified + timedelta(days=30)
                    or approval['notice_id'] in ids or identity in identities):
                raise ValueError('Ambiguous or stale approval')
            ids.add(approval['notice_id'])
            identities.add(identity)
            cycles = approval['cycles']
            if not isinstance(cycles, list) or not 1 <= len(cycles) <= 10:
                raise ValueError('Invalid cycles')
            names = set()
            for cycle in cycles:
                if (not isinstance(cycle, dict) or set(cycle) != {'name', 'entry', 'full'}
                        or not text(cycle['name'], 100) or cycle['name'] in names):
                    raise ValueError('Invalid cycle')
                names.add(cycle['name'])
                validate_event(cycle['entry'], entry=True)
                if cycle['full'] is not None:
                    validate_event(cycle['full'], entry=False)
                    if (cycle['entry']['kind'] in {'application', 'full_application'}
                            or cycle['full']['date'] is not None and cycle['full']['date'] < cycle['entry']['date']):
                        raise ValueError('Invalid stage order')
        return config
    except (ValueError, TypeError, KeyError, AttributeError):
        raise SamError('invalid_config', {'request_count': 0}) from None


def active_cycles(approval, as_of):
    # Preserve each cycle's source-owned prerequisite; never attach an old
    # preliminary deadline to a later cycle or advertise an invited-only tail.
    return [cycle for cycle in approval['cycles'] if iso(cycle['entry']['date']) >= as_of]


def _event(event, cycle):
    result = {k: event[k] for k in ('kind', 'date', 'time', 'timezone', 'required', 'invitation_required', 'note')}
    result.update(cycle=cycle, stage=event['kind'], application_class='new',
                  source='SAM.gov reviewed solicitation', source_url=event['source_url'],
                  source_field='reviewed solicitation', confidence='source_verified',
                  citation={'source_url': event['source_url'], 'source_field': 'reviewed solicitation',
                            'quote': event['quote']})
    if event['required']:
        result['requirement_citation'] = dict(result['citation'])
    if event['invitation_required']:
        result['prerequisite'] = 'invitation'
    if event['date'] is None:
        result['date_status'] = 'unknown'
    return result


def make_record(notice, approval, as_of):
    cycles = active_cycles(approval, as_of)
    reasons = []
    if (notice['notice_id'] != approval['notice_id'] or notice['solicitation_number'] != approval['solicitation_number']
            or notice['organization_id'] != approval['organization_id']):
        reasons.append('identity_changed')
    if not notice['latest'] or notice['latest_notice_id'] != approval['notice_id']:
        reasons.append('superseded_notice')
    if notice['review_sha256'] != approval['review_sha256']:
        reasons.append('reviewed_evidence_changed')
    if not iso(approval['verified_on']) <= as_of <= iso(approval['review_after']):
        reasons.append('approval_not_current')
    if (notice['status'] != 'published' or notice['archived'] or notice['cancelled'] or notice['deleted']
            or notice['notice_type'] not in {'o', 'k', 's', 'p'}):
        reasons.append('not_open_notice')
    if any(value.casefold() not in {'none', 'unrestricted'} for value in notice['set_asides']):
        reasons.append('restrictive_set_aside')
    archive = to_iso_date(notice['archive_date'])
    if archive and archive < as_of.isoformat():
        reasons.append('archive_date_passed')
    posted = to_iso_date(notice['posted_at'])
    if not posted or posted > as_of.isoformat():
        reasons.append('invalid_posted_date')
    if not cycles:
        reasons.append('entry_closed')
    selected = cycles or approval['cycles']
    events = []
    for cycle in selected:
        events.append(_event(cycle['entry'], cycle['name']))
        if cycle['full'] is not None:
            events.append(_event(cycle['full'], cycle['name']))
    # Keep the umbrella as a window boundary, not an invented full-proposal date.
    close_date = max(item['date'] for item in events if item['date'])
    description = approval['summary'] + (' ' + approval['scope_note'] if approval['scope_note'] else '')
    record = CanonicalOpportunity(title=notice['title'], external_id=approval['notice_id'],
        opportunity_number=approval['solicitation_number'],
        url=f"https://sam.gov/opp/{approval['notice_id']}/view", agency=approval['sponsor'],
        description=description, eligibility_text=approval['academic_eligibility_quote'] if not reasons else None,
        close_date=close_date, posted_date=notice['posted_at'],
        deadline_note='Follow the reviewed submission stage, cycle, and source instructions.',
        additional_deadlines=events, extra={'close_date_kind': 'submission_window_end'},
    ).to_record(slug='sam-gov', source='SAM.gov', source_type='Federal')
    status = ('cancelled' if notice['cancelled'] else 'archived' if notice['archived'] or notice['deleted']
              else 'expired' if 'entry_closed' in reasons else 'unverified' if reasons else 'posted')
    record.update(status=status, archive_date=to_iso_date(notice['archive_date']),
                  last_updated=to_iso_date(notice['modified_at']),
                  source_review_after=min(as_of + timedelta(days=7), iso(approval['review_after'])).isoformat(),
                  sam_approval_sha256=digest(approval), sam_review_sha256=notice['review_sha256'],
                  sam_organization_id=notice['organization_id'])
    preliminary = [event for event in events if event['kind'] not in {'application', 'full_application'}]
    record.update(has_preliminary_stage=bool(preliminary),
                  preliminary_required=any(event['required'] for event in preliminary),
                  preliminary_stage_type=preliminary[0]['kind'] if preliminary else None)
    if not reasons:
        record['page_field_provenance'] = {'eligibility_text': {
            'source_url': approval['evidence_url'], 'fetched_at': approval['verified_on'],
            'source_excerpt': approval['academic_eligibility_quote'],
            'extraction_method': 'reviewed_sam_notice', 'confidence': 'source_verified', 'status': 'verified'}}
    return record, reasons


def collect(config, as_of, snapshots, *, client=None):
    validate_config(config)
    client = client or fetch_notice
    approvals = config['approved_notices']
    diagnostics = {'request_count': 0, 'outcome': 'ok', 'discovered': len(approvals),
                   'reviewed_inventory': True, 'exclusion_reasons': {}, 'notice_observations': []}

    def fetch(approval):
        try:
            notice, detail = client(approval['notice_id'])
            return notice, detail, None
        except SamError as error:
            return None, error.diagnostics, 'public_notice_unavailable'
        except Exception:
            return None, {'request_count': 0}, 'invalid_notice_client'

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(fetch, approvals))
    records, seen = [], set()
    failures = []
    for approval, (notice, detail, failure) in zip(approvals, results):
        diagnostics['request_count'] += detail.get('request_count', 0)
        if failure:
            failures.append({'notice_id': approval['notice_id'], 'reason': failure,
                             'http_status': detail.get('http_status')})
            continue
        record, reasons = make_record(notice, approval, as_of)
        records.append(record)
        seen.add(approval['notice_id'])
        diagnostics['notice_observations'].append({'notice_id': approval['notice_id'],
            'review_sha256': notice['review_sha256'], 'reasons': reasons})
        for reason in reasons:
            diagnostics['exclusion_reasons'][reason] = diagnostics['exclusion_reasons'].get(reason, 0) + 1
    if failures:
        raise SamError('reviewed_notice_fetch_failed', diagnostics | {'failures': failures})
    for cached in snapshots.get('sam-gov', []) if isinstance(snapshots, dict) else []:
        record_id = str(cached.get('opportunity_id') or '')
        if record_id.startswith('sam-gov:') and record_id.removeprefix('sam-gov:') not in seen:
            records.append(dict(cached, status='unverified'))
    admitted = sum(record['status'] == 'posted' for record in records)
    diagnostics.update(admitted=admitted, deferred=len(approvals) - admitted, observations=len(records))
    return records, diagnostics
