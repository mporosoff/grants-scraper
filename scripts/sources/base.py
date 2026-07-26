"""Canonical opportunity model and the SourceAdapter base class.

An adapter's only job is to turn a source (web page, RSS feed, API) into a list
of :class:`CanonicalOpportunity` objects. ``to_record`` then expands each one
into the *exact* record shape that ``scripts/build_catalog.py`` produces, so
external records are indistinguishable from Grants.gov records to the browser,
the BM25 index, and the facet counter.

You never have to hand-build the 50+ record fields: fill in the handful of
fields you actually have, and the model derives topics, disciplines-agnostic
signals (LOI/limited-submission/early-career), deadlines, and safe defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import re
from typing import Any, Iterable, Optional

# Reuse Grants.gov's own normalization so external records get identical
# topic tagging, signal detection, and money/text cleaning. Importing this
# module has no side effects (its CLI is guarded by ``if __name__``).
from scripts.build_catalog import (
    EARLY_CAREER_RE,
    LIMITED_SUBMISSION_RE,
    PRELIMINARY_RE,
    ROLLING_RE,
    clean_text,
    numeric,
    safe_http_url,
    topic_areas,
)

VALID_STATUSES = {"posted", "forecasted"}

# US-style and ISO date formats seen on foundation / agency pages.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
)


def to_iso_date(value: Any) -> Optional[str]:
    """Coerce a date/datetime/string into an ISO ``YYYY-MM-DD`` string or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    # ISO first (tolerate a trailing time or Z).
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    cleaned = re.sub(r"\s+", " ", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")
    return slug or "source"


@dataclass
class CanonicalOpportunity:
    """A single opportunity in a source-neutral form.

    Only ``title`` is strictly required. Provide ``external_id`` when the source
    has a stable identifier (opportunity/PON/RFP number); otherwise a stable id
    is derived from the title + url so re-runs stay idempotent.
    """

    title: str
    external_id: Optional[str] = None
    opportunity_number: Optional[str] = None
    url: Optional[str] = None           # canonical/detail link to the notice
    agency: Optional[str] = None        # sub-funder; defaults to the source name
    description: Optional[str] = None
    status: str = "posted"              # "posted" or "forecasted"
    close_date: Any = None              # ISO string, date, datetime, or US date
    posted_date: Any = None
    deadline_note: Optional[str] = None
    award_floor: Any = None
    award_ceiling: Any = None
    total_program_funding: Any = None
    expected_number_of_awards: Any = None
    cost_share_required: Optional[bool] = None
    eligibility_text: Optional[str] = None
    applicant_types: list = field(default_factory=list)
    disciplines: list = field(default_factory=list)
    topic_areas: list = field(default_factory=list)      # derived if left empty
    funding_instruments: list = field(default_factory=list)
    funding_categories: list = field(default_factory=list)
    primary_document_url: Optional[str] = None
    primary_document_name: Optional[str] = None
    extra: dict = field(default_factory=dict)            # escape hatch, never indexed

    def stable_external_id(self) -> str:
        if self.external_id:
            return re.sub(r"\s+", "", str(self.external_id))
        seed = f"{(self.title or '').strip()}|{(self.url or '').strip()}".casefold()
        return "auto-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    def to_record(self, *, slug: str, source: str, source_type: str) -> dict:
        """Expand into the full Grants.gov-compatible catalog record dict."""
        title = clean_text(self.title)
        if not title:
            raise ValueError("CanonicalOpportunity.title is required")
        status = self.status if self.status in VALID_STATUSES else "posted"

        description = clean_text(self.description)
        eligibility_text = clean_text(self.eligibility_text)
        deadline_note = clean_text(self.deadline_note)
        url = safe_http_url(self.url)
        primary_document_url = safe_http_url(self.primary_document_url)

        opportunity_id = f"{slug}:{self.stable_external_id()}"
        close_date = to_iso_date(self.close_date)
        posted_date = to_iso_date(self.posted_date)

        text_blob = " ".join(
            part
            for part in (title, description, eligibility_text, deadline_note)
            if part
        )
        topics = list(self.topic_areas) or topic_areas(
            title, description, self.funding_categories
        )
        rolling = bool(ROLLING_RE.search(text_blob))
        preliminary = PRELIMINARY_RE.search(text_blob)
        early_career = EARLY_CAREER_RE.search(text_blob)

        deadlines = []
        if close_date:
            deadlines.append(
                {
                    "kind": (
                        "estimated_application"
                        if status == "forecasted"
                        else "application"
                    ),
                    "date": close_date,
                    "time": None,
                    "timezone": None,
                    "note": deadline_note,
                    "estimated": status == "forecasted",
                    "source": source,
                    "source_url": url or primary_document_url,
                    "source_field": "source listing",
                    "confidence": "source_listed",
                }
            )

        record = {
            # --- identity & provenance ---
            "opportunity_id": opportunity_id,
            "opportunity_number": clean_text(self.opportunity_number),
            "title": title,
            "agency": clean_text(self.agency) or source,
            "agency_code": None,
            "status": status,
            "source": source,
            "source_type": source_type,
            # --- links / one-click action ---
            "detail_page": url or primary_document_url,
            "funding_opportunity_url": url,
            "primary_document_url": primary_document_url,
            "primary_document_name": clean_text(self.primary_document_name),
            "primary_document_source": (
                f"{source} listing" if primary_document_url else None
            ),
            "primary_document_confidence": (
                "source_listed" if primary_document_url else None
            ),
            "detail_enrichment_status": "not_applicable",
            # --- dates ---
            "posted_date": posted_date,
            "close_date": close_date,
            "close_date_note": deadline_note,
            "deadlines": deadlines,
            "deadline_source": f"{source} listing",
            "archive_date": None,
            "status_verification_required": (not close_date and not rolling),
            "last_updated": posted_date,
            "estimated_award_date": None,
            "estimated_project_start": None,
            "fiscal_year": None,
            "version": None,
            "rolling": rolling,
            "opportunity_category": None,
            # --- facets ---
            "funding_category_codes": [],
            "funding_categories": list(self.funding_categories),
            "funding_instrument_codes": [],
            "funding_instruments": list(self.funding_instruments),
            "eligibility_codes": [],
            "applicant_types": list(self.applicant_types),
            "eligibility_text": eligibility_text,
            "disciplines": list(self.disciplines),
            "topic_areas": topics,
            "aln": [],
            # --- funding (award floor/ceiling only; never conflate totals) ---
            "award_floor": numeric(self.award_floor),
            "award_ceiling": numeric(self.award_ceiling),
            "total_program_funding": numeric(self.total_program_funding),
            "expected_number_of_awards": numeric(self.expected_number_of_awards),
            "award_source": f"{source} listing",
            "cost_share_required": self.cost_share_required,
            # --- deterministic signals ---
            "has_preliminary_stage": bool(preliminary),
            "preliminary_stage_type": preliminary.group(1) if preliminary else None,
            "limited_submission": bool(LIMITED_SUBMISSION_RE.search(text_blob)),
            "career_stage_signal": early_career.group(1) if early_career else None,
            "description": (description or "")[:12000] or None,
            # --- enrichment/evidence fields (defaulted; external sources do not
            #     pass through the Grants.gov detail or document-evidence steps) ---
            "detail_enriched_at": None,
            "api_revision": None,
            "api_version": None,
            "api_last_updated": None,
            "attachment_count": 1 if primary_document_url else 0,
            "document_urls": [],
            "history": None,
            "actionability_status": (
                "current_by_source_listed_date" if close_date else "verify_status"
            ),
            "document_evidence_status": "not_applicable",
            "document_evidence": None,
            "document_search_text": None,
        }
        return record


class SourceAdapter:
    """Base class for a single funding source.

    Subclass and implement :meth:`fetch` (return raw text/bytes/objects) and
    :meth:`parse` (turn the raw payload into ``CanonicalOpportunity`` objects).
    Set ``enabled = True`` only once the adapter is verified against the live
    source.
    """

    #: short machine slug, used to namespace ids, e.g. ``"nyserda"``.
    slug: str = ""
    #: human-readable source name shown in the UI, e.g. ``"NYSERDA"``.
    display_name: str = ""
    #: coarse provenance bucket, e.g. ``"State"``, ``"Foundation"``, ``"Internal"``.
    source_type: str = "Other"
    #: gate. Adapters stay off until implemented and verified.
    enabled: bool = False
    #: source health bounds. A refresh returning a count outside these is
    #: treated as unhealthy, so the merge keeps the last-known-good snapshot.
    min_records: int = 1
    max_records: int = 2000

    def __init__(self) -> None:
        if not self.slug:
            self.slug = _slugify(self.display_name or self.__class__.__name__)
        if not self.display_name:
            self.display_name = self.slug

    # --- implement these two in a subclass -------------------------------
    def fetch(self) -> Any:
        """Return the raw payload for :meth:`parse` (HTML, feed text, JSON...)."""
        raise NotImplementedError

    def parse(self, payload: Any) -> Iterable[CanonicalOpportunity]:
        """Turn a raw payload into CanonicalOpportunity objects."""
        raise NotImplementedError

    # --- orchestration (usually no need to override) ---------------------
    def collect(self) -> list[dict]:
        """Fetch, parse, and expand into catalog records. Errors propagate to
        the registry, which isolates them per-adapter."""
        payload = self.fetch()
        records: list[dict] = []
        for opportunity in self.parse(payload):
            records.append(
                opportunity.to_record(
                    slug=self.slug,
                    source=self.display_name,
                    source_type=self.source_type,
                )
            )
        return records
