"""Incrementally enrich the public catalog with Grants.gov detail evidence.

The daily XML extract remains the complete catalog source. This module uses the
public ``fetchOpportunity`` endpoint only for records that are new or changed,
then caches a compact set of official detail fields:

- likely primary NOFO/FOA attachment metadata;
- agency notice and document links;
- deadline notes, clock time, timezone, and preliminary-stage signals;
- award fields that are missing from the XML extract; and
- revision/history counters used to surface verification warnings.

No API key is required. Machine-selected documents and prose-extracted
deadlines remain visibly marked for verification.
"""

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse

from scripts.build_catalog import (
    CATALOG_GLOBAL,
    clean_text,
    iso_utc,
    numeric,
    write_catalog,
)
from scripts.pull_grants import (
    collect_attachments,
    fetch_detail,
    normalize,
)


CACHE_SCHEMA_VERSION = 2
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


def utc_now():
    return datetime.now(timezone.utc)


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


def safe_http_url(value):
    if not value:
        return None
    text = str(value).strip()
    if text.casefold().startswith("www."):
        text = f"https://{text}"
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else None


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
    }


def field_conflict(existing, enriched):
    return (
        existing not in (None, "")
        and enriched not in (None, "")
        and existing != enriched
    )


def merge_detail(record, detail_entry, as_of):
    output = deepcopy(record)
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

    agency_url = safe_http_url(
        detail_entry.get("funding_opportunity_url")
        or output.get("funding_opportunity_url")
    )
    output["funding_opportunity_url"] = agency_url
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
    }


def enrich_catalog(
    catalog,
    cache,
    *,
    max_updates=250,
    request_delay=0.25,
    fetcher=fetch_detail,
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

    merged = [
        merge_detail(
            record,
            cached_records.get(str(record.get("opportunity_id"))),
            as_of,
        )
        for record in records
    ]
    output = deepcopy(catalog)
    output["opportunities"] = merged
    output["record_count"] = len(merged)
    output.setdefault("source", {})["api_enrichment"] = {
        "endpoint": "https://api.grants.gov/v1/api/fetchOpportunity",
        "notice": API_NOTICE,
    }
    output["detail_enrichment_generated_at"] = iso_utc(now)
    output.setdefault("diagnostics", {})["detail_enrichment"] = {
        **enrichment_metrics(merged),
        "refreshed_count": refreshed,
        "failed_count": len(failures),
        "remaining_update_count": max(
            0,
            len(candidates) - min(len(candidates), max_updates),
        ),
        "failures": failures[:20],
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
        "--request-delay",
        type=float,
        default=0.25,
        help="Seconds between Grants.gov detail requests (default: 0.25).",
    )
    args = parser.parse_args(argv)
    if args.max_updates < 0:
        parser.error("--max-updates must be non-negative")
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
        request_delay=args.request_delay,
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
