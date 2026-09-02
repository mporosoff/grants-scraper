"""Incrementally enrich the public catalog with Grants.gov detail evidence.

The daily XML extract remains the complete catalog source. This module uses the
public ``fetchOpportunity`` endpoint only for records that are new or changed,
then caches a compact set of official detail fields:

- likely primary NOFO/FOA attachment metadata;
- agency notice and document links;
- deadline notes, clock time, timezone, and preliminary-stage signals;
- award fields that are missing from the XML extract; and
- authoritative NSF page lifecycle, including explicit archived status;
- authoritative NSF synopsis text when Grants.gov has dropped word spacing;
- revision/history counters used to surface verification warnings.

No API key is required. Machine-selected documents and prose-extracted
deadlines remain visibly marked for verification.
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse

import requests

from scripts.build_catalog import (
    CATALOG_GLOBAL,
    MAX_REAL_CLOSE_DATE_DAYS,
    ROLLING_RE,
    USER_AGENT,
    build_search_index,
    clean_text,
    facet_counts,
    normalize_record_facets,
    iso_utc,
    numeric,
    safe_http_url,
    write_catalog,
)
from scripts.pull_grants import (
    collect_attachments,
    fetch_detail,
    normalize,
)
from scripts.nsf_funding import (
    NSF_FUNDING_PAGE_PARSER_VERSION,
    extract_nsf_synopsis as parse_nsf_synopsis,
    parse_nsf_funding_page,
)


CACHE_SCHEMA_VERSION = 2
CONTACT_SCHEMA_VERSION = 1
AGENCY_FUNDING_PAGE_RECHECK_DAYS = 14
DEFAULT_CATALOG = Path("data/opportunities.js")
DEFAULT_CACHE = Path("data/opportunity_enrichment.json")
API_NOTICE = (
    "This product uses the Grants.gov API but is not endorsed or certified "
    "by the U.S. Department of Health and Human Services."
)

POSITIVE_DOCUMENT_RE = re.compile(
    r"\b(nofo|foa|rfa|baa|funding opportunity announcement|"
    r"full announcement|full solicitation|solicitation)\b",
    re.I,
)
SUPPLEMENTAL_DOCUMENT_RE = re.compile(
    r"\b(faq|frequently asked|appendix|addendum|sample|template|webinar|"
    r"questions?|special notice|topic list|budget worksheet|cover sheet|"
    r"instructions? for (?:applicants?|submission))\b",
    re.I,
)
REVISED_DOCUMENT_RE = re.compile(
    r"\b(revised|updated|final|amended)\s+(?:nofo|foa|rfa|baa|"
    r"funding opportunity announcement|solicitation)\b",
    re.I,
)
DRAFT_DOCUMENT_RE = re.compile(r"\bdraft\b", re.I)
FULL_ANNOUNCEMENT_RE = re.compile(
    r"\b(full announcement|full solicitation|current nofo|current foa)\b",
    re.I,
)
PRELIMINARY_KIND_RE = re.compile(
    r"\b(concept\s+paper|pre[\s-]?proposal|pre[\s-]?application|"
    r"preliminary\s+proposal|letter\s+of\s+intent|loi|white\s+paper)\b",
    re.I,
)
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
DESCRIPTION_SPACING_PATTERNS = (
    re.compile(r"[a-z][A-Z][a-z]"),
    re.compile(r"[.!?][A-Z][a-z]"),
    re.compile(r";[A-Za-z]"),
    re.compile(r"[a-z]\)[A-Za-z]"),
    re.compile(r"[a-z]\([A-Z]{2,}\)"),
)
def utc_now():
    return datetime.now(timezone.utc)


def parse_now(value):
    """Parse an explicit clock override for deterministic offline builds."""
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--now must be an ISO 8601 timestamp with a timezone"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "--now must be an ISO 8601 timestamp with a timezone"
        )
    return parsed.astimezone(timezone.utc)


def read_catalog(path):
    text = Path(path).read_text(encoding="utf-8")
    prefix = f"globalThis.{CATALOG_GLOBAL}="
    if prefix not in text:
        raise RuntimeError(f"{path} is not a {CATALOG_GLOBAL} asset.")
    payload = text.split(prefix, 1)[1].strip().removesuffix(";")
    catalog = json.loads(payload)
    if len(catalog.get("opportunities") or []) != catalog.get("record_count"):
        raise RuntimeError(f"{path} failed its record-count invariant.")
    return catalog


def empty_cache():
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "generated_at": None,
        "records": {},
    }


def read_cache(path):
    path = Path(path)
    if not path.exists():
        return empty_cache()
    cache = json.loads(path.read_text(encoding="utf-8"))
    if cache.get("schema_version") != CACHE_SCHEMA_VERSION:
        return empty_cache()
    if not isinstance(cache.get("records"), dict):
        raise RuntimeError(f"{path} does not contain a record map.")
    return cache


def write_cache(cache, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(
                cache,
                output,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            output.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def record_signature(record):
    fields = (
        record.get("status"),
        record.get("last_updated"),
        record.get("version"),
        record.get("close_date"),
        record.get("archive_date"),
    )
    return "|".join(str(value or "") for value in fields)


def parse_api_date(value):
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date().isoformat()
    except ValueError:
        pass
    # Grants.gov detail timestamps usually end in a US timezone abbreviation.
    text = re.sub(r"\s+(?:E[SD]T|C[SD]T|M[SD]T|P[SD]T)$", "", text)
    for pattern in (
        "%b %d, %Y %I:%M:%S %p",
        "%B %d, %Y %I:%M:%S %p",
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
    ):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_text_date(value):
    match = DATE_TEXT_RE.search(value or "")
    if not match:
        return None
    text = match.group(1).replace(",", "")
    for pattern in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y", "%B %d %Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def preliminary_kind(value):
    match = PRELIMINARY_KIND_RE.search(value or "")
    if not match:
        return "preliminary"
    text = match.group(1).casefold().replace("-", " ")
    if text in {"letter of intent", "loi"}:
        return "letter_of_intent"
    if "concept" in text:
        return "concept_paper"
    if "white" in text:
        return "white_paper"
    if "application" in text:
        return "preapplication"
    return "preproposal"


def description_spacing_issue_count(value):
    text = str(value or "")
    return sum(
        len(pattern.findall(text))
        for pattern in DESCRIPTION_SPACING_PATTERNS
    )


def is_nsf_url(value):
    url = safe_http_url(value)
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").casefold()
    return hostname == "nsf.gov" or hostname.endswith(".nsf.gov")


def extract_nsf_synopsis(html):
    return parse_nsf_synopsis(html)


def fetch_nsf_funding_page(url):
    if not is_nsf_url(url):
        raise RuntimeError("agency funding-page URL is not an NSF page")
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=(20, 60),
    )
    response.raise_for_status()
    if not is_nsf_url(response.url):
        raise RuntimeError("NSF funding-page URL redirected outside nsf.gov")
    content_type = response.headers.get("content-type", "").casefold()
    if "html" not in content_type:
        raise RuntimeError("official NSF funding-page source is not HTML")
    if len(response.content) > 5_000_000:
        raise RuntimeError("official NSF funding page is unexpectedly large")
    return {
        **parse_nsf_funding_page(response.text, require_synopsis=False),
        "source_url": response.url,
    }


# Compatibility alias for integrations that imported the former helper.
fetch_nsf_synopsis = fetch_nsf_funding_page


def agency_funding_page_due(record, detail_entry, as_of):
    """Return whether an undated NSF program needs an official status check."""
    if not detail_entry:
        return False
    agency_url = (
        detail_entry.get("funding_opportunity_url")
        or record.get("funding_opportunity_url")
    )
    if not is_nsf_url(agency_url):
        return False
    is_nsf_record = (
        str(record.get("agency_code") or "").casefold().startswith("nsf")
        or "national science foundation"
        in str(record.get("agency") or "").casefold()
    )
    if not is_nsf_record:
        return False
    last_error = detail_entry.get("agency_funding_page_error") or {}
    error_checked_at = parse_api_date(last_error.get("checked_at"))
    if (
        last_error.get("parser_version") == NSF_FUNDING_PAGE_PARSER_VERSION
        and error_checked_at
        and (as_of - date.fromisoformat(error_checked_at)).days
        < AGENCY_FUNDING_PAGE_RECHECK_DAYS
    ):
        return False
    page = detail_entry.get("agency_funding_page") or {}
    if page.get("parser_version") != NSF_FUNDING_PAGE_PARSER_VERSION:
        return True
    checked_at = parse_api_date(page.get("fetched_at"))
    if not checked_at:
        return True
    return (as_of - date.fromisoformat(checked_at)).days >= (
        AGENCY_FUNDING_PAGE_RECHECK_DAYS
    )


def attachment_text(attachment):
    return " ".join(
        str(attachment.get(field) or "")
        for field in (
            "file_name",
            "description",
            "folder_name",
            "folder_type",
        )
    )


def searchable_document_text(value):
    return re.sub(r"[_/\\-]+", " ", str(value or ""))


def attachment_content_text(attachment):
    return searchable_document_text(" ".join(
        str(attachment.get(field) or "")
        for field in ("file_name", "description")
    ))


def attachment_folder_text(attachment):
    return searchable_document_text(" ".join(
        str(attachment.get(field) or "")
        for field in ("folder_name", "folder_type")
    ))


def attachment_is_pdf(attachment):
    return (
        str(attachment.get("file_name") or "").casefold().endswith(".pdf")
        or attachment.get("mime_type") == "application/pdf"
    )


def attachment_date_rank(attachment):
    value = parse_api_date(attachment.get("created_date"))
    return value or ""


def select_primary_document(attachments, document_urls=None):
    """Select only a document with defensible primary-FOA evidence.

    A wrong one-click link is worse than a clearly labelled Grants.gov record
    fallback. Explicit NOFO/FOA language earns high confidence. A lone PDF in a
    full-announcement folder earns medium confidence. Everything else remains
    unresolved for human verification.
    """

    explicit_candidates = []
    folder_candidates = []
    for attachment in attachments or []:
        content_text = attachment_content_text(attachment)
        folder_text = attachment_folder_text(attachment)
        all_text = f"{content_text} {folder_text}"
        if not attachment_is_pdf(attachment):
            continue
        supplemental = bool(SUPPLEMENTAL_DOCUMENT_RE.search(all_text))
        explicit = bool(POSITIVE_DOCUMENT_RE.search(content_text))
        full_folder = bool(FULL_ANNOUNCEMENT_RE.search(folder_text))
        if supplemental:
            continue
        if explicit:
            score = (
                1 if REVISED_DOCUMENT_RE.search(content_text) else 0,
                0 if DRAFT_DOCUMENT_RE.search(content_text) else 1,
                1 if full_folder else 0,
                attachment_date_rank(attachment),
            )
            explicit_candidates.append((score, attachment))
        elif full_folder:
            folder_candidates.append(attachment)

    if explicit_candidates:
        _, selected = max(explicit_candidates, key=lambda item: item[0])
        confidence = (
            "medium"
            if DRAFT_DOCUMENT_RE.search(
                attachment_content_text(selected)
            )
            else "high"
        )
        return {
            "url": safe_http_url(selected.get("download_url")),
            "name": clean_text(selected.get("file_name")),
            "source": "Grants.gov attachment",
            "confidence": confidence,
        }
    if len(folder_candidates) == 1:
        selected = folder_candidates[0]
        return {
            "url": safe_http_url(selected.get("download_url")),
            "name": clean_text(selected.get("file_name")),
            "source": "Grants.gov attachment",
            "confidence": "medium",
        }

    document_candidates = [
        safe_http_url(
            item.get("url")
            if isinstance(item, dict)
            else item
        )
        for item in (document_urls or [])
    ]
    document_candidates = [
        value
        for value in document_candidates
        if value and re.search(r"\.pdf(?:[?#]|$)", value, re.I)
    ]
    if len(document_candidates) == 1:
        return {
            "url": document_candidates[0],
            "name": None,
            "source": "Grants.gov document URL",
            "confidence": "medium",
        }
    return None


def compact_detail(record, detail, fetched_at):
    stub = {
        "id": record.get("opportunity_id"),
        "number": record.get("opportunity_number"),
        "title": record.get("title"),
        "agency": record.get("agency"),
        "agencyCode": record.get("agency_code"),
        "oppStatus": record.get("status"),
        "docType": (
            "forecast"
            if record.get("status") == "forecasted"
            else "synopsis"
        ),
        "closeDate": record.get("close_date"),
    }
    normalized = normalize(stub, detail)
    attachments = collect_attachments(detail)
    primary = select_primary_document(
        attachments,
        normalized.get("document_urls"),
    )
    preliminary_text = clean_text(
        normalized.get("preliminary_deadline_text")
    )
    preliminary = None
    if normalized.get("has_preliminary_stage"):
        preliminary = {
            "kind": preliminary_kind(
                preliminary_text
                or normalized.get("preliminary_stage_type")
            ),
            "date": parse_text_date(preliminary_text),
            "text": preliminary_text,
            "required": bool(normalized.get("preliminary_required")),
            "confidence": "machine_extracted_needs_verification",
        }

    synopsis = detail.get("synopsis") or {}
    forecast = detail.get("forecast") or {}
    source_record = synopsis or forecast
    document_urls = [
        value
        for value in (
            safe_http_url(
                item.get("url")
                if isinstance(item, dict)
                else item
            )
            for item in (normalized.get("document_urls") or [])
        )
        if value
    ][:12]

    return {
        "source_signature": record_signature(record),
        "fetched_at": iso_utc(fetched_at),
        "api_revision": detail.get("revision"),
        "api_version": str(normalized.get("version") or "") or None,
        "api_last_updated": parse_api_date(
            normalized.get("last_updated")
        ),
        "deadline": {
            "date": parse_api_date(normalized.get("close_date")),
            "note": clean_text(normalized.get("close_date_note")),
            "time": clean_text(normalized.get("deadline_time")),
            "timezone": clean_text(normalized.get("deadline_timezone")),
        },
        "rolling": bool(normalized.get("rolling")),
        "preliminary_deadline": preliminary,
        "award": {
            "floor": numeric(normalized.get("award_floor")),
            "ceiling": numeric(normalized.get("award_ceiling")),
            "program_total": numeric(
                normalized.get("total_program_funding")
            ),
            "expected_awards": numeric(
                normalized.get("expected_number_of_awards")
            ),
        },
        "funding_opportunity_url": safe_http_url(
            normalized.get("funding_opportunity_url")
        ),
        "primary_document": primary,
        "document_urls": document_urls,
        "attachment_count": len(attachments),
        "history": {
            "synopsis_count": detail.get("synopsisHistCount") or 0,
            "forecast_count": detail.get("forecastHistCount") or 0,
            "modified_field_count": len(
                detail.get("synopsisModifiedFields")
                or detail.get("forecastModifiedFields")
                or []
            ),
            "change_comment_count": len(
                detail.get("synAttChangeComments") or []
            ),
        },
        "api_notice": API_NOTICE,
        "source_record_version": source_record.get("version"),
        "contact_version": CONTACT_SCHEMA_VERSION,
        "contacts": [
            {
                "name": clean_text(contact.get("name")),
                "email": clean_text(contact.get("email")),
                "phone": clean_text(contact.get("phone")),
                "role": clean_text(contact.get("role")),
                "source_url": safe_http_url(contact.get("source_url"))
                or record.get("detail_page"),
            }
            for contact in (normalized.get("contacts") or [])[:12]
            if isinstance(contact, dict)
            and any(
                contact.get(field)
                for field in ("name", "email", "phone")
            )
        ],
    }


def field_conflict(existing, enriched):
    return (
        existing not in (None, "")
        and enriched not in (None, "")
        and existing != enriched
    )


def future_sentinel_date(value, as_of):
    """Return whether a structured date is an open-ended lifecycle sentinel."""
    parsed = parse_api_date(value)
    if not parsed:
        return False
    return (date.fromisoformat(parsed) - as_of).days > MAX_REAL_CLOSE_DATE_DAYS


def suppress_future_sentinel_deadlines(record, as_of):
    """Remove Grants.gov 2076/2099 placeholders before any detail merge."""
    if future_sentinel_date(record.get("close_date"), as_of):
        record["close_date"] = None
    record["deadlines"] = [
        deadline
        for deadline in (record.get("deadlines") or [])
        if not future_sentinel_date(deadline.get("date"), as_of)
    ]
    note = clean_text(record.get("close_date_note"))
    if note and ROLLING_RE.search(note):
        record["rolling"] = True
        record["status_verification_required"] = False
    return record


def merge_detail(record, detail_entry, as_of):
    output = suppress_future_sentinel_deadlines(deepcopy(record), as_of)
    output.setdefault("contacts", [])
    if not detail_entry:
        output["detail_enrichment_status"] = "pending"
        output.setdefault("award_source", "Grants.gov XML extract")
        return output

    output["detail_enrichment_status"] = "current"
    output["detail_enriched_at"] = detail_entry.get("fetched_at")
    output["api_revision"] = detail_entry.get("api_revision")
    output["api_version"] = detail_entry.get("api_version")
    output["api_last_updated"] = detail_entry.get("api_last_updated")
    output["attachment_count"] = detail_entry.get("attachment_count") or 0
    output["document_urls"] = detail_entry.get("document_urls") or []
    output["history"] = detail_entry.get("history") or {}
    output["contacts"] = deepcopy(detail_entry.get("contacts") or [])

    agency_url = safe_http_url(
        detail_entry.get("funding_opportunity_url")
        or output.get("funding_opportunity_url")
    )
    output["funding_opportunity_url"] = agency_url
    agency_page = detail_entry.get("agency_funding_page") or {}
    agency_synopsis = detail_entry.get("agency_synopsis") or {}
    agency_description_source = agency_page or agency_synopsis
    agency_description = clean_text(agency_description_source.get("text"))
    if (
        description_spacing_issue_count(output.get("description"))
        and agency_description
        and is_nsf_url(agency_description_source.get("source_url"))
    ):
        output["description"] = agency_description[:12000]
        output["description_source"] = "Official NSF funding page"
        output["description_source_url"] = agency_description_source[
            "source_url"
        ]
        output["description_enriched_at"] = agency_description_source.get(
            "fetched_at"
        )

    primary = detail_entry.get("primary_document") or {}
    if primary.get("url"):
        output["primary_document_url"] = primary["url"]
        output["primary_document_name"] = primary.get("name")
        output["primary_document_source"] = primary.get("source")
        output["primary_document_confidence"] = primary.get("confidence")

    api_award = detail_entry.get("award") or {}
    award_fields = {
        "award_floor": api_award.get("floor"),
        "award_ceiling": api_award.get("ceiling"),
        "total_program_funding": api_award.get("program_total"),
        "expected_number_of_awards": api_award.get("expected_awards"),
    }
    conflicts = {}
    filled_from_api = []
    for field, api_value in award_fields.items():
        current = output.get(field)
        if field_conflict(current, api_value):
            conflicts[field] = {
                "xml": current,
                "api": api_value,
            }
        elif current in (None, "") and api_value not in (None, ""):
            output[field] = api_value
            filled_from_api.append(field)
    output["award_source"] = (
        "Grants.gov XML extract + detail API"
        if filled_from_api
        else "Grants.gov XML extract"
    )
    if conflicts:
        output["award_conflicts"] = conflicts

    api_deadline = detail_entry.get("deadline") or {}
    api_date = api_deadline.get("date")
    if future_sentinel_date(api_date, as_of):
        api_date = None
    if detail_entry.get("rolling") or ROLLING_RE.search(
        api_deadline.get("note") or ""
    ):
        output["rolling"] = True
        output["status_verification_required"] = False
    if field_conflict(output.get("close_date"), api_date):
        output["deadline_conflict"] = {
            "xml": output.get("close_date"),
            "api": api_date,
        }
        output["status_verification_required"] = True

    deadlines = deepcopy(output.get("deadlines") or [])
    if deadlines:
        primary_deadline = deadlines[0]
        if not api_date or api_date == primary_deadline.get("date"):
            if api_deadline.get("time"):
                primary_deadline["time"] = api_deadline["time"]
            if api_deadline.get("timezone"):
                primary_deadline["timezone"] = api_deadline["timezone"]
            if api_deadline.get("note"):
                primary_deadline["note"] = api_deadline["note"]
            primary_deadline["detail_checked_at"] = detail_entry.get(
                "fetched_at"
            )
    elif api_date:
        deadlines.append(
            {
                "kind": (
                    "estimated_application"
                    if output.get("status") == "forecasted"
                    else "application"
                ),
                "date": api_date,
                "time": api_deadline.get("time"),
                "timezone": api_deadline.get("timezone"),
                "note": api_deadline.get("note"),
                "estimated": output.get("status") == "forecasted",
                "source": "Grants.gov detail API",
                "source_url": output.get("detail_page"),
                "confidence": "official_structured",
                "detail_checked_at": detail_entry.get("fetched_at"),
            }
        )

    preliminary = detail_entry.get("preliminary_deadline")
    if preliminary:
        deadlines.append(
            {
                **preliminary,
                "estimated": False,
                "source": "Grants.gov synopsis text",
                "source_url": output.get("detail_page"),
                "detail_checked_at": detail_entry.get("fetched_at"),
            }
        )
        output["has_preliminary_stage"] = True
        output["preliminary_stage_type"] = preliminary.get("kind")
        output["preliminary_deadline_text"] = preliminary.get("text")
        output["preliminary_deadline"] = preliminary.get("date")
        output["preliminary_required"] = preliminary.get("required")
        if preliminary.get("date") and preliminary.get("required"):
            output["actionability_status"] = (
                "preliminary_deadline_passed_verify"
                if preliminary["date"] < as_of.isoformat()
                else "preliminary_deadline_upcoming"
            )
        else:
            output["actionability_status"] = (
                "preliminary_stage_needs_verification"
            )
    elif output.get("has_preliminary_stage"):
        output["actionability_status"] = (
            "preliminary_stage_needs_verification"
        )
    elif output.get("status_verification_required"):
        output["actionability_status"] = "status_needs_verification"
    else:
        output["actionability_status"] = "current_by_structured_date"

    output["deadlines"] = deadlines
    if agency_page.get("status") in {
        "current",
        "archived",
        "not_archived",
    }:
        output["agency_status"] = agency_page["status"]
        output["agency_status_checked_at"] = agency_page.get("fetched_at")
        output["agency_status_source_url"] = agency_page.get("source_url")
        output["replacement_opportunity_number"] = agency_page.get(
            "replacement_opportunity_number"
        )
    if agency_page.get("status") == "current" and not output.get("close_date"):
        output["status_verification_required"] = False
        output["actionability_status"] = "current_by_agency"
    if agency_page.get("status") == "archived":
        output["status"] = "archived"
        output["status_verification_required"] = False
        output["actionability_status"] = "archived_by_agency"
    return output


def enrichment_metrics(records):
    def count(predicate):
        return sum(1 for record in records if predicate(record))

    return {
        "detail_enriched_count": count(
            lambda record: record.get("detail_enrichment_status") == "current"
        ),
        "detail_pending_count": count(
            lambda record: record.get("detail_enrichment_status") != "current"
        ),
        "primary_document_count": count(
            lambda record: record.get("primary_document_url")
        ),
        "agency_notice_count": count(
            lambda record: record.get("funding_opportunity_url")
        ),
        "agency_synopsis_count": count(
            lambda record: (
                record.get("description_source")
                == "Official NSF funding page"
            )
        ),
        "one_click_official_source_count": count(
            lambda record: (
                record.get("primary_document_url")
                or record.get("funding_opportunity_url")
                or record.get("detail_page")
            )
        ),
        "per_award_amount_count": count(
            lambda record: (
                record.get("award_floor")
                or record.get("award_ceiling")
            )
        ),
        "any_amount_count": count(
            lambda record: (
                record.get("award_floor")
                or record.get("award_ceiling")
                or record.get("total_program_funding")
            )
        ),
        "deadline_conflict_count": count(
            lambda record: record.get("deadline_conflict")
        ),
        "award_conflict_count": count(
            lambda record: record.get("award_conflicts")
        ),
        "preliminary_deadline_count": count(
            lambda record: record.get("preliminary_deadline")
        ),
        "contact_count": count(lambda record: record.get("contacts")),
        "contact_email_count": count(
            lambda record: any(
                contact.get("email")
                for contact in (record.get("contacts") or [])
                if isinstance(contact, dict)
            )
        ),
    }


def enrich_catalog(
    catalog,
    cache,
    *,
    max_updates=250,
    max_agency_updates=75,
    request_delay=0.25,
    fetcher=fetch_detail,
    agency_synopsis_fetcher=fetch_nsf_synopsis,
    now=None,
):
    now = now or utc_now()
    as_of = date.fromisoformat(catalog["generated_at"][:10])
    records = catalog["opportunities"]
    cached_records = cache.setdefault("records", {})
    current_ids = {
        str(record.get("opportunity_id"))
        for record in records
        if record.get("opportunity_id")
    }
    cache["records"] = {
        key: value
        for key, value in cached_records.items()
        if key in current_ids
    }
    cached_records = cache["records"]

    candidates = [
        record
        for record in records
        if record.get("opportunity_id")
        and (
            str(record["opportunity_id"]) not in cached_records
            or cached_records[str(record["opportunity_id"])].get(
                "source_signature"
            )
            != record_signature(record)
            or cached_records[str(record["opportunity_id"])].get(
                "contact_version", 0
            )
            < CONTACT_SCHEMA_VERSION
        )
    ]
    candidates.sort(
        key=lambda record: (
            0 if not record.get("funding_opportunity_url") else 1,
            0 if record.get("has_preliminary_stage") else 1,
            record.get("close_date") or "9999-12-31",
        )
    )

    refreshed = 0
    failures = []
    for record in candidates[:max_updates]:
        opportunity_id = str(record["opportunity_id"])
        try:
            response = fetcher(opportunity_id)
            detail = response.get("data", response)
            if not detail or not isinstance(detail, dict):
                raise RuntimeError("detail response did not contain data")
            cached_records[opportunity_id] = compact_detail(
                record,
                detail,
                now,
            )
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - retain other records
            failures.append(
                {
                    "opportunity_id": opportunity_id,
                    "error": str(exc)[:300],
                }
            )
        if request_delay:
            time.sleep(request_delay)

    agency_candidates = [
        record
        for record in records
        if agency_funding_page_due(
            record,
            cached_records.get(str(record.get("opportunity_id"))),
            now.date(),
        )
    ]
    agency_candidates.sort(
        key=lambda record: (
            0 if record.get("status_verification_required") else 1,
            -description_spacing_issue_count(record.get("description")),
            record.get("last_updated") or "",
            record.get("close_date") or "9999-12-31",
            record.get("title") or "",
        )
    )
    agency_refreshed = 0
    agency_failures = []
    for record in agency_candidates[:max_agency_updates]:
        opportunity_id = str(record["opportunity_id"])
        detail_entry = cached_records[opportunity_id]
        agency_url = (
            detail_entry.get("funding_opportunity_url")
            or record.get("funding_opportunity_url")
        )
        try:
            page = agency_synopsis_fetcher(agency_url)
            synopsis_text = clean_text(
                page.get("text") or page.get("synopsis")
            )
            source_url = safe_http_url(page.get("source_url"))
            page_status = str(page.get("status") or "current").casefold()
            if page_status not in {
                "current",
                "archived",
                "not_archived",
            }:
                raise RuntimeError(
                    "official agency page returned an invalid lifecycle status"
                )
            if page_status == "current" and len(synopsis_text) < 100:
                raise RuntimeError(
                    "official agency page did not return a usable synopsis"
                )
            if not is_nsf_url(source_url):
                raise RuntimeError(
                    "official agency funding-page source is not an NSF page"
                )
            detail_entry["agency_funding_page"] = {
                "text": (synopsis_text or "")[:12000],
                "source_url": source_url,
                "fetched_at": iso_utc(now),
                "parser_version": NSF_FUNDING_PAGE_PARSER_VERSION,
                "status": page_status,
                "replacement_opportunity_number": page.get(
                    "replacement_opportunity_number"
                ),
            }
            detail_entry.pop("agency_funding_page_error", None)
            agency_refreshed += 1
        except Exception as exc:  # noqa: BLE001 - retain Grants.gov text
            detail_entry["agency_funding_page_error"] = {
                "checked_at": iso_utc(now),
                "parser_version": NSF_FUNDING_PAGE_PARSER_VERSION,
                "error": str(exc)[:300],
            }
            agency_failures.append(
                {
                    "opportunity_id": opportunity_id,
                    "error": str(exc)[:300],
                }
            )
        if request_delay:
            time.sleep(request_delay)

    merged_records = [
        merge_detail(
            record,
            cached_records.get(str(record.get("opportunity_id"))),
            as_of,
        )
        for record in records
    ]
    archived_records = [
        record
        for record in merged_records
        if record.get("status") == "archived"
    ]
    merged = [normalize_record_facets(record) for record in merged_records]
    output = deepcopy(catalog)
    output["opportunities"] = merged
    output["record_count"] = len(merged)
    output["status_counts"] = dict(
        sorted(Counter(record.get("status") for record in merged).items())
    )
    output["facets"] = facet_counts(merged)
    output["search_index"] = build_search_index(merged)
    output.setdefault("source", {})["api_enrichment"] = {
        "endpoint": "https://api.grants.gov/v1/api/fetchOpportunity",
        "notice": API_NOTICE,
    }
    output["source"]["agency_funding_page_enrichment"] = {
        "scope": (
            "Official NSF funding pages for undated program lifecycle "
            "verification and damaged-synopsis repair"
        ),
        "recheck_days": AGENCY_FUNDING_PAGE_RECHECK_DAYS,
        "parser_version": NSF_FUNDING_PAGE_PARSER_VERSION,
    }
    output["detail_enrichment_generated_at"] = iso_utc(now)
    output.setdefault("diagnostics", {})["detail_enrichment"] = {
        **enrichment_metrics(merged),
        "agency_archived_count": len(archived_records),
        "agency_archived_records": [
            {
                "opportunity_id": record.get("opportunity_id"),
                "opportunity_number": record.get("opportunity_number"),
                "title": record.get("title"),
                "source_url": record.get("agency_status_source_url"),
                "replacement_opportunity_number": record.get(
                    "replacement_opportunity_number"
                ),
            }
            for record in archived_records
        ],
        "refreshed_count": refreshed,
        "failed_count": len(failures),
        "remaining_update_count": max(
            0,
            len(candidates) - min(len(candidates), max_updates),
        ),
        "failures": failures[:20],
        "agency_funding_page_refreshed_count": agency_refreshed,
        "agency_funding_page_failed_count": len(agency_failures),
        "agency_funding_page_remaining_update_count": max(
            0,
            len(agency_candidates)
            - min(len(agency_candidates), max_agency_updates),
        ),
        "agency_funding_page_failures": agency_failures[:20],
    }
    cache["generated_at"] = iso_utc(now)
    return output, cache


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Incrementally enrich the generated Grants.gov catalog."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Generated catalog JavaScript asset.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="Compact detail-enrichment cache.",
    )
    parser.add_argument(
        "--max-updates",
        type=int,
        default=250,
        help="Maximum new or changed detail records to fetch (default: 250).",
    )
    parser.add_argument(
        "--max-agency-updates",
        type=int,
        default=125,
        help=(
            "Maximum undated NSF funding pages to verify for lifecycle and "
            "synopsis quality (default: 125)."
        ),
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.25,
        help="Seconds between Grants.gov detail requests (default: 0.25).",
    )
    parser.add_argument(
        "--now",
        type=parse_now,
        default=None,
        help=(
            "Override the current time with a timezone-aware ISO 8601 "
            "timestamp for deterministic offline builds."
        ),
    )
    args = parser.parse_args(argv)
    if args.max_updates < 0:
        parser.error("--max-updates must be non-negative")
    if args.max_agency_updates < 0:
        parser.error("--max-agency-updates must be non-negative")
    if args.request_delay < 0:
        parser.error("--request-delay must be non-negative")
    return args


def main(argv=None):
    args = parse_args(argv)
    catalog = read_catalog(args.catalog)
    cache = read_cache(args.cache)
    enriched, cache = enrich_catalog(
        catalog,
        cache,
        max_updates=args.max_updates,
        max_agency_updates=args.max_agency_updates,
        request_delay=args.request_delay,
        now=args.now,
    )
    write_cache(cache, args.cache)
    write_catalog(enriched, args.catalog)
    diagnostics = enriched["diagnostics"]["detail_enrichment"]
    print(
        "Enriched "
        f"{diagnostics['detail_enriched_count']:,}/"
        f"{enriched['record_count']:,} records; "
        f"{diagnostics['primary_document_count']:,} direct documents; "
        f"{diagnostics['failed_count']:,} request failures."
    )


if __name__ == "__main__":
    main()
