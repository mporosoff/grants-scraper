"""Bounded retries for read-only GitHub evidence, preserving exact response bytes."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import subprocess
import sys
import time


ATTEMPTS = 3
MAX_RETRY_DELAY = 30


class ReadFailure(subprocess.SubprocessError):
    """A safe diagnostic without response bodies, credentials, or signed URLs."""


def _response(raw):
    # --include supplies the final HTTP headers even when gh exits nonzero.
    # Do not decode the body: this transport also reads immutable artifact ZIPs.
    match = re.match(rb'HTTP/\S+ (\d{3})[^\r\n]*\r?\n', raw)
    separator = re.search(rb'\r?\n\r?\n', raw[:65536])
    if not match or not separator:
        return None, {}, raw
    headers = {}
    for line in raw[match.end():separator.start()].splitlines():
        key, colon, value = line.partition(b':')
        if colon:
            headers[key.decode('ascii', errors='ignore').lower()] = value.decode('ascii', errors='ignore').strip()
    return int(match[1]), headers, raw[separator.end():]


def _retry_after(headers):
    value = headers.get('retry-after')
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                return None
            return max(0, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def get(repository, path):
    """GET only; mutations, authentication denials, and invalid evidence do not retry."""
    command = ['gh', 'api', '--method', 'GET', '--include', f'repos/{repository}/{path}']
    route = re.sub(r'[^A-Za-z0-9_./-]', '_', path.split('?', 1)[0])[:160]
    history = []
    for attempt in range(1, ATTEMPTS + 1):
        status, headers, kind = None, {}, 'command_failure'
        try:
            raw = subprocess.check_output(command, stderr=subprocess.PIPE, timeout=60)
        except subprocess.TimeoutExpired:
            kind = 'timeout'
        except subprocess.CalledProcessError as error:
            status, headers, _ = _response(error.output or b'')
            diagnostic = (error.stderr or b'').decode('utf-8', errors='replace')
            if status is None:
                match = re.search(r'\(HTTP (\d{3})\)', diagnostic)
                status = int(match[1]) if match else None
            # Use stderr only to classify common transport failures, never retain it.
            if status is None and re.search(r'(?i)\b(timeout|timed out|connection reset|connection refused|'
                                            r'temporary failure|no such host|unexpected EOF|TLS handshake)\b', diagnostic):
                kind = 'network'
        else:
            status, headers, body = _response(raw)
            if status is not None and 200 <= status < 300:
                return body
            kind = 'invalid_http_response'
        retryable = kind in ('timeout', 'network') or status == 429 or status is not None and 500 <= status <= 599
        retry_after = _retry_after(headers)
        delay = max(2 ** attempt, retry_after or 0)
        retry = retryable and attempt < ATTEMPTS and delay <= MAX_RETRY_DELAY
        record = {'attempt': attempt, 'status': status, 'kind': kind, 'retry': retry}
        request_id = headers.get('x-github-request-id', '')
        if re.fullmatch(r'[A-Za-z0-9:._-]{1,128}', request_id):
            record['request_id'] = request_id
        if retry_after is not None:
            record['retry_after_seconds'] = min(retry_after, 86400)
        if retry:
            record['delay_seconds'] = delay
        history.append(record)
        print(json.dumps({'github_read': route, **record}, separators=(',', ':')), file=sys.stderr)
        if not retry:
            summary = ','.join(str(row['status'] or row['kind']) for row in history)
            raise ReadFailure(f'GitHub GET {route} failed after {attempt} attempt(s): {summary}') from None
        time.sleep(delay)
    raise AssertionError('Unreachable bounded GitHub read')
