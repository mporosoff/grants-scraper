"""NYSERDA current funding opportunities (New York State energy R&D).

Verified live JSON API. The Current Funding Opportunities page loads
solicitations from NYSERDA's ``fundingopportunities`` endpoint (a plain GET
returning JSON). Shape::

    {"FundingOpportunities": [                       # sections
       {"SectionTitle": ...,
        "FundingOpportunities": [                     # solicitations
            {"SolicitationName", "SolicitationNumber", "ShortDescription",
            "SolicitationRounds",   # structured round status/date/time
            "DueDateString",        # HTML fallback with M/D/YYYY round dates
            "RevisedDate", "DetailPageLink", "SolicitationLinkPDF", ...}, ...]}, ...]}

Energy-focused, low volume, served as plain JSON. The displayed close date is
the next open application round, while later future rounds and concept-paper
dates are retained as structured deadlines. ``DueDateString`` is used only when
the structured round list is absent. Genuinely past solicitations are dropped
by the merge's currentness gate.
"""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Iterable

from ..base import CanonicalOpportunity, SourceAdapter
from ..http import PoliteClient
from ..registry import register

LISTING_URL = "https://www.nyserda.ny.gov/Funding-Opportunities/Current-Funding-Opportunities"
NYSERDA_API = (
    "https://www.nyserda.ny.gov/rapi/fundingopportunitiesapi/getfundingopportunities"
    "?dataSourceId=a8166835-baba-4c2b-843d-c55e4583f19a"
)

_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b", re.IGNORECASE)


def _get(item: dict, *keys):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _dates_in(text):
    """Return valid M/D/YYYY dates from text, preserving source order."""
    dates = []
    for month, day, year in _DATE_RE.findall(str(text or "")):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return dates


def _time_in(text):
    match = _TIME_RE.search(str(text or ""))
    return re.sub(r"\s+", " ", match.group(1)).upper() if match else None


def _next_round_deadlines(item: dict, as_of: date) -> tuple[str | None, list[dict], str | None]:
    """Return next application date, later structured deadlines, and a note."""
    application_dates: list[dict] = []
    concept_dates: list[dict] = []
    rounds = item.get("SolicitationRounds")
    if isinstance(rounds, list):
        for round_item in rounds:
            if not isinstance(round_item, dict):
                continue
            status = str(round_item.get("Status") or "").casefold()
            if status in {"closed", "cancelled", "canceled", "withdrawn"}:
                continue
            round_name = str(round_item.get("Round") or "").strip()
            note = f"Round {round_name}" if round_name else None
            due_value = round_item.get("DueDate")
            for parsed in _dates_in(due_value):
                application_dates.append({
                    "date": parsed,
                    "time": _time_in(due_value),
                    "note": note,
                })
            concept_value = round_item.get("ConceptPaperDueDate")
            for parsed in _dates_in(concept_value):
                concept_dates.append({
                    "date": parsed,
                    "time": _time_in(concept_value),
                    "note": note,
                })

    if not application_dates:
        application_dates = [
            {"date": parsed, "time": None, "note": None}
            for parsed in _dates_in(item.get("DueDateString"))
        ]

    # De-duplicate repeated dates such as a summary date plus an identical round.
    unique_applications = {}
    for entry in application_dates:
        unique_applications.setdefault(entry["date"], entry)
    application_dates = [
        unique_applications[key] for key in sorted(unique_applications)
    ]

    future_applications = [
        entry for entry in application_dates if entry["date"] >= as_of
    ]
    primary = (
        future_applications[0]["date"]
        if future_applications
        else application_dates[-1]["date"] if application_dates else None
    )

    additional: list[dict] = []
    for entry in future_applications[1:]:
        additional.append({
            "kind": "application",
            "date": entry["date"].isoformat(),
            "time": entry["time"],
            "timezone": "ET" if entry["time"] else None,
            "note": entry["note"],
        })
    seen_concepts = set()
    for entry in sorted(concept_dates, key=lambda value: value["date"]):
        if entry["date"] < as_of or entry["date"] in seen_concepts:
            continue
        seen_concepts.add(entry["date"])
        additional.append({
            "kind": "concept_paper",
            "date": entry["date"].isoformat(),
            "time": entry["time"],
            "timezone": "ET" if entry["time"] else None,
            "note": entry["note"],
        })

    note = None
    if len(future_applications) > 1:
        note = (
            f"Next of {len(future_applications)} future NYSERDA "
            "application rounds; later rounds are listed in the details."
        )
    return primary.isoformat() if primary else None, additional, note


def _iter_solicitations(payload) -> Iterable[dict]:
    sections = payload.get("FundingOpportunities") if isinstance(payload, dict) else None
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, dict):
            continue
        solicitations = section.get("FundingOpportunities")
        if isinstance(solicitations, list):
            for solicitation in solicitations:
                if isinstance(solicitation, dict):
                    yield solicitation
        elif _get(section, "SolicitationName", "SolicitationTitle"):
            yield section


class NyserdaAdapter(SourceAdapter):
    slug = "nyserda"
    display_name = "NYSERDA"
    source_type = "State"
    enabled = True
    min_records = 1
    max_records = 500

    def fetch(self):
        return json.loads(PoliteClient().get_text(NYSERDA_API))

    def parse(self, payload) -> Iterable[CanonicalOpportunity]:
        return self.parse_payload(payload)

    def parse_payload(self, payload, as_of: date | None = None) -> list[CanonicalOpportunity]:
        if as_of is None:
            as_of = date.today()
        opportunities: list[CanonicalOpportunity] = []
        for item in _iter_solicitations(payload):
            title = _get(item, "SolicitationName", "SolicitationTitle")
            if not title:
                continue
            number = str(_get(item, "SolicitationNumber", "SolicitationID") or title)
            close_date, additional_deadlines, deadline_note = (
                _next_round_deadlines(item, as_of)
            )
            opportunities.append(CanonicalOpportunity(
                external_id=number,
                opportunity_number=number,
                title=str(title),
                url=str(_get(item, "DetailPageLink", "SalesforceLink") or LISTING_URL),
                description=_get(item, "ShortDescription"),
                close_date=close_date,
                deadline_note=deadline_note,
                posted_date=_get(item, "RevisedDate"),
                primary_document_url=_get(item, "SolicitationLinkPDF"),
                additional_deadlines=additional_deadlines,
            ))
        return opportunities


register(NyserdaAdapter())
