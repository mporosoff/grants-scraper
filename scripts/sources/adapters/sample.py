"""A fully-working example adapter backed by a local JSON fixture.

It requires no network, so it is ideal for demos, the ``dry-run`` command, and
tests. It shows exactly what a real adapter's :meth:`parse` should return. It
stays disabled so it never adds demo data to the production catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..registry import register

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_opportunities.json"


class SampleFixtureAdapter(SourceAdapter):
    slug = "sample"
    display_name = "Sample source (demo)"
    source_type = "Other"
    enabled = False  # demo only; never merged into the real catalog by default

    def __init__(self, fixture: Path = FIXTURE):
        super().__init__()
        self.fixture = fixture

    def fetch(self) -> list[dict]:
        return json.loads(Path(self.fixture).read_text(encoding="utf-8"))

    def parse(self, payload: list[dict]) -> Iterable[CanonicalOpportunity]:
        for row in payload:
            yield CanonicalOpportunity(
                external_id=row.get("id"),
                title=row.get("title", ""),
                url=row.get("url"),
                agency=row.get("agency"),
                description=row.get("description"),
                status=row.get("status", "posted"),
                close_date=row.get("close_date"),
                posted_date=row.get("posted_date"),
                award_floor=row.get("award_floor"),
                award_ceiling=row.get("award_ceiling"),
                eligibility_text=row.get("eligibility_text"),
                applicant_types=row.get("applicant_types", []),
                disciplines=row.get("disciplines", []),
            )


register(SampleFixtureAdapter())
