"""Exact NSF edition identity from official links or current program guidelines.

A mutable program URL is not itself an edition identity. Its bounded public
lookup produces a day-bound receipt; no title or default agency is promoted.
"""
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

HOSTS = {'nsf.gov', 'www.nsf.gov'}
KINDS = {'nsf_view_guidelines', 'nsf_program_guidelines'}


def number_key(value):
    value = re.sub(r'[^a-z0-9]', '', str(value or '').casefold())
    value = re.sub(r'^nsf', '', value)
    return value if re.fullmatch(r'\d{5}|pd\d{6}', value) else None


def _parts(url):
    if not isinstance(url, str) or url != url.strip() or any(ord(c) < 32 for c in url):
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password
                or p.port not in (None, 443) or p.fragment):
            return None
        return p
    except ValueError:
        return None


def edition_key(url):
    p = _parts(url)
    if p is None:
        return None
    if not p.query:
        match = re.fullmatch(r'/funding/opportunities/[a-z0-9]+(?:-[a-z0-9]+)*/'
            r'((?:nsf\d{2}-\d{3})|(?:pd\d{2}-\d{4}))(?:/solicitation)?/?', p.path)
        return number_key(match[1]) if match else None
    query = parse_qsl(p.query, keep_blank_values=True)
    if p.path == '/publications/pub_summ.jsp' and len(query) == 1 and query[0][0] == 'ods_key':
        value = query[0][1]
        return number_key(value) if re.fullmatch(r'nsf\d{5}|pd\d{6}', value) else None
    return None


def program_url(url):
    p = _parts(url)
    if p is not None and not p.query and re.fullmatch(
            r'/funding/opportunities/[a-z0-9]+(?:-[a-z0-9]+)*/?', p.path):
        return 'https://www.nsf.gov' + p.path.rstrip('/')
    return None


class Guidelines(HTMLParser):
    """Only the page-owned guidelines sections may identify the program."""
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.heading = None
        self.heading_text = []
        self.section = None
        self.section_level = 0
        self.text = []
        self.anchor = None
        self.anchor_text = []
        self.proofs = set()
        self.hidden = 0

    def _finish_section(self):
        if self.section == 'program guidelines':
            for match in re.finditer(r'\bApply to (PD\s*\d{2}-\d{4}) as follows\s*:',
                                     ' '.join(' '.join(self.text).split()), re.I):
                self.proofs.add((number_key(match[1]), self.url, 'nsf_program_guidelines'))
        self.section = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if self.hidden:
            return
        if re.fullmatch(r'h[1-6]', tag):
            level = int(tag[1])
            if self.section and level <= self.section_level:
                self._finish_section()
            self.heading = tag
            self.heading_text = []
        if tag == 'a':
            self.anchor = urljoin(self.url, dict(attrs).get('href', ''))
            self.anchor_text = []

    def handle_data(self, data):
        if self.hidden:
            return
        if self.heading:
            self.heading_text.append(data)
        if self.section:
            self.text.append(data)
        if self.anchor:
            self.anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag == self.heading:
            label = ' '.join(' '.join(self.heading_text).split()).casefold()
            if label in {'view guidelines', 'program guidelines'}:
                self._finish_section()
                self.section, self.section_level = label, int(tag[1])
            self.heading = None
        if tag == 'a':
            label = ' '.join(' '.join(self.anchor_text).split())
            key = edition_key(self.anchor)
            if (self.section == 'view guidelines' and key
                    and re.fullmatch(r'(?:NSF\s*\d{2}-\d{3}|PD\s*\d{2}-\d{4})', label, re.I)
                    and number_key(label) == key):
                # A solicitation under a different program slug is a cross-reference.
                target = _parts(self.anchor)
                if (target.path.startswith(urlsplit(self.url).path + '/')
                        or target.path == '/publications/pub_summ.jsp'):
                    self.proofs.add((key, self.anchor, 'nsf_view_guidelines'))
            self.anchor = None

    def close(self):
        super().close()
        self._finish_section()


def receipt_for(text, source_url, final_url, *, checked_on, retrieved_at):
    final = program_url(final_url)
    if not final:
        raise ValueError('NSF identity page redirected outside a supported official program page')
    parser = Guidelines(final)
    parser.feed(text); parser.close()
    if len({key for key, _, _ in parser.proofs}) != 1:
        return None
    key, target, kind = sorted(parser.proofs)[0]
    return dict(version=1, kind=kind, source_url=source_url, final_url=final,
        target_url=target, number=key, checked_on=checked_on, retrieved_at=retrieved_at,
        utf8_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        locator='View guidelines / exact edition anchor' if kind == 'nsf_view_guidelines'
                else 'Program guidelines / Apply to PD number')


def valid_receipt(value, url, as_of=None):
    if not (isinstance(value, dict) and value.get('version') == 1 and value.get('kind') in KINDS
            and value.get('source_url') == url and program_url(url) == url
            and program_url(value.get('final_url')) == value.get('final_url')
            and number_key(value.get('number')) == value.get('number')
            and re.fullmatch(r'[a-f0-9]{64}', str(value.get('utf8_sha256', '')))):
        return False
    try:
        checked = date.fromisoformat(value['checked_on'])
        retrieved = datetime.fromisoformat(value['retrieved_at'].replace('Z', '+00:00'))
        if retrieved.tzinfo is None or (as_of is not None and checked != as_of):
            return False
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    if value['kind'] == 'nsf_program_guidelines':
        return (value.get('locator') == 'Program guidelines / Apply to PD number'
                and value['number'].startswith('pd') and value.get('target_url') == value['final_url'])
    target = _parts(value.get('target_url'))
    return (value.get('locator') == 'View guidelines / exact edition anchor'
            and edition_key(value.get('target_url')) == value['number'] and target is not None
            and (target.path.startswith(urlsplit(value['final_url']).path + '/')
                 or target.path == '/publications/pub_summ.jsp'))


def record_identity(record, as_of=None):
    """Return (state, key); an explicit conflicting edition is never rewritten."""
    if not str(record.get('opportunity_id') or '').startswith('vpr-email:'):
        return None, None
    links = [record.get(k) for k in ('detail_page', 'funding_opportunity_url')]
    editions = {key for url in links if (key := edition_key(url))}
    programs = {url for link in links if (url := program_url(link))}
    if not editions and not programs:
        return None, None
    receipt = record.get('official_identity')
    for url in programs:
        if valid_receipt(receipt, url, as_of):
            editions.add(receipt['number'])
        else:
            return 'unresolved', None
    if len(editions) != 1:
        return 'conflict', None
    key = next(iter(editions))
    supplied = record.get('opportunity_number')
    if supplied and number_key(supplied) != key:
        return 'conflict', None
    from scripts.solicitation_identity import sponsor_identity
    sponsor = sponsor_identity(record)
    if sponsor is not None and sponsor != 'nsf':
        return 'conflict', None
    return 'resolved', key
