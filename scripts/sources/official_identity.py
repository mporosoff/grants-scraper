"""Exact Grants.gov links, including the official Simpler legacy-record link.

Only identity is resolved here. Deadlines, sponsor facts and submission stages
continue to come from the canonical Grants.gov record and its notice evidence.
"""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

VERSION = 1


def official_path(url, hosts):
    if not isinstance(url, str) or url != url.strip() or any(ord(c) < 32 for c in url):
        return None
    try:
        p = urlsplit(url or '')
        if (p.scheme != 'https' or p.hostname not in hosts or p.username or p.password
                or p.port not in (None, 443) or p.query or p.fragment):
            return None
        return p.path.rstrip('/')
    except (TypeError, ValueError):
        return None


def grants_id(url):
    path = official_path(url, {'www.grants.gov', 'grants.gov'})
    match = re.fullmatch(r'/search-results-detail/([1-9][0-9]{0,11})', path or '')
    return match[1] if match else None


def simpler_url(url):
    path = official_path(url, {'simpler.grants.gov'})
    if re.fullmatch(r'/opportunity/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', path or ''):
        return 'https://simpler.grants.gov' + path
    return None


class LegacyLink(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = None
        self.text = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.active = grants_id(dict(attrs).get('href'))
            self.text = []

    def handle_data(self, text):
        if self.active:
            self.text.append(text)

    def handle_endtag(self, tag):
        if tag == 'a':
            label = ' '.join(' '.join(self.text).split()).casefold()
            if self.active and label in {'view on grants.gov', 'view version history on grants.gov'}:
                self.ids.add(self.active)
            self.active = None


def valid_receipt(value, url):
    return (isinstance(value, dict) and value.get('version') == VERSION
            and value.get('source_url') == url and simpler_url(url) == url
            and grants_id(value.get('target_url')) is not None
            and re.fullmatch('[a-f0-9]{64}', str(value.get('utf8_sha256', ''))) is not None
            and isinstance(value.get('retrieved_at'), str)
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}T[^\s]+', value['retrieved_at']) is not None
            and value.get('locator') == 'View on Grants.gov / version-history anchor')


def resolve(records, cache, *, client=None, limit=20):
    """Bounded public GETs; cache immutable UUID-to-legacy-ID provenance as data."""
    stats = dict(attempted=0, reused=0, resolved=0, unresolved=0)
    seen = {}
    for record in records:
        if not str(record.get('opportunity_id', '')).startswith('vpr-email:'):
            continue
        url = simpler_url(record.get('funding_opportunity_url') or record.get('detail_page'))
        if not url:
            continue
        receipt = cache.get(url)
        if valid_receipt(receipt, url):
            stats['reused'] += 1
        elif url in seen:
            receipt = seen[url]
        elif stats['attempted'] < limit:
            stats['attempted'] += 1
            if client is None:
                from .http import PoliteClient
                client = PoliteClient()
            # Network/parse failure must be visible; no guessed ID or fuzzy match.
            text = client.get_text(url)
            if simpler_url(client.last_url) != url:
                raise ValueError('Simpler identity page redirected away from its exact UUID')
            links = LegacyLink(); links.feed(text); links.close()
            receipt = None
            if len(links.ids) == 1:
                receipt = dict(version=VERSION, source_url=url,
                    target_url='https://www.grants.gov/search-results-detail/' + next(iter(links.ids)),
                    utf8_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    locator='View on Grants.gov / version-history anchor')
                cache[url] = receipt
            seen[url] = receipt
        else:
            receipt = None
        if valid_receipt(receipt, url):
            record['official_identity'] = dict(receipt)
            stats['resolved'] += 1
        else:
            stats['unresolved'] += 1
    return stats


def record_grants_id(record):
    links = [record.get(k) for k in ('detail_page', 'funding_opportunity_url')]
    ids = {ident for url in links if (ident := grants_id(url))}
    receipt = record.get('official_identity')
    for url in links:
        normalized = simpler_url(url)
        if normalized and valid_receipt(receipt, normalized):
            ids.add(grants_id(receipt['target_url']))
    return next(iter(ids)) if len(ids) == 1 else None
