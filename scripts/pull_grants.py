"""
Diagnostic Grants.gov search/detail API normalizer.

Examples:
    python scripts/pull_grants.py --search-term catalysis --max-opportunities 5

The production browser catalog is built by ``scripts/build_catalog.py`` from
the complete daily XML extract. This earlier endpoint client remains useful
for detail-shape fixtures and future attachment enrichment. Its default output
is an ignored diagnostic file, ``data/api-sample.js``, so running it cannot
replace the schema-v2 production catalog.

No API key is required. Large raw API responses are intentionally not written.
Use ``--raw-sample-output`` only for temporary API-shape diagnostics.
"""

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
import json
import re
import sys
import time
from pathlib import Path

import requests

SEARCH_URL = "https://api.grants.gov/v1/api/search2"
DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
DETAIL_PAGE = "https://www.grants.gov/search-results-detail/{opp_id}"
ATTACHMENT_URL = "https://grants.gov/grantsws/rest/opportunity/att/download/{att_id}"
GRANTS_GOV_HOME = "https://www.grants.gov/"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "UR-Grant-Matcher/1.0",
}

# The initial audience is Chemical and Sustainability Engineering. Each term is
# searched separately because Grants.gov keyword behavior is more reliable for
# focused phrases than a large OR query.
SEARCH_TERMS = [
    "catalysis",
    '"carbon dioxide utilization"',
    '"carbon capture"',
    "electrocatalysis",
    "separations",
    '"machine learning" AND materials',
    '"chemical engineering"',
]

# Institutions of higher education plus "other" records whose free-text
# eligibility may include universities. Small-business opportunities remain
# useful when a university can participate as a research partner.
ELIGIBILITY_CODES = [
    "25",  # Others (see the additional eligibility text)
    "06",  # Public and state-controlled institutions of higher education
    "20",  # Private institutions of higher education
    "12",  # Small businesses
]

OPP_STATUSES = "forecasted|posted"
ROWS_PER_PAGE = 100
FEED_SCHEMA_VERSION = 1
FEED_GLOBAL = "GRANT_MATCH_FEED"

CONCEPT_PAPER_RE = re.compile(
    r"(concept\s+paper|pre[\s-]?proposal|pre[\s-]?application|"
    r"preliminary\s+proposal|letter\s+of\s+intent|LOI|white\s+paper)"
    r"[^.\n]{0,200}?"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)

CONCEPT_PAPER_MENTION_RE = re.compile(
    r"(concept\s+paper|pre[\s-]?proposal|pre[\s-]?application|"
    r"preliminary\s+proposal|letter\s+of\s+intent|white\s+paper)",
    re.I,
)

REQUIRED_RE = re.compile(
    r"\b(is\s+required|are\s+required|mandatory|must\s+submit)\b", re.I
)

LIMITED_SUB_RE = re.compile(
    r"((?:only\s+)?(?:one|two|three|1|2|3)\s+"
    r"(?:application|proposal|submission)s?[^.\n]{0,120}?"
    r"per\s+(?:institution|organization|applicant|university)|"
    r"limit(?:ed|s)?\s+(?:to\s+)?(?:one|two|three|1|2|3)\s+"
    r"(?:application|proposal|submission)[^.\n]{0,120})",
    re.I,
)

COST_SHARE_RE = re.compile(
    r"(cost\s+shar\w+|matching\s+funds?|non[\s-]?federal\s+share)"
    r"[^.\n]{0,180}?(\d{1,3}\s?(?:%|percent))",
    re.I,
)

TIMEZONE_RE = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?)"
    r"[\s,]*(?:(?:submitter|applicant|proposer|your|organization)'?s?\s+){0,2}"
    r"((?:Eastern|Central|Mountain|Pacific|ET|CT|MT|PT|EST|EDT|CST|CDT|"
    r"MST|MDT|PST|PDT|local)\s*(?:[Tt]ime|[Dd]aylight|[Ss]tandard)?"
    r"(?:\s*[Tt]ime)?)",
    re.I,
)

EARLY_CAREER_RE = re.compile(
    r"(early[\s-]?career|no\s+more\s+than\s+(\w+)\s+years?[^.\n]{0,60}"
    r"(?:doctora|PhD|Ph\.D)|within\s+(\w+)\s+years?\s+of[^.\n]{0,40}"
    r"(?:doctora|PhD|Ph\.D)|untenured|new\s+investigator|"
    r"tenure[\s-]track\s+assistant)",
    re.I,
)
EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.I,
)


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def post_json(url, payload, label, attempts=3):
    """POST JSON with bounded retries, then fail the refresh visibly."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                url, headers=HEADERS, json=payload, timeout=45
            )
            response.raise_for_status()
            data = response.json()
            error_code = data.get("errorcode")
            if error_code not in (None, 0, "0"):
                raise RuntimeError(
                    f"API error {error_code}: {data.get('msg', 'unknown error')}"
                )
            return data
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}")


def search(keyword, max_hits=None):
    """Return all matching opportunity stubs for one keyword."""
    hits = []
    start = 0
    while True:
        rows = ROWS_PER_PAGE
        if max_hits is not None:
            rows = min(rows, max_hits - len(hits))
            if rows <= 0:
                break
        payload = {
            "keyword": keyword,
            "oppStatuses": OPP_STATUSES,
            "eligibilities": "|".join(ELIGIBILITY_CODES),
            "rows": rows,
            "startRecordNum": start,
        }
        data = post_json(SEARCH_URL, payload, f"search '{keyword}'")
        body = data.get("data", {})
        page = body.get("oppHits", []) or []
        hits.extend(page)

        total = int(body.get("hitCount", len(hits)) or 0)
        start += rows
        if (
            start >= total
            or not page
            or (max_hits is not None and len(hits) >= max_hits)
        ):
            break
        time.sleep(0.4)
    return hits


def fetch_detail(opp_id):
    return post_json(
        DETAIL_URL, {"opportunityId": opp_id}, f"detail {opp_id}"
    )


def collect_attachments(detail):
    """Walk attachment folders and return likely primary NOFO PDFs first."""
    attachments = []
    for folder in detail.get("synopsisAttachmentFolders") or []:
        for attachment in folder.get("synopsisAttachments", []) or []:
            attachment_id = attachment.get("id")
            name = attachment.get("fileName", "") or ""
            attachments.append(
                {
                    "id": attachment_id,
                    "file_name": name,
                    "description": attachment.get("fileDescription"),
                    "mime_type": attachment.get("mimeType"),
                    "size_bytes": attachment.get("fileLobSize"),
                    "created_date": attachment.get("createdDate"),
                    "folder_type": folder.get("folderType"),
                    "folder_name": folder.get("folderName"),
                    "download_url": (
                        ATTACHMENT_URL.format(att_id=attachment_id)
                        if attachment_id
                        else None
                    ),
                }
            )

    def rank(attachment):
        name = (attachment["file_name"] or "").lower()
        description = (attachment["description"] or "").lower()
        text = name + " " + description
        is_pdf = (
            name.endswith(".pdf")
            or attachment["mime_type"] == "application/pdf"
        )
        looks_like_nofo = bool(
            re.search(r"\b(nofo|foa|rfa|baa)\b", text)
            or any(
                phrase in text
                for phrase in (
                    "funding opportunity announcement",
                    "full announcement",
                    "solicitation",
                    "full text",
                )
            )
        )
        looks_supplemental = any(
            phrase in text
            for phrase in (
                "faq",
                "frequently asked",
                "appendix",
                "addendum",
                "sample",
                "template",
                "webinar",
                "questions",
                "special notice",
                "topics",
            )
        )
        return (
            not is_pdf,
            not looks_like_nofo,
            looks_supplemental,
            "amendment" in text,
            name,
        )

    attachments.sort(key=rank)
    return attachments


def first_match(pattern, text):
    if not text:
        return None
    match = pattern.search(text)
    return (
        re.sub(r"\s+", " ", match.group(0)).strip() if match else None
    )


def normalize(stub, detail):
    """Flatten one API detail response into the public screening schema."""
    synopsis = detail.get("synopsis") or {}
    forecast = detail.get("forecast") or {}
    source_record = synopsis if synopsis else forecast
    agency_details = (
        source_record.get("agencyDetails")
        or detail.get("agencyDetails")
        or {}
    )

    description = source_record.get("synopsisDesc") or source_record.get(
        "forecastDesc"
    )
    close_note = (
        source_record.get("responseDateDesc")
        or source_record.get("estApplicationResponseDateDesc")
        or source_record.get("responseDateNote")
        or ""
    )
    text_blob = " \n ".join(
        str(value)
        for value in [
            description,
            source_record.get("applicantEligibilityDesc"),
            close_note,
            source_record.get("agencyContactDesc"),
            source_record.get("fundingDescLinkDesc"),
            stub.get("title"),
        ]
        if value
    )

    close_date = (
        source_record.get("responseDate")
        or source_record.get("estApplicationResponseDate")
        or stub.get("closeDate")
    )
    timezone_match = TIMEZONE_RE.search(close_note) or TIMEZONE_RE.search(
        text_blob
    )
    deadline_time = (
        timezone_match.group(1).strip() if timezone_match else None
    )
    deadline_timezone = (
        re.sub(r"\s+", " ", timezone_match.group(2)).strip()
        if timezone_match
        else None
    )

    preliminary_with_date = first_match(CONCEPT_PAPER_RE, text_blob)
    preliminary_mention = first_match(
        CONCEPT_PAPER_MENTION_RE, text_blob
    )
    limited_submission = first_match(LIMITED_SUB_RE, text_blob)
    cost_share_detail = first_match(COST_SHARE_RE, text_blob)

    attachments = collect_attachments(detail)
    nofo = attachments[0] if attachments else None
    funding_link = source_record.get("fundingDescLinkUrl") or None
    document_urls = detail.get("synopsisDocumentURLs") or []

    aln_records = detail.get("alns") or detail.get("cfdas") or []
    aln = []
    for record in aln_records:
        number = record.get("alnNumber") or record.get("cfdaNumber")
        if number and number not in aln:
            aln.append(number)
    if not aln:
        aln = stub.get("alnist") or stub.get("cfdaList") or []

    opportunity_id = detail.get("id") or stub.get("id")
    contact_name = source_record.get("agencyContactName")
    contact_phone = source_record.get("agencyContactPhone")
    contact_description = source_record.get("agencyContactDesc") or ""
    contact_emails = []
    email_text = " ".join(
        str(value or "")
        for value in (
            source_record.get("agencyContactEmail"),
            contact_description,
        )
    )
    for candidate in EMAIL_RE.findall(unescape(email_text)):
        value = str(candidate or "").strip().strip(".,;:")
        if value and value.casefold() not in {
            email.casefold() for email in contact_emails
        }:
            contact_emails.append(value)
    contacts = []
    if contact_name or contact_phone or contact_emails:
        contacts.append(
            {
                "name": contact_name,
                "email": contact_emails[0] if contact_emails else None,
                "phone": contact_phone,
                "role": "Agency contact",
                "source_url": (
                    DETAIL_PAGE.format(opp_id=opportunity_id)
                    if opportunity_id
                    else GRANTS_GOV_HOME
                ),
            }
        )
    return {
        "opportunity_id": opportunity_id,
        "opportunity_number": (
            detail.get("opportunityNumber") or stub.get("number")
        ),
        "title": detail.get("opportunityTitle") or stub.get("title"),
        "agency": (
            agency_details.get("agencyName")
            or source_record.get("agencyName")
            or stub.get("agency")
            or stub.get("agencyName")
        ),
        "agency_code": (
            source_record.get("agencyCode")
            or detail.get("owningAgencyCode")
            or stub.get("agencyCode")
        ),
        "status": (stub.get("oppStatus") or "").lower() or None,
        "doc_type": detail.get("docType") or stub.get("docType"),
        "source": "Grants.gov",
        "source_url": GRANTS_GOV_HOME,
        "matched_search_terms": stub.get("_matched_search_terms") or [],
        "aln": aln,
        "detail_page": (
            DETAIL_PAGE.format(opp_id=opportunity_id)
            if opportunity_id
            else None
        ),
        "nofo_pdf_url": nofo["download_url"] if nofo else None,
        "nofo_file_name": nofo["file_name"] if nofo else None,
        "funding_opportunity_url": funding_link,
        "primary_document_url": (
            nofo["download_url"] if nofo else funding_link
        ),
        "document_urls": document_urls,
        "all_attachments": attachments,
        "posted_date": (
            source_record.get("postingDate") or stub.get("openDate")
        ),
        "estimated_posting_date": source_record.get(
            "estSynopsisPostingDate"
        ),
        "close_date": close_date,
        "close_date_note": close_note or None,
        "deadline_time": deadline_time,
        "deadline_timezone": deadline_timezone,
        "archive_date": source_record.get("archiveDate"),
        "estimated_award_date": (
            source_record.get("estimatedAwardDate")
            or source_record.get("estAwardDate")
        ),
        "estimated_project_start": (
            source_record.get("estimatedProjectStartDate")
            or source_record.get("estProjectStartDate")
        ),
        "last_updated": source_record.get("lastUpdatedDate"),
        "version": source_record.get("version"),
        "rolling": bool(
            re.search(
                r"\brolling\b|open\s+until\s+superseded",
                close_note,
                re.I,
            )
        ),
        "has_preliminary_stage": bool(preliminary_mention),
        "preliminary_stage_type": preliminary_mention,
        "preliminary_deadline_text": preliminary_with_date,
        "preliminary_required": bool(
            preliminary_mention and REQUIRED_RE.search(text_blob)
        ),
        "limited_submission": bool(limited_submission),
        "limited_submission_criteria": limited_submission,
        "cost_share_required": source_record.get("costSharing"),
        "cost_share_detail": cost_share_detail,
        "award_ceiling": source_record.get("awardCeiling"),
        "award_floor": source_record.get("awardFloor"),
        "total_program_funding": source_record.get("estimatedFunding"),
        "expected_number_of_awards": source_record.get("numberOfAwards"),
        "applicant_types": [
            applicant.get("description")
            for applicant in (source_record.get("applicantTypes") or [])
            if applicant
        ],
        "eligibility_text": source_record.get("applicantEligibilityDesc"),
        "career_stage_signal": first_match(EARLY_CAREER_RE, text_blob),
        "contact_name": source_record.get("agencyContactName"),
        "contact_email": contact_emails[0] if contact_emails else None,
        "contact_phone": contact_phone,
        "contacts": contacts,
        "description": description,
        "funding_categories": [
            category.get("description")
            for category in (
                source_record.get("fundingActivityCategories") or []
            )
            if category
        ],
        "funding_instruments": [
            instrument.get("description")
            for instrument in (source_record.get("fundingInstruments") or [])
            if instrument
        ],
    }


def parse_grants_date(value):
    """Parse enough of the Grants.gov date family for freshness filtering."""
    if not value:
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        pass

    without_zone = re.sub(
        r"\s+(?:EDT|EST|CDT|CST|MDT|MST|PDT|PST)$", "", raw, flags=re.I
    )
    formats = (
        "%b %d, %Y %I:%M:%S %p",
        "%B %d, %Y %I:%M:%S %p",
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    )
    for date_format in formats:
        try:
            return datetime.strptime(without_zone, date_format).date()
        except ValueError:
            continue
    return None


def record_identity(record):
    number = re.sub(
        r"\s+", "", str(record.get("opportunity_number") or "")
    ).casefold()
    if number:
        return f"number:{number}"
    opportunity_id = record.get("opportunity_id")
    return f"id:{opportunity_id}" if opportunity_id is not None else None


def record_rank(record):
    status_rank = {"posted": 2, "forecasted": 1}.get(
        str(record.get("status") or "").lower(), 0
    )
    updated = (
        parse_grants_date(record.get("last_updated"))
        or parse_grants_date(record.get("posted_date"))
        or date.min
    )
    return status_rank, updated, int(record.get("version") or 0)


def is_closed(record, as_of):
    status = str(record.get("status") or "").lower()
    if status in {"closed", "archived"}:
        return True
    if status != "posted" or record.get("rolling"):
        return False
    close_date = parse_grants_date(record.get("close_date"))
    return bool(close_date and close_date < as_of)


def prepare_records(records, as_of=None):
    """Deduplicate records and remove posted notices whose due date passed."""
    as_of = as_of or utc_now().date()
    unique = {}
    unidentifiable = 0
    for record in records:
        identity = record_identity(record)
        if not identity:
            unidentifiable += 1
            continue
        current = unique.get(identity)
        if current is None or record_rank(record) > record_rank(current):
            unique[identity] = record

    deduplicated_count = len(records) - len(unique) - unidentifiable
    current_records = []
    closed_count = 0
    for record in unique.values():
        if is_closed(record, as_of):
            closed_count += 1
        else:
            current_records.append(record)
    current_records.sort(
        key=lambda record: (
            str(record.get("title") or "").casefold(),
            str(record.get("opportunity_number") or ""),
        )
    )
    return current_records, {
        "deduplicated_count": deduplicated_count,
        "closed_removed_count": closed_count,
        "unidentifiable_removed_count": unidentifiable,
    }


def validate_records(records, minimum, maximum):
    count = len(records)
    if count < minimum:
        raise RuntimeError(
            f"Implausible feed: {count} records is below minimum {minimum}."
        )
    if count > maximum:
        raise RuntimeError(
            f"Implausible feed: {count} records exceeds maximum {maximum}."
        )

    bad = [
        record
        for record in records
        if not record.get("title") or not record_identity(record)
    ]
    if bad:
        raise RuntimeError(
            f"Implausible feed: {len(bad)} records lack a title or identity."
        )

    unique_count = len({record_identity(record) for record in records})
    if unique_count != count:
        raise RuntimeError("Implausible feed: duplicate opportunity identities.")


def clean_public_text(value):
    if value is None:
        return None
    text = str(value)
    text = re.sub(
        r"<\s*(?:br|/p|/div|/li|/h[1-6])\s*/?\s*>",
        "\n",
        text,
        flags=re.I,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(unescape(text)).replace("\xa0", " ")
    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in text.replace("\r", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line).strip() or None


def public_record(record):
    """Remove detail-response bulk that the browser application does not use."""
    published = dict(record)
    published.pop("all_attachments", None)
    published.pop("document_urls", None)
    text_fields = (
        "title",
        "agency",
        "description",
        "eligibility_text",
        "close_date_note",
        "limited_submission_criteria",
        "cost_share_detail",
        "career_stage_signal",
        "preliminary_stage_type",
        "preliminary_deadline_text",
        "nofo_file_name",
    )
    for field in text_fields:
        published[field] = clean_public_text(published.get(field))
    for field in (
        "applicant_types",
        "funding_categories",
        "funding_instruments",
    ):
        published[field] = [
            cleaned
            for item in (published.get(field) or [])
            if (cleaned := clean_public_text(item))
        ]
    return published


def build_feed(records, generated_at, search_terms, diagnostics):
    status_counts = Counter(
        str(record.get("status") or "unknown") for record in records
    )
    return {
        "schema_version": FEED_SCHEMA_VERSION,
        "source": {
            "name": "Grants.gov",
            "url": GRANTS_GOV_HOME,
            "search_api": SEARCH_URL,
        },
        "generated_at": iso_utc(generated_at),
        "record_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "search_terms": list(search_terms),
        "diagnostics": diagnostics,
        "opportunities": [public_record(record) for record in records],
    }


def write_feed(feed, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        feed, indent=2, ensure_ascii=False, separators=(",", ": ")
    ).replace("</", "<\\/")
    content = (
        "/* Generated by scripts/pull_grants.py. Do not edit by hand. */\n"
        f"globalThis.{FEED_GLOBAL} = {payload};\n"
    )
    output_path.write_text(content, encoding="utf-8", newline="\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a diagnostic feed from Grants.gov API searches."
    )
    parser.add_argument(
        "--search-term",
        action="append",
        dest="search_terms",
        help=(
            "Search term to use. Repeat for multiple terms. Defaults to the "
            "configured Chemical and Sustainability Engineering terms."
        ),
    )
    parser.add_argument(
        "--max-opportunities",
        type=int,
        help="Maximum unique search hits to fetch (primarily for diagnostics).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/api-sample.js"),
        help="Diagnostic JavaScript asset (default: data/api-sample.js).",
    )
    parser.add_argument(
        "--raw-sample-output",
        type=Path,
        help="Optional diagnostic path for one raw detail API response.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.3,
        help="Delay in seconds between detail requests (default: 0.3).",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=1,
        help="Fail if the published feed has fewer records (default: 1).",
    )
    parser.add_argument(
        "--max-record-count",
        type=int,
        default=1000,
        help="Fail if the published feed has more records (default: 1000).",
    )
    args = parser.parse_args(argv)
    if args.max_opportunities is not None and args.max_opportunities < 1:
        parser.error("--max-opportunities must be at least 1")
    if args.request_delay < 0:
        parser.error("--request-delay cannot be negative")
    if args.min_records < 1:
        parser.error("--min-records must be at least 1")
    if args.max_record_count < args.min_records:
        parser.error("--max-record-count must be at least --min-records")
    return args


def main(argv=None):
    args = parse_args(argv)
    search_terms = args.search_terms or SEARCH_TERMS
    generated_at = utc_now()

    print("Searching Grants.gov\n" + "-" * 55)
    stubs = {}
    total_search_hits = 0
    for term in search_terms:
        remaining = None
        if args.max_opportunities is not None:
            remaining = args.max_opportunities - len(stubs)
            if remaining <= 0:
                break
        results = search(term, max_hits=remaining)
        total_search_hits += len(results)
        new = 0
        for hit in results:
            key = hit.get("id")
            if not key:
                continue
            if key not in stubs:
                stubs[key] = {**hit, "_matched_search_terms": [term]}
                new += 1
            elif term not in stubs[key]["_matched_search_terms"]:
                stubs[key]["_matched_search_terms"].append(term)
        print(f"  {term:<32} {len(results):>4} hits, {new:>4} new")

    if args.max_opportunities is not None:
        stubs = dict(list(stubs.items())[: args.max_opportunities])
    if not stubs:
        raise RuntimeError("No search results; the API shape may have changed.")

    print(f"\n{len(stubs)} unique search hits. Fetching detail...\n")
    normalized = []
    raw_sample = None
    for index, (opportunity_id, stub) in enumerate(stubs.items(), 1):
        detail_response = fetch_detail(opportunity_id)
        detail = detail_response.get("data", {})
        if raw_sample is None:
            raw_sample = detail_response
        record = normalize(stub, detail)
        normalized.append(record)

        flags = []
        if record["limited_submission"]:
            flags.append("LIMITED SUB")
        if record["has_preliminary_stage"]:
            flags.append("PRELIM STAGE")
        if record["cost_share_required"]:
            flags.append("COST SHARE")
        if not record["nofo_pdf_url"]:
            flags.append("no pdf")
        marker = f"  [{', '.join(flags)}]" if flags else ""
        title = (record["title"] or "")[:58]
        print(f"[{index}/{len(stubs)}] {title}{marker}")
        time.sleep(args.request_delay)

    records, preparation = prepare_records(
        normalized, as_of=generated_at.date()
    )
    validate_records(records, args.min_records, args.max_record_count)
    diagnostics = {
        "search_hit_count": total_search_hits,
        "unique_search_hit_count": len(stubs),
        **preparation,
    }
    feed = build_feed(records, generated_at, search_terms, diagnostics)
    write_feed(feed, args.output)

    if args.raw_sample_output and raw_sample:
        args.raw_sample_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_sample_output.write_text(
            json.dumps(raw_sample, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    status_counts = Counter(record["status"] for record in records)
    limited = sum(1 for record in records if record["limited_submission"])
    preliminary = sum(
        1 for record in records if record["has_preliminary_stage"]
    )
    print(f"\n{'-' * 55}")
    print(f"Published:                 {len(records)}")
    print(f"Posted / forecasted:       "
          f"{status_counts.get('posted', 0)} / "
          f"{status_counts.get('forecasted', 0)}")
    print(f"Removed as closed:         {preparation['closed_removed_count']}")
    print(f"Deduplicated:              {preparation['deduplicated_count']}")
    print(f"Flagged limited submission:{limited:>4}")
    print(f"With preliminary stage:    {preliminary:>4}")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
