"""One read-only SAM.gov access check; no ingestion, redirects or retries.

The key stays in the invoking process. Only selected public notice metadata and
bounded status/quota information enter the report; raw responses are discarded.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote, quote_plus, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://api.sam.gov/opportunities/v2/search'
MAX_BYTES = 1024 * 1024
LIMIT = 3
ERROR_CODES = frozenset({'API_KEY_MISSING', 'API_KEY_INVALID', 'API_KEY_DISABLED',
    'API_KEY_UNAUTHORIZED', 'API_KEY_UNVERIFIED', 'OVER_RATE_LIMIT'})
PUBLIC_FIELDS = ('noticeId', 'title', 'solicitationNumber', 'fullParentPathName',
    'postedDate', 'type', 'active', 'responseDeadLine', 'naicsCode', 'classificationCode')


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
    return value


def quota(headers):
    result = {}
    for name in ('X-RateLimit-Limit', 'X-RateLimit-Remaining', 'Retry-After'):
        value = headers.get(name, '')
        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value):
            result[name] = int(value)
    return result


def probe(api_key, *, today=None, opener=None):
    today = today or datetime.now(timezone.utc).date()
    key = api_key.strip() if isinstance(api_key, str) else ''
    query = {'postedFrom': (today - timedelta(days=90)).strftime('%m/%d/%Y'),
             'postedTo': today.strftime('%m/%d/%Y'), 'title': 'Broad Agency Announcement',
             'ptype': 'o', 'limit': LIMIT, 'offset': 0}
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'endpoint': ENDPOINT, 'query': query, 'request_count': 0, 'http_status': None,
              'api_access_verified': False, 'outcome': 'missing_key', 'rate_limit': {},
              'samples': [], 'catalog_changed': False, 'team_generation': False}
    if not key:
        return report
    request = Request(ENDPOINT + '?' + urlencode(query | {'api_key': key}),
        headers={'Accept': 'application/json',
                 'User-Agent': 'Funding-Finder-SAM-Access-Check/1.0'}, method='GET')
    client = opener if opener is not None else build_opener(NoRedirect())
    report['request_count'] = 1
    try:
        with client.open(request, timeout=30) as response:
            report['http_status'] = response.status
            report['rate_limit'] = quota(response.headers)
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        report['http_status'] = error.code
        report['rate_limit'] = quota(error.headers or {})
        report['outcome'] = 'http_error'
        # Do not print the exception or error body: either may echo the key/URL.
        try:
            raw = error.read(MAX_BYTES + 1)
            payload = json.loads(raw) if len(raw) <= MAX_BYTES else {}
            detail = payload.get('error', {}) if isinstance(payload, dict) else {}
            code = detail.get('code') if isinstance(detail, dict) else None
            if code in ERROR_CODES:
                report['error_code'] = code
        except Exception:
            pass
        finally:
            error.close()
        return redacted(report, key)
    except Exception:
        report['outcome'] = 'network_error'
        return redacted(report, key)
    if len(raw) > MAX_BYTES:
        report['outcome'] = 'response_too_large'
        return redacted(report, key)
    try:
        payload = json.loads(raw)
        rows = payload['opportunitiesData']
        total = payload['totalRecords']
        if (report['http_status'] != 200 or not isinstance(rows, list)
                or type(total) is not int or total < len(rows)
                or any(not isinstance(row, dict) for row in rows)):
            raise ValueError('Invalid documented response')
        samples = []
        for row in rows[:LIMIT]:
            sample = {name: redacted(row[name], key)[:300] for name in PUBLIC_FIELDS
                      if isinstance(row.get(name), str)}
            sample['description_present'] = bool(row.get('description'))
            samples.append(sample)
        report.update(api_access_verified=True, outcome='ok', total_records=total,
                      returned_records=len(rows), samples=samples)
    except (ValueError, KeyError, TypeError):
        report['outcome'] = 'invalid_response'
    return redacted(report, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') == 'true' and any(os.environ.get(name) != expected for name, expected in {
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
        'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/sam-api-access-check.yml@refs/heads/main',
    }.items()):
        report = {'schema_version': 1, 'api_access_verified': False, 'request_count': 0,
                  'outcome': 'invalid_workflow_context'}
    else:
        report = probe(os.environ.get('SAM_API_KEY', ''))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    args.report.write_text(encoded, encoding='utf8')
    print(encoded, end='')
    return 0 if report['api_access_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
