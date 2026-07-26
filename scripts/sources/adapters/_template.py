"""COPY ME to add a new funding source.

Steps to add a source:
  1. Copy this file to ``scripts/sources/adapters/<yoursource>.py``.
  2. Fill in the class attributes and the two methods (`fetch`, `parse`).
  3. Add ``from . import <yoursource>`` to ``adapters/__init__.py``.
  4. Test it in isolation:  ``python -m scripts.sources dry-run --adapter <slug> --include-disabled``
  5. When the output looks right, set ``enabled = True`` and add a health check.

You only fill in the fields you actually have. The canonical model derives
topics, LOI/limited-submission/early-career signals, deadlines, and all the
other catalog fields for you, matching Grants.gov records exactly.

This template is intentionally NOT registered (leading underscore, no
`register(...)` call), so it never runs.
"""

from __future__ import annotations

from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
# from ..http import PoliteClient        # uncomment if you need the network
# from ..registry import register        # uncomment in your real adapter


class TemplateAdapter(SourceAdapter):
    slug = "template"                     # short id, used to namespace records
    display_name = "Template source"      # shown in the UI as the source
    source_type = "Other"                 # "State" / "Foundation" / "Internal" / ...
    enabled = False                       # flip to True only after verifying

    def fetch(self):
        """Return the raw payload (HTML text, feed text, or parsed JSON)."""
        # return PoliteClient().get_text("https://example.org/opportunities")
        raise NotImplementedError

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        """Turn the payload into CanonicalOpportunity objects."""
        # for row in payload:
        #     yield CanonicalOpportunity(
        #         external_id=row["id"],
        #         title=row["title"],
        #         url=row["link"],
        #         description=row.get("summary"),
        #         close_date=row.get("deadline"),      # ISO or US date string
        #         award_ceiling=row.get("max_award"),
        #     )
        raise NotImplementedError


# In your real adapter, register a single instance:
# register(TemplateAdapter())
