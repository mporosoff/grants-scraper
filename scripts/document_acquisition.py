"""Bounded public notice representations for explicitly supported source routes."""
from html import escape, unescape
from html.parser import HTMLParser
import hashlib
import math
import re
from time import monotonic
from urllib.parse import urlsplit

from scripts.sources import sam_public
from scripts.sources.sam_api import SamError


SAM_POLICY = 'SAMpublic-description-v1'
NASA_POLICY = 'NASAtlsprofile-v1'
NASA_HOSTS = frozenset({'solicitation.nasaprs.com', 'nspires.nasaprs.com'})
MAX_SAM_SECONDS = 30
SAM_ROUTE = re.compile(r'/(?:workspace/contract/)?opp/([0-9a-f]{32})/view/?')


class DocumentAcquisitionError(ValueError):
    """Only fixed public reason/status fields escape a failed acquisition."""
    def __init__(self, reason, http_status=None):
        self.document_reason = reason
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__('Official notice acquisition failed: ' + reason)


def _public_https(url):
    if not isinstance(url, str) or len(url) > 2048 or any(character.isspace() for character in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    return parsed


def sam_notice_id(url):
    parsed = _public_https(url)
    if not parsed or parsed.hostname != 'sam.gov' or '?' in url or '#' in url:
        return None
    match = SAM_ROUTE.fullmatch(parsed.path)
    return match[1] if match else None


def acquisition_identity(url):
    """Acquisition policy only; never changes the identity of verified facts."""
    if sam_notice_id(url):
        return SAM_POLICY
    parsed = _public_https(url)
    return NASA_POLICY if parsed and parsed.hostname in NASA_HOSTS else None


def configure_session(session):
    """Add the measured NASA suite only on the two exact HTTPS origins.

    Other hosts, including cross-origin redirect targets, retain the session's
    default adapter. Certificate/hostname verification and security level stay
    unchanged in the existing compatibility adapter.
    """
    from scripts.sources.http import _LegacyCipherAdapter
    adapter = _LegacyCipherAdapter()
    for host in NASA_HOSTS:
        session.mount('https://' + host + '/', adapter)
        session.mount('https://' + host + ':443/', adapter)


class _Description(HTMLParser):
    # No remote attributes, scripts, private resource URIs, forms, or embedded
    # JSON become the document representation. Only owned description markup
    # and text are retained for the ordinary structural reader.
    TAGS = frozenset({'p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                      'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tfoot',
                      'tr', 'td', 'th', 'strong', 'em', 'b', 'i', 'u', 'span', 'a', 'br', 'hr',
                      'blockquote', 'pre', 'sup', 'sub'})
    OMIT = frozenset({'script', 'style', 'head', 'template', 'iframe', 'object', 'svg', 'form'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.text = [], []
        self.omitted = []

    def handle_starttag(self, tag, attrs):
        if self.omitted or tag in self.OMIT:
            self.omitted.append(tag)
        elif tag in self.TAGS:
            self.parts.append('<' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        if not self.omitted and tag in self.TAGS:
            self.parts.append('<' + tag + '>')

    def handle_endtag(self, tag):
        if self.omitted:
            if tag in self.omitted:
                del self.omitted[self.omitted.index(tag):]
        elif tag in self.TAGS and tag not in {'br', 'hr'}:
            self.parts.append('</' + tag + '>')

    def handle_data(self, text):
        if not self.omitted:
            self.parts.append(escape(text, quote=False))
            self.text.append(text)


def _representation(bodies, maximum):
    fragments, size = [], 0
    for body in bodies:
        parser = _Description()
        parser.feed(body)
        parser.close()
        if not unescape(''.join(parser.text)).strip():
            continue
        fragment = ('<section>' + ''.join(parser.parts) + '</section>').encode('utf-8')
        size += len(fragment)
        if size > maximum:
            raise DocumentAcquisitionError('sam_description_oversize')
        fragments.append(fragment)
    if not fragments:
        raise DocumentAcquisitionError('sam_description_missing')
    content = b'<html><body>\n' + b'\n'.join(fragments) + b'\n</body></html>'
    if len(content) > maximum:
        raise DocumentAcquisitionError('sam_description_oversize')
    return content


def read_document(url, headers=None, *, timeout=30, maximum_bytes=sam_public.MAX_BYTES):
    """Return a verified SAM description response, or None for an unclaimed URL.

    Incoming conditionals and credentials are intentionally not forwarded. Two
    authenticated public endpoint reads produce fresh owned description bytes;
    this path never claims HTTP 304 from a synthetic representation.
    """
    identifier = sam_notice_id(url)
    if identifier is None:
        return None
    limits = timeout if isinstance(timeout, tuple) else (timeout,)
    if (not limits or any(isinstance(value, bool) or not isinstance(value, (int, float))
                          or not math.isfinite(value) or value <= 0 for value in limits)
            or type(maximum_bytes) is not int or maximum_bytes <= 0):
        raise DocumentAcquisitionError('sam_notice_schema')
    deadline = monotonic() + min(max(limits), MAX_SAM_SECONDS)
    try:
        bodies, notice, _ = sam_public.fetch_notice_description(identifier, deadline=deadline)
    except SamError as error:
        diagnostics = error.diagnostics
        outcome = diagnostics.get('outcome')
        reason = ('sam_acquisition_timeout' if diagnostics.get('failure_class') == 'timeout'
                  else 'sam_notice_not_current' if outcome == 'document_notice_not_current'
                  else 'sam_description_missing' if outcome == 'document_description_missing'
                  else 'sam_notice_schema' if outcome == 'document_description_schema'
                       or diagnostics.get('failure_class') == 'response_schema'
                  else 'sam_notice_unavailable')
        raise DocumentAcquisitionError(reason, diagnostics.get('http_status')) from None
    content = _representation(bodies, min(maximum_bytes, sam_public.MAX_BYTES))
    if monotonic() >= deadline:
        raise DocumentAcquisitionError('sam_acquisition_timeout')
    return {'status_code': 200, 'content': content, 'url': url,
            'content_type': 'text/html; charset=utf-8', 'encoding': 'utf-8',
            'etag': None, 'last_modified': None,
            'retrieval_provenance': {
                'schema_version': 1, 'policy': SAM_POLICY, 'representation': 'owned-description-html',
                'notice_id': identifier, 'api_url': 'https://sam.gov/api/prod/opps/v2/opportunities/' + identifier,
                'body_sha256': hashlib.sha256(content).hexdigest(),
                'review_sha256': notice['review_sha256'], 'organization_id': notice['organization_id'],
                'solicitation_number': notice['solicitation_number']}}
