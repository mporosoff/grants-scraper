"""Read exact public SAM notices and detect changes to reviewed evidence.

These are SAM's anonymous public notice/attachment-metadata routes. No personal
API key, cookie, private contact, or attachment body enters the returned snapshot.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, build_opener

from .sam_api import NOTICE_ID, NoRedirect, SamError

MAX_BYTES = 8 * 1024 * 1024
ATTACHMENT_FIELDS = ('attachmentId', 'resourceId', 'name', 'type', 'postedDate',
                     'accessLevel', 'exportControlled', 'explicitAccess', 'mimeType',
                     'size', 'deletedDate', 'deletedFlag', 'fileExists', 'accessStatus')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf-8')).hexdigest()


def _text(value, *, required=False, maximum=2000):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or required and not value.strip()):
        raise SamError('invalid_public_notice')
    return value.strip()


def _attachments(payload, notice_id):
    try:
        # HAL omits _embedded for a successful, explicitly empty collection.
        # Require both exact resource links before accepting that representation.
        if isinstance(payload, dict) and set(payload) == {'_links'}:
            links = payload['_links']
            for name in ('self', 'opportunity:publish:latest'):
                parsed = urlsplit(links[name]['href'])
                if (parsed.scheme != 'https' or parsed.username or parsed.password
                        or parsed.path != f'/opps/v3/opportunities/{notice_id}/resources'
                        or sorted(parse_qsl(parsed.query)) != [('excludeDeleted', 'true'), ('withScanResult', 'false')]):
                    raise ValueError()
            return []
        groups = payload['_embedded']['opportunityAttachmentList']
        if not isinstance(groups, list) or len(groups) > 10:
            raise ValueError()
        result, seen = [], set()
        for group in groups:
            if group.get('opportunityId') != notice_id or not isinstance(group.get('attachments'), list):
                raise ValueError()
            if len(group['attachments']) > 500:
                raise ValueError()
            for item in group['attachments']:
                if not isinstance(item, dict) or not isinstance(item.get('resourceId'), str):
                    raise ValueError()
                selected = {k: item[k] for k in ATTACHMENT_FIELDS if k in item}
                # Linked resources can change target without a new resource ID.
                # Bind that change without exporting a potentially signed URL.
                uri = item.get('uri')
                if uri is not None:
                    if not isinstance(uri, str) or len(uri) > 16000:
                        raise ValueError()
                    selected['uri_sha256'] = hashlib.sha256(uri.encode('utf8')).hexdigest()
                if any(v is not None and type(v) not in (str, int, bool)
                       or isinstance(v, str) and len(v) > 2000 for v in selected.values()):
                    raise ValueError()
                identity = (item.get('attachmentId'), item['resourceId'])
                if identity in seen:
                    raise ValueError()
                seen.add(identity)
                result.append(selected)
        return sorted(result, key=lambda item: (item['resourceId'], item.get('attachmentId') or ''))
    except (KeyError, TypeError, AttributeError, ValueError):
        raise SamError('invalid_public_resources') from None


def snapshot(payload, resources, notice_id):
    """Project review-relevant facts and hashes; omit raw descriptions/contacts."""
    try:
        if not NOTICE_ID.fullmatch(notice_id) or not isinstance(payload, dict):
            raise ValueError()
        if payload.get('opportunityId') != notice_id or payload.get('id') != notice_id:
            raise ValueError()
        data = payload['data2']
        if not isinstance(data, dict) or any(type(payload.get(k)) is not bool
                for k in ('latest', 'archived', 'cancelled', 'deleted')):
            raise ValueError()
        status = _text(payload['status']['code'], required=True)
        route = payload['_links']['opportunity:publish:latest']['href']
        match = re.fullmatch(r'/opps/v2/opportunities/([0-9a-f]{32})', route)
        if not match or payload['latest'] is True and match[1] != notice_id:
            raise ValueError()
        descriptions = payload.get('description')
        if not isinstance(descriptions, list) or len(descriptions) > 20:
            raise ValueError()
        description_parts = []
        for item in descriptions:
            if (not isinstance(item, dict) or item.get('opportunityId') != notice_id
                    or not isinstance(item.get('body'), str)):
                raise ValueError()
            description_parts.append({'id': item.get('descriptionId'),
                                      'sha256': hashlib.sha256(item['body'].encode('utf-8')).hexdigest()})
        solicitation = data.get('solicitation') or {}
        deadlines = solicitation.get('deadlines') or {}
        archive = data.get('archive') or {}
        naics = data.get('naics') or []
        if not isinstance(naics, list) or len(naics) > 30:
            raise ValueError()
        codes = []
        for item in naics:
            if not isinstance(item, dict) or not isinstance(item.get('code'), list):
                raise ValueError()
            for code in item['code']:
                if not isinstance(code, str) or not re.fullmatch(r'\d{2,6}', code):
                    raise ValueError()
                codes.append(code)
        # Public SAM nests the real restriction under solicitation. Preserve
        # every advertised value so an alias can never hide a restriction.
        set_asides = []
        for value in (solicitation.get('setAside'), data.get('setAside')):
            if value is not None:
                set_asides.append(_text(value, required=True))
        result = {
            'notice_id': notice_id, 'latest_notice_id': match[1],
            'latest': payload['latest'], 'status': status,
            'archived': payload['archived'], 'cancelled': payload['cancelled'], 'deleted': payload['deleted'],
            'title': _text(data.get('title'), required=True),
            'solicitation_number': _text(data.get('solicitationNumber'), required=True),
            'organization_id': _text(data.get('organizationId'), required=True),
            'notice_type': _text(data.get('type'), required=True),
            'classification_code': _text(data.get('classificationCode')),
            'naics_codes': sorted(set(codes)), 'set_asides': sorted(set(set_asides)),
            'posted_at': _text(payload.get('postedDate'), required=True),
            'modified_at': _text(payload.get('modifiedDate'), required=True),
            'response_deadline': _text(deadlines.get('response')),
            'response_timezone': _text(deadlines.get('responseTz')),
            'archive_date': _text(archive.get('date')),
            'description_sha256': digest(sorted(description_parts, key=lambda item: item['id'] or '')),
            'resources_sha256': digest(_attachments(resources, notice_id)),
        }
        result['review_sha256'] = digest(result)
        return result
    except SamError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError):
        raise SamError('invalid_public_notice') from None


def _get_json(url, opener):
    client = opener if opener is not None else build_opener(NoRedirect())
    # Both routes may serve HAL JSON; JSON-only negotiation returns HTTP 406.
    request = Request(url, headers={'Accept': '*/*',
                      'User-Agent': 'Funding-Finder-SAM-Research/1.0'}, method='GET')
    try:
        with client.open(request, timeout=30) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
        if status != 200 or len(raw) > MAX_BYTES:
            raise SamError('public_http_error', {'http_status': status})
        return json.loads(raw)
    except HTTPError as error:
        status = error.code
        error.close()
        raise SamError('public_http_error', {'http_status': status}) from None
    except SamError:
        raise
    except Exception:
        raise SamError('public_transport_or_schema_error') from None


def fetch_notice(notice_id, *, opener=None):
    """Exactly two bounded public reads, no redirect/retry or credential access."""
    diagnostics = {'request_count': 0, 'outcome': 'pending'}
    if not isinstance(notice_id, str) or not NOTICE_ID.fullmatch(notice_id):
        raise SamError('invalid_notice_id', diagnostics)
    try:
        diagnostics['request_count'] += 1
        notice = _get_json(f'https://sam.gov/api/prod/opps/v2/opportunities/{notice_id}', opener)
        diagnostics['request_count'] += 1
        resources = _get_json(f'https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}'
                              '/resources?excludeDeleted=true&withScanResult=false', opener)
        result = snapshot(notice, resources, notice_id)
        return result, diagnostics | {'outcome': 'ok', 'http_status': 200}
    except SamError as error:
        raise SamError('public_notice_unavailable', diagnostics | error.diagnostics) from None
