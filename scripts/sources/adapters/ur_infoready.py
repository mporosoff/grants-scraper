"""University of Rochester internal & limited-submission opportunities (InfoReady).

Scaffold. UR posts internal and limited-submission competitions on its public
InfoReady portal: https://rochester.infoready4.com/ . Each open competition has
its own public page. There is no documented public API, so this is a scrape of
the public competition list.

To finish:
1. Fetch the public homepage/list and inspect how open competitions are listed
   (InfoReady typically renders competition cards/rows with a title link and a
   deadline). Confirm whether the list is server-rendered or loaded via an
   internal JSON endpoint the page calls (check the network tab); the JSON
   endpoint, if public, is more stable than scraping HTML.
2. Implement :meth:`parse` to yield one CanonicalOpportunity per competition,
   marking limited submissions (the base model already flags "limited
   submission" language automatically).
3. Set ``source_type = "Internal"`` (already set) and ``enabled = True``.
"""

from __future__ import annotations

from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register

LISTING_URL = "https://rochester.infoready4.com/"


class URInfoReadyAdapter(SourceAdapter):
    slug = "ur-infoready"
    display_name = "UR InfoReady (internal & limited submissions)"
    source_type = "Internal"
    enabled = False  # implement parse() and verify against the live portal first

    def fetch(self) -> str:
        return PoliteClient().get_text(LISTING_URL)

    def parse(self, payload: str) -> Iterable[CanonicalOpportunity]:
        # TODO: parse `payload` into CanonicalOpportunity objects, one per
        # open competition. Limited-submission wording in the title/description
        # is detected automatically by the canonical model.
        return []


register(URInfoReadyAdapter())
