"""
pull_grants.py
Pulls funding opportunities from the public Grants.gov REST API and normalizes
them into the screening schema we agreed on.

Run it:
    pip install requests
    python scripts/pull_grants.py
    python scripts/pull_grants.py --search-term catalysis --max-opportunities 5

Outputs:
    grants.json       -- normalized records
    grants_raw.json   -- untouched API response for the first opportunity,
                         so you can confirm the real field names

No API key needed. search2 and fetchOpportunity are open endpoints.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

SEARCH_URL = "https://api.grants.gov/v1/api/search2"
DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"

# Public detail page, useful as a human-readable fallback link.
DETAIL_PAGE = "https://www.grants.gov/search-results-detail/{opp_id}"

# Attachment download pattern. VERIFY THIS on the first run against a real
# opportunity that has a PDF. If it 404s, open a detail page in the browser,
# right-click the NOFO link, and copy the actual pattern here.
ATTACHMENT_URL = "https://grants.gov/grantsws/rest/opportunity/att/download/{att_id}"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "URochester-GrantMatcher/0.1 (marc.porosoff@rochester.edu)",
}

# Start narrow. Broaden once the output looks right. Each string is a separate
# search, because Grants.gov keyword search is literal and ORs poorly.
SEARCH_TERMS = [
    "catalysis",
    "carbon dioxide utilization",
    "carbon capture",
    "electrocatalysis",
    "separations",
    "machine learning materials",
    "chemical engineering",
]

# Only what a university can apply for.
ELIGIBILITY_CODES = [
    "25",  # Others (see text field entitled "Additional..." for clarification)
    "06",  # Public and State controlled institutions of higher education
    "20",  # Private institutions of higher education
    "12",  # Small businesses
]

# "posted" = open now. "forecasted" = announced but not yet open, which is the
# early warning we actually want.
OPP_STATUSES = "forecasted|posted"

ROWS_PER_PAGE = 100

# ---------------------------------------------------------------------------
# Pattern library for fields Grants.gov does not structure.
# These read the free-text description and pull out what a PI needs.
# ---------------------------------------------------------------------------

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

REQUIRED_RE = re.compile(r"\b(is\s+required|are\s+required|mandatory|must\s+submit)\b", re.I)

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
    # Allow a few intervening words, because NSF writes
    # "5:00 p.m. submitter's local time" and DOE writes "5 PM Eastern Time".
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


def post_json(url, payload, label):
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        error_code = data.get("errorcode")
        if error_code not in (None, 0, "0"):
            print(
                f"  ! {label} returned API error {error_code}: "
                f"{data.get('msg', 'unknown error')}",
                file=sys.stderr,
            )
            return None
        return data
    except requests.RequestException as exc:
        print(f"  ! {label} failed: {exc}", file=sys.stderr)
        return None
    except ValueError:
        print(f"  ! {label} returned non-JSON", file=sys.stderr)
        return None


def search(keyword, max_hits=None):
    """Return a list of opportunity stubs for one keyword, paging through all."""
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
        if not data:
            break

        body = data.get("data", {})
        page = body.get("oppHits", []) or []
        hits.extend(page)

        total = body.get("hitCount", len(hits))
        start += rows
        if start >= total or not page or (
            max_hits is not None and len(hits) >= max_hits
        ):
            break
        time.sleep(0.4)

    return hits


def fetch_detail(opp_id):
    return post_json(DETAIL_URL, {"opportunityId": opp_id}, f"detail {opp_id}")


def collect_attachments(detail):
    """Walk the attachment folders and return the NOFO PDFs first."""
    out = []
    folders = detail.get("synopsisAttachmentFolders") or []
    for folder in folders:
        for att in folder.get("synopsisAttachments", []) or []:
            att_id = att.get("id")
            name = att.get("fileName", "") or ""
            out.append({
                "id": att_id,
                "file_name": name,
                "description": att.get("fileDescription"),
                "mime_type": att.get("mimeType"),
                "size_bytes": att.get("fileLobSize"),
                "created_date": att.get("createdDate"),
                "folder_type": folder.get("folderType"),
                "folder_name": folder.get("folderName"),
                "download_url": ATTACHMENT_URL.format(att_id=att_id) if att_id else None,
            })

    def rank(att):
        name = (att["file_name"] or "").lower()
        desc = (att["description"] or "").lower()
        blob = name + " " + desc
        is_pdf = name.endswith(".pdf") or att["mime_type"] == "application/pdf"
        looks_like_nofo = bool(
            re.search(r"\b(nofo|foa|rfa|baa)\b", blob)
            or any(k in blob for k in ("funding opportunity announcement",
                                       "full announcement", "solicitation",
                                       "full text"))
        )
        looks_supplemental = any(
            k in blob
            for k in (
                "faq", "frequently asked", "appendix", "addendum", "sample",
                "template", "webinar", "questions", "special notice", "topics",
            )
        )
        is_amendment = "amendment" in blob
        return (
            not is_pdf,
            not looks_like_nofo,
            looks_supplemental,
            is_amendment,
            name,
        )

    out.sort(key=rank)
    return out


def first_match(pattern, text):
    if not text:
        return None
    m = pattern.search(text)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


def normalize(stub, detail):
    """Flatten the API response into the screening schema."""
    syn = detail.get("synopsis") or {}
    forecast = detail.get("forecast") or {}
    src = syn if syn else forecast
    agency_details = src.get("agencyDetails") or detail.get("agencyDetails") or {}

    description = src.get("synopsisDesc") or src.get("forecastDesc")
    close_note = (
        src.get("responseDateDesc")
        or src.get("estApplicationResponseDateDesc")
        or src.get("responseDateNote")
        or ""
    )

    # Every free-text field that might hide the details we care about.
    text_blob = " \n ".join(str(x) for x in [
        description,
        src.get("applicantEligibilityDesc"),
        close_note,
        src.get("agencyContactDesc"),
        src.get("fundingDescLinkDesc"),
        stub.get("title"),
    ] if x)

    close_date = (
        src.get("responseDate")
        or src.get("estApplicationResponseDate")
        or stub.get("closeDate")
    )

    # Deadline clock time and zone. Grants.gov puts this in the note field
    # rather than the date field, which is why a bare date is not enough.
    tz_match = TIMEZONE_RE.search(close_note) or TIMEZONE_RE.search(text_blob)
    deadline_time = tz_match.group(1).strip() if tz_match else None
    deadline_tz = re.sub(r"\s+", " ", tz_match.group(2)).strip() if tz_match else None

    # Concept paper / preproposal stage.
    cp_with_date = first_match(CONCEPT_PAPER_RE, text_blob)
    cp_mention = first_match(CONCEPT_PAPER_MENTION_RE, text_blob)
    has_prelim = bool(cp_mention)

    # Limited submission.
    limited = first_match(LIMITED_SUB_RE, text_blob)

    # Cost share. Prefer the structured flag, then look for the percentage.
    cost_share_flag = src.get("costSharing")
    cost_share_detail = first_match(COST_SHARE_RE, text_blob)

    attachments = collect_attachments(detail)
    nofo = attachments[0] if attachments else None
    funding_link = src.get("fundingDescLinkUrl") or None
    document_urls = detail.get("synopsisDocumentURLs") or []

    aln_records = detail.get("alns") or detail.get("cfdas") or []
    aln = []
    for record in aln_records:
        number = record.get("alnNumber") or record.get("cfdaNumber")
        if number and number not in aln:
            aln.append(number)
    if not aln:
        aln = stub.get("alnist") or stub.get("cfdaList") or []

    opp_id = detail.get("id") or stub.get("id")

    return {
        # identity
        "opportunity_id": opp_id,
        "opportunity_number": detail.get("opportunityNumber") or stub.get("number"),
        "title": detail.get("opportunityTitle") or stub.get("title"),
        "agency": (
            agency_details.get("agencyName")
            or src.get("agencyName")
            or stub.get("agency")
        ),
        "agency_code": (
            src.get("agencyCode")
            or detail.get("owningAgencyCode")
            or stub.get("agencyCode")
        ),
        "status": stub.get("oppStatus"),
        "doc_type": detail.get("docType") or stub.get("docType"),
        "aln": aln,
        "detail_page": DETAIL_PAGE.format(opp_id=opp_id) if opp_id else None,

        # the NOFO itself, one click away
        "nofo_pdf_url": nofo["download_url"] if nofo else None,
        "nofo_file_name": nofo["file_name"] if nofo else None,
        "funding_opportunity_url": funding_link,
        "primary_document_url": (
            nofo["download_url"] if nofo else funding_link
        ),
        "document_urls": document_urls,
        "all_attachments": attachments,

        # dates
        "posted_date": src.get("postingDate") or stub.get("openDate"),
        "estimated_posting_date": src.get("estSynopsisPostingDate"),
        "close_date": close_date,
        "close_date_note": close_note or None,
        "deadline_time": deadline_time,
        "deadline_timezone": deadline_tz,
        "archive_date": src.get("archiveDate"),
        "estimated_award_date": (
            src.get("estimatedAwardDate") or src.get("estAwardDate")
        ),
        "estimated_project_start": (
            src.get("estimatedProjectStartDate") or src.get("estProjectStartDate")
        ),
        "last_updated": src.get("lastUpdatedDate"),
        "version": src.get("version"),
        "rolling": bool(
            re.search(r"\brolling\b|open\s+until\s+superseded", close_note, re.I)
        ),

        # preliminary stage
        "has_preliminary_stage": has_prelim,
        "preliminary_stage_type": cp_mention,
        "preliminary_deadline_text": cp_with_date,
        "preliminary_required": bool(cp_mention and REQUIRED_RE.search(text_blob)),

        # limited submission
        "limited_submission": bool(limited),
        "limited_submission_criteria": limited,

        # cost share
        "cost_share_required": cost_share_flag,
        "cost_share_detail": cost_share_detail,

        # money
        "award_ceiling": src.get("awardCeiling"),
        "award_floor": src.get("awardFloor"),
        "total_program_funding": src.get("estimatedFunding"),
        "expected_number_of_awards": src.get("numberOfAwards"),

        # eligibility
        "applicant_types": [a.get("description") for a in
                            (src.get("applicantTypes") or []) if a],
        "eligibility_text": src.get("applicantEligibilityDesc"),
        "career_stage_signal": first_match(EARLY_CAREER_RE, text_blob),

        # program officer
        "contact_name": src.get("agencyContactName"),
        "contact_email": src.get("agencyContactEmail"),
        "contact_phone": src.get("agencyContactPhone"),

        # for the matcher downstream
        "description": description,
        "funding_categories": [c.get("description") for c in
                               (src.get("fundingActivityCategories") or []) if c],
        "funding_instruments": [i.get("description") for i in
                                (src.get("fundingInstruments") or []) if i],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Pull and normalize funding opportunities from Grants.gov."
    )
    parser.add_argument(
        "--search-term",
        action="append",
        dest="search_terms",
        help=(
            "Search term to use. Repeat for multiple terms. "
            "Defaults to the configured Chemical Engineering terms."
        ),
    )
    parser.add_argument(
        "--max-opportunities",
        type=int,
        help="Maximum unique opportunities to fetch after searching.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory for grants.json and grants_raw.json (default: current directory).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.3,
        help="Delay in seconds between detail requests (default: 0.3).",
    )
    args = parser.parse_args(argv)
    if args.max_opportunities is not None and args.max_opportunities < 1:
        parser.error("--max-opportunities must be at least 1")
    if args.request_delay < 0:
        parser.error("--request-delay cannot be negative")
    return args


def main(argv=None):
    args = parse_args(argv)
    search_terms = args.search_terms or SEARCH_TERMS

    print("Searching Grants.gov\n" + "-" * 55)

    stubs = {}
    for term in search_terms:
        remaining = None
        if args.max_opportunities is not None:
            remaining = args.max_opportunities - len(stubs)
            if remaining <= 0:
                break
        results = search(term, max_hits=remaining)
        new = 0
        for hit in results:
            key = hit.get("id")
            if key and key not in stubs:
                stubs[key] = hit
                new += 1
        print(f"  {term:<32} {len(results):>4} hits, {new:>4} new")

    if args.max_opportunities is not None:
        stubs = dict(list(stubs.items())[:args.max_opportunities])

    print(f"\n{len(stubs)} unique opportunities. Fetching detail...\n")

    if not stubs:
        sys.exit("No results. Check that the API shape has not changed.")

    records = []
    raw_sample = None

    for i, (opp_id, stub) in enumerate(stubs.items(), 1):
        detail_resp = fetch_detail(opp_id)
        if not detail_resp:
            continue
        detail = detail_resp.get("data", {})

        if raw_sample is None:
            raw_sample = detail_resp

        record = normalize(stub, detail)
        records.append(record)

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
        print(f"[{i}/{len(stubs)}] {title}{marker}")
        time.sleep(args.request_delay)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    grants_path = args.output_dir / "grants.json"
    raw_path = args.output_dir / "grants_raw.json"

    with grants_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False, default=str)

    if raw_sample:
        with raw_path.open("w", encoding="utf-8") as fh:
            json.dump(raw_sample, fh, indent=2, ensure_ascii=False, default=str)

    limited = sum(1 for r in records if r["limited_submission"])
    prelim = sum(1 for r in records if r["has_preliminary_stage"])
    tz = sum(1 for r in records if r["deadline_timezone"])
    pdfs = sum(1 for r in records if r["nofo_pdf_url"])

    print(f"\n{'-' * 55}")
    print(f"Normalized:                {len(records)}")
    print(f"With NOFO pdf link:        {pdfs}")
    print(f"Flagged limited submission:{limited:>4}")
    print(f"With preliminary stage:    {prelim:>4}")
    print(f"With deadline timezone:    {tz:>4}")
    print(f"\nWrote {grants_path} and {raw_path}")


if __name__ == "__main__":
    main()
