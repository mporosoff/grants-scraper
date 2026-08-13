"""Current NSF CBET cluster programs that are not reliably on Grants.gov.

NSF's 2026 CBET reorganization replaced the former core-program listings with
four broader cluster programs.  The official pages say that proposals are
submitted through Research.gov, so Grants.gov can omit a current cluster (as
it presently does for EWRE).  This adapter verifies and publishes the four
official NSF pages; normal cross-source deduplication lets Grants.gov win when
it does carry the same PD number.
"""

from __future__ import annotations

from typing import Iterable

from scripts.nsf_funding import parse_nsf_funding_page

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register


CBET_PROGRAMS = (
    {
        "title": "Chemical Process Systems (CPS)",
        "number": "PD-26-367Y",
        "url": "https://www.nsf.gov/funding/opportunities/chemical-process-systems",
    },
    {
        "title": "Engineering Biological and Biomedical Systems (EBBS)",
        "number": "PD-26-369Y",
        "url": (
            "https://www.nsf.gov/funding/opportunities/"
            "engineering-biological-biomedical-systems"
        ),
    },
    {
        "title": "Energy, Water, and Resource Engineering (EWRE)",
        "number": "PD-26-370Y",
        "url": (
            "https://www.nsf.gov/funding/opportunities/"
            "energy-water-resource-engineering"
        ),
    },
    {
        "title": "Transport Phenomena (TP)",
        "number": "PD-26-366Y",
        "url": "https://www.nsf.gov/funding/opportunities/transport-phenomena",
    },
)


class NSFCBETCorePrograms(SourceAdapter):
    slug = "nsf-cbet"
    display_name = "U.S. National Science Foundation"
    source_type = "Federal"
    enabled = True
    min_records = 1
    max_records = len(CBET_PROGRAMS)
    # If NSF archives every configured cluster, publish zero instead of
    # retaining an unsafe snapshot.
    retain_on_failure = False

    def fetch(self) -> dict[str, str]:
        client = PoliteClient(request_delay=0.25)
        return {
            program["number"]: client.get_text(program["url"])
            for program in CBET_PROGRAMS
        }

    def parse(self, payload: dict[str, str]) -> Iterable[CanonicalOpportunity]:
        by_number = {program["number"]: program for program in CBET_PROGRAMS}
        if set(payload) != set(by_number):
            raise RuntimeError("NSF CBET response set was incomplete")

        opportunities = []
        archived = []
        for number, html in payload.items():
            program = by_number[number]
            page = parse_nsf_funding_page(html, require_synopsis=False)
            if page["status"] == "archived":
                archived.append(number)
                continue
            if page["status"] != "current":
                raise RuntimeError(
                    f"NSF CBET page {number} did not contain a usable synopsis"
                )
            opportunities.append(
                CanonicalOpportunity(
                    title=program["title"],
                    external_id=number,
                    opportunity_number=number,
                    url=program["url"],
                    agency="U.S. National Science Foundation",
                    description=(
                        f"{page['text']}\nFull proposals accepted anytime."
                    ),
                    status="posted",
                    posted_date="2026-04-24",
                    deadline_note="Full proposals accepted anytime",
                    disciplines=["Engineering and Physical Sciences"],
                    funding_instruments=["Grant"],
                )
            )

        self.diagnostics = {
            "configured_programs": len(CBET_PROGRAMS),
            "current_programs": len(opportunities),
            "archived_program_numbers": archived,
            "lifecycle_source": "Official NSF funding pages",
        }
        return opportunities


register(NSFCBETCorePrograms())
