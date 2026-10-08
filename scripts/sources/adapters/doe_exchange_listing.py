"""Read the complete consolidated Exchange listing without executing its script.

The public Default.aspx page embeds all offices' records and topic deadlines as
JSON; its filters and pagination run in the browser. Office identity and source
status therefore have to be applied before treating a notice as an open call.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import re

from ..base import CanonicalOpportunity

LIST_URL = 'https://exchange.energy.gov/Default.aspx'
# Complete public response measured 2026-10-08: 24,636,245 bytes. This exception
# is specific to the consolidated DOE listing; other sources retain their cap.
MAX_BYTES = 32 * 1024 * 1024
GUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
NUMBER = re.compile(r'DE-[A-Z0-9]+-[A-Z0-9-]+\Z')
DEADLINES = (
    ('ConceptPaperUpldDeadline', 'concept_paper', 'Concept paper'),
    ('FullAppSubmissionDeadline', 'application', 'Full application'),
    ('SubmissionRegistrationDeadline', 'registration', 'Submission registration'),
    ('RenewalPhaseSubmissionDeadline', 'application', 'Renewal application'),
)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DOE Exchange JSON contains a duplicate field')
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError('DOE Exchange JSON contains a non-JSON constant')


def _array(html, name, maximum):
    declarations = list(re.finditer(r'\bconst\s+' + re.escape(name) + r'\s*=\s*', html))
    if len(declarations) != 1:
        raise ValueError('DOE Exchange listing is missing a unique ' + name)
    try:
        rows, end = json.JSONDecoder(object_pairs_hook=_object,
            parse_constant=_invalid_constant).raw_decode(html, declarations[0].end())
    except (ValueError, RecursionError) as exc:
        raise ValueError('DOE Exchange listing has invalid ' + name) from exc
    if (not isinstance(rows, list) or len(rows) > maximum
            or not re.match(r'\s*\|\|\s*\[\s*\]\s*;', html[end:end + 50])
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError('DOE Exchange listing has an incomplete or oversized ' + name)
    return rows


def _unique_notices(rows):
    objects, ids, refs = [], {}, []
    for row in rows:
        if '$ref' in row:
            if set(row) != {'$ref'} or not isinstance(row['$ref'], str):
                raise ValueError('DOE Exchange listing has an invalid reference')
            refs.append(row['$ref'])
            continue
        reference = row.get('$id')
        if not isinstance(reference, str) or not reference or reference in ids:
            raise ValueError('DOE Exchange listing has duplicate or missing object identity')
        ids[reference] = row
        objects.append(row)
    if not objects or len(objects) > 5000 or any(ref not in ids for ref in refs):
        raise ValueError('DOE Exchange listing has missing or unresolved notice objects')
    notice_ids = set()
    for row in objects:
        notice_id = row.get('FoaId')
        if not isinstance(notice_id, str) or not GUID.fullmatch(notice_id):
            raise ValueError('DOE Exchange listing has an invalid notice identity')
        if notice_id.lower() in notice_ids:
            raise ValueError('DOE Exchange listing repeats a notice identity')
        notice_ids.add(notice_id.lower())
    return objects


def _timestamp(value, field):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?', value):
        raise ValueError('DOE Exchange listing has an invalid ' + field)
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('DOE Exchange listing has an invalid ' + field) from exc


def _events(details, url):
    events, topics = [], {}
    for detail in details:
        track = detail.get('TopicName')
        if not isinstance(track, str) or not track.strip() or len(track) > 1000:
            raise ValueError('DOE Exchange listing has an invalid topic name')
        phase = detail.get('PhaseName')
        if phase is not None and (not isinstance(phase, str) or len(phase) > 200):
            raise ValueError('DOE Exchange listing has an invalid phase name')
        identity = (track.strip(), phase or None)
        values = tuple(detail.get(field) for field, _, _ in DEADLINES)
        if identity in topics and topics[identity] != values:
            raise ValueError('DOE Exchange listing has conflicting topic deadlines')
        topics[identity] = values
        for field, kind, label in DEADLINES:
            if field not in detail:
                raise ValueError('DOE Exchange topic is missing a submission field')
            value = detail.get(field)
            if value is None:
                continue
            parsed = _timestamp(value, field)
            event = {
                'kind': kind, 'stage': kind, 'date': parsed.date().isoformat(),
                'time': parsed.strftime('%H:%M:%S'),
                # The new listing supplies naive times without declaring a zone.
                # Do not inherit ET from the decommissioned portal's template.
                'timezone': ('UTC' if parsed.utcoffset().total_seconds() == 0
                    else parsed.strftime('%z')[:3] + ':' + parsed.strftime('%z')[3:])
                    if parsed.tzinfo is not None else None,
                'track': track.strip(), 'application_class': 'renewal'
                    if field == 'RenewalPhaseSubmissionDeadline' else 'unspecified',
                **({'cycle': phase} if phase else {}),
                'note': label + '; consult the official announcement for prerequisites.',
                'required': None, 'obligation': 'unknown', 'date_status': 'known',
                'source': 'DOE Exchange topic submission field', 'source_url': url,
                'source_field': field, 'confidence': 'source_listed',
            }
            if event not in events:
                events.append(event)
    if len(events) > 50:
        raise ValueError('DOE Exchange notice exceeds the complete deadline limit')
    return events


def parse_listing(html: str, *, organization_id: int, organization_name: str,
                  slug: str, as_of: date, maximum: int):
    """Return open opportunities and explicit non-current observations.

    A successful response replaces this complete office snapshot. Terminal
    observations are diagnostics, not posted CanonicalOpportunity records.
    """
    if (not isinstance(html, str) or len(html.encode('utf-8')) > MAX_BYTES
            or not html.rstrip().lower().endswith('</html>')):
        raise ValueError('DOE Exchange listing is not a complete bounded HTML response')
    notices = _unique_notices(_array(html, 'dbFOAList', 20000))
    organizations = _array(html, 'dbOrganizations', 100)
    matches = [row for row in organizations if row.get('OrganizationId') == organization_id]
    if (len(matches) != 1 or matches[0].get('Name') != organization_name
            or matches[0].get('IsDeleted') is not False):
        raise ValueError('DOE Exchange office identity changed')
    office = matches[0].get('FullName')
    if not isinstance(office, str) or not office.strip() or len(office) > 500:
        raise ValueError('DOE Exchange office name is invalid')
    details = {}
    for row in _array(html, 'dbfoaListDetails', 10000):
        notice_id = row.get('FoaId')
        if not isinstance(notice_id, str) or not GUID.fullmatch(notice_id):
            raise ValueError('DOE Exchange topic has an invalid notice identity')
        details.setdefault(notice_id.lower(), []).append(row)
    opportunities, terminal, numbers = [], [], set()
    selected = [row for row in notices if row.get('OrganizationId') == organization_id]
    if not selected:
        raise ValueError('DOE Exchange office is absent from the complete listing')
    for row in selected:
        if row.get('OrganizationName') != organization_name:
            raise ValueError('DOE Exchange notice conflicts with its office identity')
        if not isinstance(row.get('FOATypeName'), str) or not row['FOATypeName'].strip():
            raise ValueError('DOE Exchange notice is missing its announcement type')
        if row.get('FOATypeName') != 'Notice Of Funding Opportunity (NOFO)':
            continue
        number, title = row.get('FoaNumber'), row.get('FoaTitle')
        if (not isinstance(number, str) or not NUMBER.fullmatch(number)
                or number in numbers or not isinstance(title, str)
                or not title.strip() or len(title) > 2000):
            raise ValueError('DOE Exchange NOFO has invalid or duplicate identity')
        numbers.add(number)
        if len(numbers) > maximum:
            raise ValueError('DOE Exchange office exceeds its notice health bound')
        modified = row.get('ModifiedDate')
        _timestamp(modified, 'ModifiedDate')
        status = row.get('AnnouncementStatus')
        if status not in {'Open', 'Closed', 'Archived', 'Not Published'} or any(
            type(row.get(field)) is not bool
            for field in ('IsDeleted', 'Archived', 'ApprovedForPublic', 'AllowSubmissions')
        ):
            raise ValueError('DOE Exchange NOFO has an unknown publication state')
        url = 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=' + row['FoaId'].lower()
        reason = ('withdrawn' if row['IsDeleted'] else 'archived' if row['Archived']
            or status == 'Archived' else 'closed' if status == 'Closed'
            else 'unverified' if status != 'Open' or not row['ApprovedForPublic']
            or not row['AllowSubmissions'] else None)
        events = []
        undated_topic = False
        if reason is None:
            topics = details.get(row['FoaId'].lower()) or []
            if not topics or any(item.get('AnnouncementStatus') not in {'Active', 'Closed', 'Archived'}
                                 for item in topics):
                raise ValueError('DOE Exchange open NOFO has missing or unknown topic states')
            active = [item for item in topics if item['AnnouncementStatus'] == 'Active']
            if not active:
                reason = 'closed'
            else:
                events = _events(active, url)
                undated_topic = any(not any(item[field] is not None for field, kind, _ in DEADLINES
                                           if kind != 'registration') for item in active)
        # An undated active topic does not acquire a sibling's closing date.
        close_date = None if undated_topic else max((event['date'] for event in events
            if event['kind'] != 'registration'), default=None)
        if reason is None and close_date and close_date < as_of.isoformat():
            reason = 'expired'
        if reason:
            terminal.append({'opportunity_id': slug + ':' + number,
                'opportunity_number': number, 'status': reason,
                'source_status': status, 'last_updated': modified,
                'close_date': close_date, 'source_url': url})
            continue
        suboffice = row.get('SubProgramOfficeName')
        if suboffice is not None and (not isinstance(suboffice, str) or len(suboffice) > 500):
            raise ValueError('DOE Exchange suboffice is invalid')
        opportunities.append(CanonicalOpportunity(external_id=number,
            opportunity_number=number, title=title, agency=suboffice or office,
            url=url, close_date=close_date, additional_deadlines=events,
            deadline_note='See the official topic submission fields and prerequisites.' if events else None,
            extra={'close_date_kind': 'submission_window_end', 'agency_code': 'DOE',
                'last_updated': modified[:10]}))
    return opportunities, {'listing_url': LIST_URL, 'organization_id': organization_id,
        'organization_name': organization_name, 'complete_listing': True,
        'unique_notices': len(notices), 'office_notices': len(selected),
        'nofo_observations': len(numbers), 'observed_terminal_records': terminal}
