"""NYSERDA current funding opportunities (New York State energy R&D).

Scaffold. NYSERDA posts active PONs/RFPs on a single page:
https://www.nyserda.ny.gov/Funding-Opportunities/Current-Funding-Opportunities
There is no public API, so this is an HTML scrape of one small, low-volume page
-- a good low-maintenance source once the row structure is confirmed.

To finish:
1. Fetch the page once and inspect how each opportunity row is marked up
   (table rows, cards, or list items) and where the PON number, title, link,
   and close date live. Note: NY.gov pages can render server-side or via
   JavaScript; if the funding rows are not in the raw HTML, use the printable/
   list view or the New York State Contract Reporter listing instead.
2. Implement :meth:`parse` to yield one CanonicalOpportunity per row.
3. Add a health check (expect a plausible row count) and set ``enabled = True``.
"""

from __future__ import annotations

from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register

LISTING_URL = "https://www.nyserda.ny.gov/Funding-Opportunities/Current-Funding-Opportunities"


class NyserdaAdapter(SourceAdapter):
    slug = "nyserda"
    display_name = "NYSERDA"
    source_type = "State"
    enabled = False  # implement parse() and verify against the live page first

    def fetch(self) -> str:
        return PoliteClient().get_text(LISTING_URL)

    def parse(self, payload: str) -> Iterable[CanonicalOpportunity]:
        # TODO: parse `payload` (HTML) into opportunities. Example shape:
        #   yield CanonicalOpportunity(
        #       external_id="PON 4602",
        #       title="Clean Energy Fund - ...",
        #       url="https://www.nyserda.ny.gov/.../PON-4602",
        #       close_date="2026-09-15",
        #       source_type is set on the adapter, not per record.
        #   )
        return []


register(NyserdaAdapter())
