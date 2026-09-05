"""One official-source adapter for DARPA DO/QBI and IARPA research calls.

DARPA's public table JSON is the discovery inventory, not its truncated RSS
feed. Individual PA topics are verified on their linked program pages. IARPA's
open R&D table is the inventory; program status and proposal dates confirm
actionability. Neither program directories nor SAM.gov search are inventories.
"""

from collections import Counter
from datetime import date
from html import unescape
import json
import re
from urllib.parse import urljoin, urlparse

from scripts.solicitation_identity import normalized_number
from ..base import CanonicalOpportunity, SourceAdapter, to_iso_date
from ..http import PoliteClient
from ..registry import register


DARPA_LIST = "https://www.darpa.mil/json/opportunity.json"
IARPA_LIST = "https://www.iarpa.gov/engage-with-us/open-r-d-opportunities"
DARPA = "Defense Advanced Research Projects Agency (DARPA)"
IARPA = "Intelligence Advanced Research Projects Activity (IARPA)"
_CHILD = re.compile(r"darpapa(\d{2})(\d{2})(\d{2})")
_PARENT = re.compile(r"darpapa\d{4}")
_DARPA_SCOPE = re.compile(r"Disruption Opportunit(?:y|ies)|Quantum Benchmarking Initiative|\bQBIT?\b", re.I)
_NUMBER = re.compile(r"[A-Z][A-Z0-9]*(?:[-\s]+[A-Z0-9]+)*\d", re.I)
_LINK = re.compile(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', re.I | re.S)
_NON_CALL = re.compile(
    r"\b(?:request for information|RFI|sources sought|special notice|"
    r"proposers?[’']? day|industry day|information session|registration|"
    r"draft|forecast|presolicitation|pre-solicitation|future program)\b", re.I
)
_NOT_ACCEPTING = re.compile(
    r"\b(?:cancelled|canceled|withdrawn|closed|not accepting|"
    r"not (?:a formal )?(?:request|solicitation)|"
    r"proposals are not (?:being )?(?:requested|accepted))\b", re.I
)


def plain(html):
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def official_url(value, base, host, prefix=None):
    url = urljoin(base, unescape(value or ""))
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in {host, "www." + host}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return None
    if prefix and not parsed.path.startswith(prefix):
        return None
    return url


def notice_url(value):
    url = official_url(value, "https://sam.gov", "sam.gov")
    if url and re.fullmatch(r"/(?:workspace/contract/)?opp/[a-f0-9]{32}/view/?", urlparse(url).path, re.I):
        return url
    return None


def parsed_date(text):
    # DARPA uses Sept./Nov.; IARPA uses full month names.
    text = re.sub(r"\bSept\.?", "Sep", plain(text), flags=re.I)
    text = re.sub(r"\b([A-Za-z]{3})\.", r"\1", text)
    return to_iso_date(text)


def current(close, opened, as_of):
    if not close:
        raise ValueError("Missing or unparseable research submission deadline")
    if (date.fromisoformat(close) - as_of).days > 366 * 6:
        raise ValueError("Implausible research submission deadline")
    return as_of.isoformat() <= close and (not opened or opened <= as_of.isoformat())


def darpa_inventory(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 2000:
        raise ValueError("DARPA opportunity inventory missing or unexpected shape")
    grouped = {}
    required = {"title", "field_opportunity_number", "field_close_date", "field_external_url"}
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("DARPA opportunity row schema changed")
        number = plain(row["field_opportunity_number"])
        key = normalized_number(number)
        child = _CHILD.fullmatch(key)
        if not child:
            if _PARENT.fullmatch(key):
                continue  # Recognized umbrellas are a legitimate non-child population.
            text = " ".join(plain(row.get(field)) for field in (
                "title", "field_body_with_summary", "field_body_with_summary_1"
            ))
            # A nonempty inventory is not sufficient proof of a healthy zero:
            # in-scope research rows with unknown identifiers mean parser drift.
            if (key.startswith("darpapa") or _DARPA_SCOPE.search(text)) and not (
                _NON_CALL.search(plain(row["title"])) or _NOT_ACCEPTING.search(text)
            ):
                raise ValueError(f"Unrecognized DARPA research solicitation number: {number!r}")
            continue
        number = "DARPA-PA-" + "-".join(child.groups())
        row = {**row, "field_opportunity_number": number}
        prior = grouped.setdefault(key, dict(row))
        for field, value in row.items():
            if field in ("field_body_with_summary", "field_body_with_summary_1"):
                if len(value or "") > len(prior.get(field) or ""):
                    prior[field] = value
            elif prior.get(field) and value and prior[field] != value and field in required:
                raise ValueError(f"Conflicting DARPA inventory rows for {number}")
            elif value and not prior.get(field):
                prior[field] = value
    return list(grouped.values())


def darpa_program_url(row):
    body = row.get("field_body_with_summary") or row.get("field_body_with_summary_1") or ""
    for href, _ in _LINK.findall(body):
        url = official_url(href, DARPA_LIST, "darpa.mil", "/research/programs/")
        if url:
            return url
    return None


def darpa_opportunity_block(html, number):
    # Scope dates and action links to the exact child, never its PA umbrella
    # or another topic on the same program page (QBI has three blocks).
    blocks = [match for match in re.finditer(r"<p\b[^>]*>(.*?)</p>", html, re.I | re.S)
              if _CHILD.fullmatch(normalized_number(plain(match.group(1))))
              or _PARENT.fullmatch(normalized_number(plain(match.group(1))))]
    for index, match in enumerate(blocks):
        if normalized_number(plain(match.group(1))) == normalized_number(number):
            end = blocks[index + 1].start() if index + 1 < len(blocks) else len(html)
            return html[match.end():end].split("</div>", 1)[0]
    raise ValueError(f"DARPA program page has no exact solicitation block for {number}")


def labelled_date(block, label):
    found = re.search(rf"\b{label}:\s*([A-Za-z.]+ \d{{1,2}}, \d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})", plain(block), re.I)
    return parsed_date(found.group(1)) if found else None


def darpa_description(html, fallback):
    fragments = re.findall(r'<div\b[^>]*class="[^"]*field--name-(?:field-text|field-body-with-summary)\b[^"]*"[^>]*>(.*?)</div>', html, re.S)
    descriptions = []
    for fragment in fragments:
        if re.search(r"<h[1-6][^>]*>\s*(?:Opportunities|Opportunity|Office|Resources)\b", fragment, re.I):
            continue
        descriptions.append(plain(fragment))
    return " ".join(descriptions)[:11000] or fallback


def iarpa_inventory(html):
    table = re.search(r'<table\b[^>]*id=[\"\']rs[\"\'][^>]*>(.*?)</table>', html, re.I | re.S)
    if not table or not re.search(r"R\s*&\s*D\s*#", plain(table.group(1))):
        raise ValueError("IARPA open R&D table schema changed")
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)
        if not cells:
            continue
        if len(cells) != 2:
            raise ValueError("IARPA R&D row schema changed")
        title, number = plain(cells[0]), plain(cells[1])
        if _NON_CALL.search(title) or _NOT_ACCEPTING.search(title):
            continue
        if not title or not _NUMBER.fullmatch(number):
            raise ValueError("IARPA R&D row missing solicitation identity")
        urls = [official_url(href, IARPA_LIST, "iarpa.gov", "/research-programs/")
                for href, _ in _LINK.findall(cells[0])]
        url = next((url for url in urls if url), None)
        if not url:
            raise ValueError(f"IARPA research detail link missing for {number}")
        rows.append({"title": title, "number": number, "url": url})
    if not rows and not re.search(r"There are currently no open R&D Opportunities\.", plain(table.group(1))) and not re.search(r"<td\b", table.group(1), re.I):
        raise ValueError("IARPA empty table lacks an explicit no-open-calls result")
    return rows


def iarpa_fields(html):
    return {plain(label).casefold(): plain(value) for label, value in re.findall(
        r'<h3\b[^>]*class="[^"]*baa_content_block-label[^"]*"[^>]*>(.*?)</h3>\s*'
        r'<p\b[^>]*class="[^"]*baa_content_block-content[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I
    )}


class DarpaIarpaAdapter(SourceAdapter):
    slug = "darpa-iarpa"
    display_name = "DARPA / IARPA research solicitations"
    source_type = "Federal"
    enabled = True
    min_records = 0  # Verified empty inventories are a healthy result.
    max_records = 200
    retain_on_failure = False  # Withdrawn calls must not survive a failed refresh.

    def __init__(self):
        super().__init__()
        self._client = PoliteClient()

    def fetch(self):
        self.diagnostics = {}
        rows = json.loads(self._client.get_text(DARPA_LIST))
        iarpa_html = self._html(IARPA_LIST)
        urls = set()
        for row in darpa_inventory(rows):
            url = darpa_program_url(row)
            if url:
                urls.add(url)
        urls.update(row["url"] for row in iarpa_inventory(iarpa_html))
        if len(urls) > self.max_records:
            raise ValueError("Research detail inventory exceeds fetch bound")
        return {"darpa": rows, "iarpa": iarpa_html,
                "pages": {url: self._html(url) for url in sorted(urls)}}

    def _html(self, url):
        html = self._client.get_text(url)
        # DARPA sometimes labels UTF-8 HTML as ISO-8859-1 in its HTTP header.
        if re.search(r'charset=["\s]*utf-8', html, re.I):
            try:
                return html.encode("latin-1").decode("utf-8")
            except UnicodeError:
                pass
        return html

    def parse(self, payload):
        as_of = self.context.get("as_of") or date.today()
        rows = darpa_inventory(payload["darpa"])
        iarpa_rows = iarpa_inventory(payload["iarpa"])
        pages = payload["pages"]
        skipped = Counter()
        opportunities = {}
        date_overrides = []

        for row in rows:
            number = plain(row["field_opportunity_number"]).upper()
            summary = plain(row.get("field_body_with_summary") or row.get("field_body_with_summary_1"))
            text = row["title"] + " " + summary
            if _NON_CALL.search(row["title"]) or _NOT_ACCEPTING.search(text):
                skipped["darpa_not_actionable_research"] += 1
                continue
            if (not _DARPA_SCOPE.search(text)
                    or not re.search(r"inviting submissions|solicit|invites? proposals", summary, re.I)):
                raise ValueError(f"DARPA child research scope/submission evidence missing: {number}")
            url = darpa_program_url(row)
            if not url or not notice_url(row["field_external_url"]):
                raise ValueError(f"DARPA required official route missing or unsupported: {number}")
            if url not in pages:
                raise ValueError(f"DARPA detail page missing: {url}")
            block = darpa_opportunity_block(pages[url], number)
            if _NOT_ACCEPTING.search(plain(block)):
                skipped["darpa_not_accepting"] += 1
                continue
            close = labelled_date(block, "Deadline")
            opened = labelled_date(block, "Published")
            if not opened:
                raise ValueError(f"DARPA publication date missing or unparseable: {number}")
            if not current(close, opened, as_of):
                skipped["darpa_outside_submission_window"] += 1
                continue
            links = [notice_url(href) for href, label in _LINK.findall(block) if re.search(r"solicitation", plain(label), re.I)]
            if not links or any(not link for link in links):
                raise ValueError(f"DARPA exact solicitation action missing or unsupported: {number}")
            # Both sources must identify the same notice. The public and
            # workspace SAM routes are equivalent presentations of that ID.
            notice_ids = {urlparse(link).path.rstrip("/").split("/")[-2].lower() for link in links}
            expected_id = urlparse(row["field_external_url"]).path.rstrip("/").split("/")[-2].lower()
            if notice_ids != {expected_id}:
                raise ValueError(f"DARPA conflicting exact solicitation action: {number}")
            action = links[0]
            if close != row["field_close_date"]:
                date_overrides.append({"number": number, "listing_date": row["field_close_date"], "program_date": close, "source_url": url})
            description = darpa_description(pages[url], summary)
            # The official topic terms supply technical context to opaque names.
            topics = plain(row.get("field_research_topics", "")).replace("|", "; ")
            opportunities[("darpa", normalized_number(number))] = CanonicalOpportunity(
                title=plain(row["title"]), external_id="darpa-" + normalized_number(number),
                opportunity_number=number, agency=DARPA, url=action,
                description=f"{summary} {description} Research topics: {topics}",
                posted_date=opened, close_date=close,
                deadline_note=f"Submission deadline for {number} on the official DARPA program page: {url}",
                additional_deadlines=[],
            )
            # Use the exact page as deadline provenance while preserving the
            # direct solicitation as the card's action link.
            opportunities[("darpa", normalized_number(number))].extra["deadline_page"] = url

        for row in iarpa_rows:
            html = pages.get(row["url"])
            if html is None:
                raise ValueError(f"IARPA detail page missing: {row['url']}")
            status = re.search(r'<p\b[^>]*class="[^"]*baa_content_status[^"]*"[^>]*>(.*?)</p>', html, re.I | re.S)
            if not status:
                raise ValueError(f"IARPA solicitation status markup missing: {row['url']}")
            status_text = plain(status.group(1)) if status else ""
            if _NON_CALL.search(status_text) or _NOT_ACCEPTING.search(status_text):
                skipped["iarpa_not_open_research"] += 1
                continue
            if (not re.search(r"\bOPEN\b", status_text, re.I)
                    or not re.search(r"BROAD AGENCY ANNOUNCEMENT|research solicitation|\bBAA\b", status_text, re.I)):
                raise ValueError(f"IARPA unrecognized research solicitation status: {row['number']}")
            # Link identity must match the listing's solicitation, not an RFI
            # or proposers' day link elsewhere on the same program page.
            action = next((notice_url(href) for href, label in _LINK.findall(html)
                           if normalized_number(plain(label)) == normalized_number(row["number"]) and notice_url(href)), None)
            if not action:
                raise ValueError(f"IARPA exact solicitation action missing or unsupported: {row['number']}")
            fields = iarpa_fields(html)
            if not fields:
                raise ValueError(f"IARPA solicitation date markup missing: {row['url']}")
            # Closing Date is administrative, not evidence that submissions
            # remain possible. Only a recognized proposal deadline can admit.
            date_text = fields.get("proposal due date")
            close = parsed_date(date_text)
            opened = parsed_date(fields.get("release date"))
            if fields.get("release date") and not opened:
                raise ValueError(f"IARPA release date unparseable: {row['number']}")
            if not current(close, opened, as_of):
                skipped["iarpa_outside_submission_window"] += 1
                continue
            description = re.search(r'<meta\b[^>]*name="description"[^>]*content="([^"]*)"', html, re.I)
            description = plain(description.group(1)) if description else row["title"]
            key = ("iarpa", normalized_number(row["number"]))
            opportunity = CanonicalOpportunity(
                title=row["title"], external_id="iarpa-" + key[1],
                opportunity_number=row["number"], agency=IARPA, url=action,
                description=description, posted_date=opened, close_date=close,
                deadline_note=f"Research proposal deadline on the official IARPA program page: {row['url']}",
                extra={"deadline_page": row["url"]},
            )
            if key in opportunities and opportunities[key] != opportunity:
                raise ValueError(f"Conflicting IARPA rows for {row['number']}")
            opportunities[key] = opportunity

        self.diagnostics = {
            "darpa_individual_topics": len(rows), "iarpa_open_rows": len(iarpa_rows),
            "sponsor_counts": dict(Counter(key[0] for key in opportunities)),
            "skipped": dict(skipped), "program_date_overrides": date_overrides,
            "iarpa_explicit_empty": not iarpa_rows and "There are currently no open R&D Opportunities." in plain(payload["iarpa"]),
        }
        return list(opportunities.values())

    def collect(self):
        records = []
        for opportunity in self.parse(self.fetch()):
            record = opportunity.to_record(slug=self.slug, source=self.display_name, source_type=self.source_type)
            for deadline in record["deadlines"]:
                deadline["source_url"] = opportunity.extra["deadline_page"]
                deadline["source_field"] = "exact solicitation on official program page"
            records.append(record)
        return records


register(DarpaIarpaAdapter())
