"""Generic RSS / Atom adapter, plus a Philanthropy News Digest (Candid) config.

RSS/Atom is a stable, standard format, so this adapter is fully implemented and
testable offline via :meth:`parse_feed`. Point a subclass at a feed URL, set the
source metadata, and (optionally) override :meth:`deadline_for` to pull a
deadline out of the item text.
"""

from __future__ import annotations

from datetime import datetime
import html
import re
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from ..base import CanonicalOpportunity
from ..base import SourceAdapter
from ..http import PoliteClient
from ..registry import register

_DEADLINE_RE = re.compile(
    r"(?:deadline|due|closes?|apply by)(?:\s+date)?\s*[:\-]?\s*"
    r"([A-Z][a-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BARE_AMPERSAND_RE = re.compile(
    r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)"
)


def _strip(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return (
        re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(text))).strip()
        or None
    )


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class RSSAdapter(SourceAdapter):
    """Base class for any RSS 2.0 or Atom feed of funding opportunities."""

    feed_url: str = ""
    source_type = "Other"

    def fetch(self) -> str:
        if not self.feed_url:
            raise ValueError(f"{self.__class__.__name__}.feed_url is not set")
        return PoliteClient().get_text(self.feed_url)

    def parse(self, payload: str) -> Iterable[CanonicalOpportunity]:
        return self.parse_feed(payload)

    # -- offline-testable core --------------------------------------------
    def parse_feed(self, text: str) -> list[CanonicalOpportunity]:
        # Some official feeds contain bare ampersands in titles. Repair only
        # invalid entity starts before XML parsing; `_strip` decodes the
        # resulting entity for both normal text and HTML held in CDATA.
        safe_xml = _BARE_AMPERSAND_RE.sub("&amp;", text.strip())
        root = ET.fromstring(safe_xml)
        items = [el for el in root.iter() if _localname(el.tag) in {"item", "entry"}]
        opportunities: list[CanonicalOpportunity] = []
        for item in items:
            fields: dict[str, str] = {}
            link = None
            guid = None
            for child in item:
                name = _localname(child.tag)
                if name == "link":
                    # Atom uses an href attribute; RSS uses text.
                    link = child.attrib.get("href") or (child.text or "").strip() or link
                elif name in {"title", "description", "summary", "content",
                              "pubDate", "updated", "published", "date"}:
                    fields[name] = (child.text or "").strip()
                elif name == "guid":
                    guid = (child.text or "").strip()
            title = _strip(fields.get("title"))
            if not title:
                continue
            body = _strip(
                fields.get("description")
                or fields.get("summary")
                or fields.get("content")
            )
            posted = self._parse_pubdate(
                fields.get("pubDate") or fields.get("published")
                or fields.get("updated") or fields.get("date")
            )
            opportunities.append(
                CanonicalOpportunity(
                    title=title,
                    external_id=guid or link,
                    url=link,
                    description=body,
                    posted_date=posted,
                    close_date=self.deadline_for(title, body),
                )
            )
        return opportunities

    # -- hooks a subclass may override ------------------------------------
    def deadline_for(self, title: Optional[str], body: Optional[str]) -> Optional[str]:
        """Best-effort deadline extraction from the item text."""
        match = _DEADLINE_RE.search(f"{title or ''} {body or ''}")
        return match.group(1) if match else None

    @staticmethod
    def _parse_pubdate(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return None


class PhilanthropyNewsDigestRFP(RSSAdapter):
    """Candid's Philanthropy News Digest RFP feed -- a free aggregator that
    surfaces many foundations at once.

    NOTE: confirm the current feed URL and add a topic/eligibility filter before
    enabling, because PND is nonprofit-skewed and needs filtering down to
    academic-research RFPs. Left disabled until then.
    """

    slug = "pnd-rfp"
    display_name = "Philanthropy News Digest (Candid)"
    source_type = "Foundation"
    enabled = False
    # NOTE: as of July 2026 Candid restructured its site and a clean public RFP
    # RSS endpoint could not be confirmed (the old feed path now redirects to
    # the Candid blog). Confirm a current RFP feed/API before enabling, and add
    # a topic/eligibility filter because PND is nonprofit-skewed.
    feed_url = ""


class NIHGuideFundingOpps(RSSAdapter):
    """NIH Guide for Grants and Contracts informational-notices feed.

    NIH stopped publishing NOFOs in the Guide beginning in FY2026; Grants.gov
    is now NIH's single official source for grant and cooperative-agreement
    opportunities. Keep this adapter disabled so policy notices and RFIs are
    not presented as funding opportunities.
    """

    slug = "nih-guide"
    display_name = "NIH Guide for Grants and Contracts"
    source_type = "Federal"
    enabled = False
    feed_url = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"


class NSFFundingUpcoming(RSSAdapter):
    """NSF upcoming funding opportunities feed.

    The feed exists and is served as ``application/rss+xml`` at the URL below.
    Confirm the item structure once against the live feed before enabling
    (the generic RSS parser expects standard <item> title/link/description).
    Federal source; overlaps Grants.gov (dedup handles it); the value is NSF
    Dear Colleague Letters and notices not always in Grants.gov.
    """

    slug = "nsf-funding"
    display_name = "National Science Foundation"
    source_type = "Federal"
    enabled = True
    min_records = 3
    max_records = 250
    feed_url = "https://www.nsf.gov/rss/rss_www_funding-upcoming/rss.xml"

    def parse(self, payload: str) -> Iterable[CanonicalOpportunity]:
        opportunities = self.parse_feed(payload)
        for opportunity in opportunities:
            match = re.search(
                r"/(nsf|pd)(\d{2}-[0-9a-z]+)(?:[/?#]|$)",
                opportunity.url or "",
                re.I,
            )
            if match:
                number = match.group(2).upper()
                opportunity.opportunity_number = (
                    number if match.group(1).casefold() == "nsf"
                    else f"PD-{number}"
                )
        return opportunities


register(PhilanthropyNewsDigestRFP())
register(NIHGuideFundingOpps())
register(NSFFundingUpcoming())
