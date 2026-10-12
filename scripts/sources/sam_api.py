"""Bounded SAM transport. Credential-bearing URLs and response bodies stay private."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://api.sam.gov/opportunities/v2/search'
MAX_BYTES = 8 * 1024 * 1024
DESCRIPTION_MAX_BYTES = 1024 * 1024
LIMIT = 500
NOTICE_ID = re.compile(r'[0-9a-f]{32}')
DESCRIPTION_ROUTES = {
    'v1': '/opportunities/v1/noticedesc',
    'prod-v1': '/prod/opportunities/v1/noticedesc',
}
PUBLIC_FIELDS = ('noticeId', 'title', 'solicitationNumber', 'fullParentPathName',
    'fullParentPathCode', 'postedDate', 'type', 'active', 'responseDeadLine',
    'reponseDeadLine', 'archiveDate', 'typeOfSetAside', 'typeOfSetAsideDescription',
    'setAside', 'setAsideCode', 'naicsCode', 'classificationCode')
ERROR_CODES = frozenset({'API_KEY_MISSING', 'API_KEY_INVALID', 'API_KEY_DISABLED',
    'API_KEY_UNAUTHORIZED', 'API_KEY_UNVERIFIED', 'OVER_RATE_LIMIT'})


class SamError(ValueError):
    """Only fixed reason codes and bounded, credential-free diagnostics escape."""
    def __init__(self, reason, diagnostics=None):
        super().__init__('sam_' + reason)
        self.diagnostics = dict(diagnostics or {})
        self.diagnostics['outcome'] = reason


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redacted(value, key):
    if isinstance(value, dict):
        return {name: redacted(item, key) for name, item in value.items()}
    if isinstance(value, list):
        return [redacted(item, key) for item in value]
    if isinstance(value, str) and key:
        for variant in {key, quote(key, safe=''), quote_plus(key, safe='')}:
            value = value.replace(variant, '[redacted]')
            # Percent escapes are case insensitive; literal key characters are not.
            if '%' in variant:
                pattern = ''.join('[%s%s]' % (c.lower(), c.upper()) if i > 0 and
                    (variant[i - 1] == '%' or (i > 1 and variant[i - 2] == '%')) and
                    c in 'abcdefABCDEF' else re.escape(c) for i, c in enumerate(variant))
                value = re.sub(pattern, '[redacted]', value)
    return value


def quota(headers):
    result = {}
    for name in ('X-RateLimit-Limit', 'X-RateLimit-Remaining', 'Retry-After'):
        value = headers.get(name, '')
        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value):
            result[name] = int(value)
    return result


def _request(api_key, endpoint, query, max_bytes, opener):
    key = api_key.strip() if isinstance(api_key, str) else ''
    diagnostics = {'request_count': 0, 'http_status': None, 'rate_limit': {},
                   'query': redacted(query, key)}
    if not key:
        raise SamError('missing_key', diagnostics)
    client = opener if opener is not None else build_opener(NoRedirect())
    request = Request(endpoint + '?' + urlencode(query | {'api_key': key}),
        headers={'Accept': 'application/json', 'User-Agent': 'Funding-Finder-SAM-Pilot/1.0'},
        method='GET')
    diagnostics['request_count'] = 1
    try:
        with client.open(request, timeout=30) as response:
            diagnostics['http_status'] = response.status
            diagnostics['rate_limit'] = quota(response.headers)
            raw = response.read(max_bytes + 1)
    except HTTPError as error:
        diagnostics['http_status'] = error.code
        diagnostics['rate_limit'] = quota(error.headers or {})
        try:
            raw = error.read(max_bytes + 1)
            payload = json.loads(raw) if len(raw) <= max_bytes else {}
            detail = payload.get('error', {}) if isinstance(payload, dict) else {}
            code = detail.get('code') if isinstance(detail, dict) else None
            if isinstance(code, str) and code in ERROR_CODES:
                diagnostics['error_code'] = code
        except Exception:
            pass
        finally:
            error.close()
        raise SamError('http_error', redacted(diagnostics, key)) from None
    except Exception:
        raise SamError('network_error', redacted(diagnostics, key)) from None
    if diagnostics['http_status'] != 200:
        raise SamError('http_error', redacted(diagnostics, key))
    if len(raw) > max_bytes:
        raise SamError('response_too_large', redacted(diagnostics, key))
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise SamError('invalid_response', redacted(diagnostics, key)) from None
    return payload, redacted(diagnostics, key), key


def _description_route(value, notice_id):
    """Convert a verified API link to a fixed route token; never retain its URL."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (parsed.scheme != 'https' or parsed.netloc != 'api.sam.gov'
                or parsed.fragment or parsed.path not in DESCRIPTION_ROUTES.values()
                or any(name not in {'noticeid', 'api_key'} for name, _ in query)
                or len([v for n, v in query if n == 'noticeid']) != 1
                or len([v for n, v in query if n == 'api_key']) > 1
                or dict(query).get('noticeid') != notice_id):
            return None
        return next(name for name, path in DESCRIPTION_ROUTES.items() if path == parsed.path)
    except ValueError:
        return None


def _public_scalar(value, key):
    if value is None or isinstance(value, bool) or type(value) is int:
        return value
    if not isinstance(value, str) or len(value) > 2000:
        return None
    value = redacted(value, key)
    if re.search(r'api\.sam\.gov|api[_-]?key\s*(?:=|%3d)', value, re.I):
        return '[omitted]'
    return value


def fetch_listing(api_key, *, today=None, opener=None):
    """One complete bounded listing, with no pagination or detail fetches."""
    today = today or datetime.now(timezone.utc).date()
    query = {'postedFrom': (today - timedelta(days=364)).strftime('%m/%d/%Y'),
             'postedTo': today.strftime('%m/%d/%Y'), 'title': 'Broad Agency Announcement',
             'limit': LIMIT, 'offset': 0}
    payload, diagnostics, key = _request(api_key, ENDPOINT, query, MAX_BYTES, opener)
    if (not isinstance(payload, dict) or not isinstance(payload.get('opportunitiesData'), list)
            or type(payload.get('totalRecords')) is not int
            or payload['totalRecords'] != len(payload['opportunitiesData'])
            or len(payload['opportunitiesData']) > LIMIT
            or any(name in payload and (type(payload[name]) is not int or payload[name] != value)
                   for name, value in (('offset', 0), ('limit', LIMIT)))):
        raise SamError('invalid_response', diagnostics)
    rows, seen = [], set()
    for row in payload['opportunitiesData']:
        if (not isinstance(row, dict) or not isinstance(row.get('noticeId'), str)
                or not NOTICE_ID.fullmatch(row['noticeId']) or row['noticeId'] in seen
                or any(value is not None and type(value) not in (str, int, bool)
                       or isinstance(value, str) and len(value) > 2000
                       for name, value in row.items() if name in PUBLIC_FIELDS)):
            raise SamError('invalid_response', diagnostics)
        seen.add(row['noticeId'])
        safe = {name: _public_scalar(row[name], key) for name in PUBLIC_FIELDS if name in row}
        route = _description_route(row.get('description'), row['noticeId'])
        if route:
            safe['description_route'] = route
        rows.append(safe)
    diagnostics.update(outcome='ok', total_records=len(rows), returned_records=len(rows))
    return rows, diagnostics


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fetch_description(api_key, notice_id, *, route, opener=None):
    """Explicit preview only: one small description, returned ephemerally as text."""
    if (not isinstance(notice_id, str) or not NOTICE_ID.fullmatch(notice_id)
            or not isinstance(route, str) or route not in DESCRIPTION_ROUTES):
        raise SamError('invalid_description_route', {'request_count': 0})
    payload, diagnostics, key = _request(api_key, 'https://api.sam.gov' + DESCRIPTION_ROUTES[route],
        {'noticeid': notice_id}, DESCRIPTION_MAX_BYTES, opener)
    if not isinstance(payload, dict) or not isinstance(payload.get('description'), str):
        raise SamError('invalid_response', diagnostics)
    parser = _PlainText()
    try:
        parser.feed(payload['description'])
        parser.close()
    except Exception:
        raise SamError('invalid_response', diagnostics) from None
    text = redacted(' '.join(parser.parts), key)
    text = re.sub(r'https?://\S*api\.sam\.gov\S*', '[API link omitted]', text, flags=re.I)
    text = re.sub(r'api[_-]?key\s*=\s*\S+', '[credential omitted]', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()[:20000]
    diagnostics['outcome'] = 'ok'
    return text, diagnostics
