"""Build the complete public opportunity catalog and browser search index.

The builder downloads the official daily Grants.gov XML database extract,
streams the compressed XML without unpacking it to disk, keeps current posted
and forecast opportunities, normalizes them, and emits the static JavaScript
asset used by GitHub Pages.

Run:
    python -m scripts.build_catalog
    python -m scripts.build_catalog --archive GrantsDBExtract20260725v2.zip
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from html import unescape
import json
import math
from pathlib import Path
import re
import tempfile
import unicodedata
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree.ElementTree import iterparse
from zipfile import ZipFile

import requests


EXTRACT_PAGE = "https://www.grants.gov/xml-extract"
GRANTS_HOME = "https://www.grants.gov/"
DETAIL_PAGE = "https://www.grants.gov/search-results-detail/{opportunity_id}"
CATALOG_GLOBAL = "GRANT_CATALOG"
CATALOG_METADATA_GLOBAL = "GRANT_CATALOG_METADATA"
CATALOG_METADATA_FILENAME = "catalog-metadata.js"
CATALOG_METADATA_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = 3
USER_AGENT = "UR-Grant-Matcher-Catalog/1.0"
HTTPS_UPGRADE_HOSTS = {
    "grants.gov",
    "www.grants.gov",
    "grants.nih.gov",
    "www.grants.nih.gov",
    "nsf.gov",
    "www.nsf.gov",
    "nspires.nasaprs.com",
    "www.nspires.nasaprs.com",
}

CATEGORY_NAMES = {
    "ACA": "Affordable Care Act",
    "AG": "Agriculture",
    "AR": "Arts",
    "BC": "Business and Commerce",
    "CD": "Community Development",
    "CP": "Consumer Protection",
    "DPR": "Disaster Prevention and Relief",
    "ED": "Education",
    "ELT": "Employment, Labor and Training",
    "EN": "Energy",
    "ENV": "Environment",
    "FN": "Food and Nutrition",
    "HL": "Health",
    "HO": "Housing",
    "HU": "Humanities",
    "ISS": "Income Security and Social Services",
    "IS": "Information and Statistics",
    "LJL": "Law, Justice and Legal Services",
    "NR": "Natural Resources",
    "O": "Other",
    "OZ": "Opportunity Zone Benefits",
    "RA": "Recovery Act",
    "RD": "Regional Development",
    "ST": "Science and Technology and other Research and Development",
    "T": "Transportation",
}

ELIGIBILITY_NAMES = {
    "00": "State governments",
    "01": "County governments",
    "02": "City or township governments",
    "04": "Special district governments",
    "05": "Independent school districts",
    "06": "Public and state institutions of higher education",
    "07": "Federally recognized Native American tribal governments",
    "08": "Public and Indian housing authorities",
    "11": "Other Native American tribal organizations",
    "12": "Nonprofits with 501(c)(3) status",
    "13": "Nonprofits without 501(c)(3) status",
    "20": "Private institutions of higher education",
    "21": "Individuals",
    "22": "For-profit organizations other than small businesses",
    "23": "Small businesses",
    "25": "Other",
    "99": "Unrestricted",
}

INSTRUMENT_NAMES = {
    "CA": "Cooperative Agreement",
    "G": "Grant",
    "PC": "Procurement Contract",
    "O": "Other",
}

OPPORTUNITY_CATEGORY_NAMES = {
    "D": "Discretionary",
    "M": "Mandatory",
    "C": "Continuation",
    "E": "Earmark",
    "O": "Other",
}

DISCIPLINE_BY_CATEGORY = {
    "ACA": "Medical and Health",
    "AG": "Environmental and Life Sciences",
    "AR": "Arts and Humanities",
    "BC": "Business and Economic Development",
    "CD": "Community and Social Sciences",
    "CP": "Community and Social Sciences",
    "DPR": "Community and Social Sciences",
    "ED": "Education",
    "ELT": "Community and Social Sciences",
    "EN": "Engineering and Physical Sciences",
    "ENV": "Environmental and Life Sciences",
    "FN": "Environmental and Life Sciences",
    "HL": "Medical and Health",
    "HO": "Community and Social Sciences",
    "HU": "Arts and Humanities",
    "ISS": "Community and Social Sciences",
    "IS": "Engineering and Physical Sciences",
    "LJL": "Community and Social Sciences",
    "NR": "Environmental and Life Sciences",
    "OZ": "Business and Economic Development",
    "RD": "Business and Economic Development",
    "ST": "Engineering and Physical Sciences",
    "T": "Engineering and Physical Sciences",
}

# Facets are a controlled vocabulary.  External listings often provide a
# sentence-sized "discipline" field; those words remain searchable through the
# title/description, while this mapping keeps the filter itself stable.
DISCIPLINE_RULES = {
    "Engineering and Physical Sciences": (
        r"\b(?:chem(?:istry|ical)|computer science|computing|engineering|"
        r"mathematics?|physics?|physical science|quantum|statistics?)\b"
    ),
    "Environmental and Life Sciences": (
        r"\b(?:agricultur|biolog|ecolog|environment|earth systems?|geoscience|"
        r"life science|natural resource)\w*\b"
    ),
    "Medical and Health": (
        r"\b(?:biomedical|clinical|health|medicine|medical|neuroscience)\w*\b"
    ),
    "Community and Social Sciences": (
        r"\b(?:anthropolog|behavioral science|political science|psycholog|"
        r"social science|sociolog)\w*\b"
    ),
    "Business and Economic Development": (
        r"\b(?:business|commerce|economic|economics|entrepreneur)\w*\b"
    ),
    "Education": r"\b(?:education|pedagogy|teaching)\w*\b",
    "Arts and Humanities": (
        r"\b(?:arts?|culture|history|humanities|language|literature|music|"
        r"philosophy|theater)\w*\b"
    ),
}
DISCIPLINE_NAMES = tuple(dict.fromkeys(DISCIPLINE_BY_CATEGORY.values()))
DISCIPLINE_NAME_LOOKUP = {name.casefold(): name for name in DISCIPLINE_NAMES}

TOPIC_RULES = {
    "Agriculture and food": r"\b(?:agricultur|crop|food|farm|livestock|soil)\w*",
    "Artificial intelligence and machine learning": (
        r"\b(?:artificial intelligence|machine learning|deep learning|"
        r"generative ai|AI/ML)\b"
    ),
    # Keep "art" and "arts" as complete words. The former pattern allowed
    # "artificial intelligence" to assign Arts and culture to AI notices.
    "Arts and culture": (
        r"\b(?:arts?\b|cultur\w*|museum\w*|music\w*|theater\w*|humanities\w*)"
    ),
    "Biology and biotechnology": (
        r"\b(?:biolog|biotechnolog|genom|proteom|cellular|microbiom)\w*"
    ),
    "Cancer": r"\b(?:cancer|oncolog|tumou?r|carcinom|neoplasm)\w*",
    "Carbon management": (
        r"\b(?:carbon capture|carbon utilization|carbon storage|"
        r"carbon management|direct air capture|CO2)\b"
    ),
    "Catalysis and reaction engineering": (
        r"\b(?:catalys(?:is|es)|catalytic (?:reaction|process|conversion|"
        r"activity|material|system|site|mechanism|chemistry|engineering|"
        r"technology|performance)|(?:electro|photo|thermo)catalys\w*|"
        r"reaction engineering|reactor design)\b"
    ),
    "Climate change": (
        r"\b(?:climate change|decarboni[sz]|greenhouse gas|global warming|"
        r"climate resilience)\w*"
    ),
    "Community development": (
        r"\b(?:community development|community engagement|rural development|"
        r"economic development)\b"
    ),
    "Cybersecurity": r"\b(?:cybersecurity|cyber security|information security)\b",
    "Data science": r"\b(?:data science|data analytics|big data|informatics)\b",
    "Education and workforce": (
        r"\b(?:education|student|teacher|curriculum|workforce|training)\w*"
    ),
    "Energy": (
        r"\b(?:energy|battery|fuel cell|hydrogen|solar|wind power|"
        r"nuclear power|grid)\w*"
    ),
    "Environmental science": (
        r"\b(?:environment|ecosystem|ecolog|pollution|conservation|"
        r"biodiversity)\w*"
    ),
    "Health equity": (
        r"\b(?:health disparit|health equit|underserved population|"
        r"social determinants of health)\w*"
    ),
    "Infectious disease": (
        r"\b(?:infectious disease|virus|viral|bacteri|pathogen|pandemic)\w*"
    ),
    "Manufacturing": (
        r"\b(?:manufactur|industrial process|supply chain|semiconductor)\w*"
    ),
    "Materials science": (
        r"\b(?:materials? science|advanced materials?|polymer|nanomaterial|"
        r"metallurg|ceramic)\w*"
    ),
    "Neuroscience": (
        r"\b(?:neuroscien|neurolog|brain|cognitive|neurodegener)\w*"
    ),
    "Public health": (
        r"\b(?:public health|population health|epidemiolog|health services)\w*"
    ),
    "Quantum science": r"\b(?:quantum|qubit|quantum computing)\w*",
    "Separations and membranes": (
        r"\b(?:separation science|membrane|adsorption|chromatograph|"
        r"purification)\w*"
    ),
    "Social and behavioral sciences": (
        r"\b(?:social science|behavioral|psycholog|sociolog|human behavior)\w*"
    ),
    "Space and aeronautics": (
        r"\b(?:spacecraft|aeronautic|aerospace|NASA|space science)\w*"
    ),
    "Technology development": (
        r"\b(?:technology development|prototype|commerciali[sz]|innovation)\w*"
    ),
    "Transportation": (
        r"\b(?:transportation|transit|rail|aviation|vehicle|maritime)\w*"
    ),
    "Water": (
        r"\b(?:water treatment|wastewater|drinking water|water quality|"
        r"desalination|hydrolog)\w*"
    ),
}

COMPILED_TOPIC_RULES = {
    name: re.compile(pattern, re.I) for name, pattern in TOPIC_RULES.items()
}

PRELIMINARY_RE = re.compile(
    r"\b(concept\s+paper|pre[\s-]?proposal|pre[\s-]?application|"
    r"preliminary\s+proposal|letter\s+of\s+intent|LOI|white\s+paper)\b",
    re.I,
)
NON_FUNDING_TITLE_RE = re.compile(
    r"^(?:[A-Z0-9-]+\s+)?(?:"
    r"notice\s+of\s+intent(?:\s+to\s+issue)?\b|"
    r"NOI\s*[-:]|"
    r"request\s+for\s+information\b|"
    r"RFI\s*[-:]"
    r")",
    re.I,
)
TEST_OPPORTUNITY_RE = re.compile(
    r"\btest (?:NOFO|funding opportunity)\b.{0,120}\bdo not apply\b",
    re.I | re.S,
)
NOT_ACCEPTING_RE = re.compile(
    r"\b(?:not|isn't|is\s+not)\s+accepting\s+applications?\b|"
    r"\bno\s+applications?\s+(?:are|will\s+be)\s+accepted\b",
    re.I,
)
LIMITED_SUBMISSION_RE = re.compile(
    r"(?:limit(?:ed|s)?\s+(?:to\s+)?(?:one|two|three|1|2|3)\s+"
    r"(?:application|proposal|submission)|(?:one|two|three|1|2|3)\s+"
    r"(?:application|proposal|submission)s?.{0,120}per\s+"
    r"(?:institution|organization|applicant|university))",
    re.I,
)
ROLLING_RE = re.compile(
    r"(?:\bopen\s+until\s+superseded\b|"
    r"\b(?:full\s+)?proposals?\s+(?:are\s+)?accepted\s+anytime\b|"
    r"\bon\s+(?:an?\s+)?rolling\s+basis\b|"
    r"\brolling\s+(?:deadline|application|applications|submission|"
    r"submissions|acceptance|review)\b|"
    r"\b(?:application|applications|proposal|proposals|submission|"
    r"submissions)\s+(?:are\s+|will\s+be\s+)?"
    r"(?:accepted|received|reviewed)\s+(?:on\s+)?"
    r"(?:an?\s+)?rolling\b)",
    re.I,
)
MAX_REAL_CLOSE_DATE_DAYS = 366 * 25
EARLY_CAREER_RE = re.compile(
    r"\b(early[\s-]?career|new investigator|young investigator|junior faculty|"
    r"postdoctoral|predoctoral|untenured|assistant professor)\b",
    re.I,
)

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.-]{1,}")
STOP_WORDS = {
    "a", "about", "after", "all", "also", "an", "and", "any", "application",
    "applications", "are", "as", "at", "award", "awards", "be", "been",
    "being", "by", "can", "for", "from", "funding", "grant", "grants", "has",
    "have", "in", "including", "is", "it", "may", "more", "must", "new", "not",
    "of", "on", "opportunities", "opportunity", "or", "other", "program",
    "project", "projects", "proposal", "proposals", "research", "shall", "should",
    "support", "than", "that", "the", "their", "these", "this", "through", "to",
    "under", "use", "using", "was", "we", "which", "will", "with",
}


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_text(value):
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
    text = "\n".join(line for line in lines if line).strip()
    # Grants.gov descriptions often flatten HTML block boundaries without a
    # separating space ("partner.Projects" or "ObjectivesEach"). Repair only
    # high-confidence boundaries so chemical names and ordinary punctuation
    # remain untouched.
    text = re.sub(r"(?<=[a-z0-9][.!?])(?=[A-Z])", " ", text)
    text = re.sub(
        r"\b(Objectives?|Background|Purpose|Overview|Eligibility|Description|"
        r"Activities|Goals|Benefits)(?=[A-Z][a-z])",
        r"\1: ",
        text,
    )
    text = re.sub(r"(?<=[,:;])(?=[A-Za-z])", " ", text)
    return text or None


def safe_http_url(value):
    text = clean_text(value)
    if not text:
        return None
    if text.casefold().startswith("www."):
        text = f"https://{text}"
    parsed = urlparse(text)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme == "http" and (
        hostname in HTTPS_UPGRADE_HOSTS
        or hostname.endswith(".gov")
        or hostname.endswith(".mil")
    ):
        parsed = parsed._replace(scheme="https")
        text = urlunparse(parsed)
    return (
        text
        if parsed.scheme in {"http", "https"} and parsed.netloc
        else None
    )


def parse_extract_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%m%d%Y").date()
    except ValueError:
        return None


def iso_date(value):
    parsed = parse_extract_date(value)
    return parsed.isoformat() if parsed else None


def first(values, key):
    items = values.get(key) or []
    return items[0] if items else None


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def normalize_disciplines(values):
    """Map free-form source labels into the catalog's discipline taxonomy."""
    if not isinstance(values, (list, tuple, set)):
        values = [values] if values else []
    normalized = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        canonical = DISCIPLINE_NAME_LOOKUP.get(text.casefold())
        if canonical:
            normalized.append(canonical)
            continue
        normalized.extend(
            name
            for name, pattern in DISCIPLINE_RULES.items()
            if re.search(pattern, text, flags=re.I)
        )
    return unique(normalized)


def source_facet_value(record):
    """Return a stable user-selectable source without changing provenance.

    Official federal pages can supplement Grants.gov (for example, when an NSF
    program accepts proposals only through Research.gov).  These records stay
    attributed to their agency on cards and links, but do not create isolated
    agency-specific Source options.  Users can still select them through the
    Federal source type or their agency.
    """
    source = clean_text(record.get("source"))
    if (clean_text(record.get("source_type")) or "").casefold() == "federal":
        return "Grants.gov" if (source or "").casefold() == "grants.gov" else None
    return source


def normalize_record_facets(record):
    """Normalize every controlled facet on a catalog record in place."""
    record["disciplines"] = normalize_disciplines(record.get("disciplines"))
    record["source_facet"] = source_facet_value(record)
    return record


def values_by_tag(element):
    values = defaultdict(list)
    for child in element:
        tag = child.tag.rsplit("}", 1)[-1]
        value = (child.text or "").strip()
        if value:
            values[tag].append(value)
    return values


def numeric(value):
    if value in (None, ""):
        return None
    try:
        number = int(str(value).replace(",", "").replace("$", "").strip())
        return number if number > 0 else None
    except ValueError:
        return None


def is_current(values, status, as_of):
    title = clean_text(first(values, "OpportunityTitle")) or ""
    if NON_FUNDING_TITLE_RE.search(title):
        return False
    agency = clean_text(first(values, "AgencyName")) or ""
    raw_description = " ".join(values.get("Description") or [])
    if re.search(r"\bIV&V Test Agency\b", agency, re.I) or TEST_OPPORTUNITY_RE.search(raw_description):
        return False
    instrument_codes = {
        value.casefold()
        for value in (values.get("FundingInstrumentType") or [])
        if value
    }
    description = raw_description
    if (
        instrument_codes
        and instrument_codes <= {"o"}
        and NOT_ACCEPTING_RE.search(description[:2500])
    ):
        return False

    archive = parse_extract_date(first(values, "ArchiveDate"))
    close_field = (
        "EstimatedSynopsisCloseDate"
        if status == "forecasted"
        else "CloseDate"
    )
    close = parse_extract_date(first(values, close_field))
    if close:
        return close >= as_of
    if archive:
        return archive >= as_of

    if status == "forecasted":
        # An undated forecast can remain in the extract long after the planned
        # funding year. Keep current/future forecasts, but do not present an
        # old fiscal-year placeholder as an active opportunity.
        fiscal_year = first(values, "FiscalYear")
        if fiscal_year and fiscal_year.isdigit():
            if int(fiscal_year) < as_of.year:
                return False

        milestone_dates = [
            parse_extract_date(first(values, field))
            for field in ("EstimatedAwardDate", "EstimatedProjectStartDate")
        ]
        dated_milestones = [value for value in milestone_dates if value]
        if dated_milestones and max(dated_milestones) < as_of:
            return False

        # Some forecasts omit every planning date. Treat one that has not
        # changed in eighteen months as stale instead of retaining it forever.
        last_updated = parse_extract_date(first(values, "LastUpdatedDate"))
        if last_updated and (as_of - last_updated).days > 548:
            return False
        return True

    rolling = bool(ROLLING_RE.search(description))
    if rolling:
        return True
    # Grants.gov keeps active, recurring program descriptions that intentionally
    # omit both dates. Include them, but normalization flags them for explicit
    # status verification in the browser.
    return True


def topic_areas(title, description, categories):
    text = " ".join(
        part for part in (title, description, " ".join(categories)) if part
    )
    return [
        name
        for name, pattern in COMPILED_TOPIC_RULES.items()
        if pattern.search(text)
    ]


def normalize_element(element, as_of):
    tag = element.tag.rsplit("}", 1)[-1]
    status = (
        "forecasted"
        if tag == "OpportunityForecastDetail_1_0"
        else "posted"
    )
    values = values_by_tag(element)
    if not is_current(values, status, as_of):
        return None

    opportunity_id = first(values, "OpportunityID")
    title = clean_text(first(values, "OpportunityTitle"))
    number = clean_text(first(values, "OpportunityNumber"))
    if not title or not (opportunity_id or number):
        return None

    description = clean_text(first(values, "Description"))
    eligibility_text = clean_text(
        first(values, "AdditionalInformationOnEligibility")
    )
    close_note = clean_text(
        first(values, "EstimatedSynopsisCloseDateExplanation")
    )
    text_blob = " ".join(
        part for part in (title, description, eligibility_text, close_note)
        if part
    )

    category_codes = unique(values.get("CategoryOfFundingActivity") or [])
    categories = [
        CATEGORY_NAMES.get(code, code) for code in category_codes
    ]
    eligibility_codes = unique(values.get("EligibleApplicants") or [])
    applicant_types = [
        ELIGIBILITY_NAMES.get(code, f"Eligibility code {code}")
        for code in eligibility_codes
    ]
    instrument_codes = unique(values.get("FundingInstrumentType") or [])
    instruments = [
        INSTRUMENT_NAMES.get(code, code) for code in instrument_codes
    ]
    disciplines = unique(
        DISCIPLINE_BY_CATEGORY[code]
        for code in category_codes
        if code in DISCIPLINE_BY_CATEGORY
    )
    topics = topic_areas(title, description, categories)

    close_field = (
        "EstimatedSynopsisCloseDate"
        if status == "forecasted"
        else "CloseDate"
    )
    post_field = (
        "EstimatedSynopsisPostDate"
        if status == "forecasted"
        else "PostDate"
    )
    source_url = safe_http_url(first(values, "AdditionalInformationURL"))
    cost_share_raw = clean_text(
        first(values, "CostSharingOrMatchingRequirement")
    )
    archive_date = iso_date(first(values, "ArchiveDate"))
    close_date = iso_date(first(values, close_field))
    if close_date:
        parsed_close = date.fromisoformat(close_date)
        if (parsed_close - as_of).days > MAX_REAL_CLOSE_DATE_DAYS:
            # Grants.gov uses dates such as 2076 and 2099 as open-ended
            # sentinels. They are lifecycle markers, not application
            # deadlines, and must never be shown or exported as real dates.
            close_date = None
    detail_page = (
        DETAIL_PAGE.format(opportunity_id=opportunity_id)
        if opportunity_id
        else GRANTS_HOME
    )
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
                "note": close_note,
                "estimated": status == "forecasted",
                "source": "Grants.gov XML extract",
                "source_url": detail_page,
                "source_field": close_field,
                "confidence": (
                    "official_estimate"
                    if status == "forecasted"
                    else "official_structured"
                ),
            }
        )

    return {
        "opportunity_id": opportunity_id,
        "opportunity_number": number,
        "title": title,
        "agency": clean_text(first(values, "AgencyName")),
        "agency_code": clean_text(first(values, "AgencyCode")),
        "status": status,
        "source": "Grants.gov",
        "source_type": "Federal",
        "detail_page": detail_page,
        "funding_opportunity_url": source_url,
        "primary_document_url": None,
        "primary_document_name": None,
        "primary_document_source": None,
        "primary_document_confidence": None,
        "detail_enrichment_status": "pending",
        "posted_date": iso_date(first(values, post_field)),
        "close_date": close_date,
        "close_date_note": close_note,
        "deadlines": deadlines,
        "deadline_source": "Grants.gov XML extract",
        "archive_date": archive_date,
        "status_verification_required": (
            not close_date
            and not archive_date
            and (
                status == "forecasted"
                or not bool(ROLLING_RE.search(text_blob))
            )
        ),
        "last_updated": iso_date(first(values, "LastUpdatedDate")),
        "estimated_award_date": iso_date(
            first(values, "EstimatedAwardDate")
        ),
        "estimated_project_start": iso_date(
            first(values, "EstimatedProjectStartDate")
        ),
        "fiscal_year": clean_text(first(values, "FiscalYear")),
        "version": clean_text(first(values, "Version")),
        "rolling": bool(ROLLING_RE.search(text_blob)),
        "opportunity_category": OPPORTUNITY_CATEGORY_NAMES.get(
            first(values, "OpportunityCategory"),
            first(values, "OpportunityCategory"),
        ),
        "funding_category_codes": category_codes,
        "funding_categories": categories,
        "funding_instrument_codes": instrument_codes,
        "funding_instruments": instruments,
        "eligibility_codes": eligibility_codes,
        "applicant_types": applicant_types,
        "eligibility_text": eligibility_text,
        "disciplines": disciplines,
        "topic_areas": topics,
        "aln": unique(values.get("CFDANumbers") or []),
        "award_floor": numeric(first(values, "AwardFloor")),
        "award_ceiling": numeric(first(values, "AwardCeiling")),
        "total_program_funding": numeric(
            first(values, "EstimatedTotalProgramFunding")
        ),
        "expected_number_of_awards": numeric(
            first(values, "ExpectedNumberOfAwards")
        ),
        "award_source": "Grants.gov XML extract",
        "cost_share_required": (
            None
            if not cost_share_raw
            else cost_share_raw.casefold() in {"yes", "true", "y"}
        ),
        "contacts": [],
        "has_preliminary_stage": bool(PRELIMINARY_RE.search(text_blob)),
        "preliminary_stage_type": (
            PRELIMINARY_RE.search(text_blob).group(1)
            if PRELIMINARY_RE.search(text_blob)
            else None
        ),
        "limited_submission": bool(
            LIMITED_SUBMISSION_RE.search(text_blob)
        ),
        "career_stage_signal": (
            EARLY_CAREER_RE.search(text_blob).group(1)
            if EARLY_CAREER_RE.search(text_blob)
            else None
        ),
        "description": (description or "")[:12000] or None,
    }


def iter_catalog_records(xml_stream, as_of):
    root = None
    record_tags = {
        "OpportunitySynopsisDetail_1_0",
        "OpportunityForecastDetail_1_0",
    }
    for event, element in iterparse(xml_stream, events=("start", "end")):
        if root is None:
            root = element
        tag = element.tag.rsplit("}", 1)[-1]
        if event == "end" and tag in record_tags:
            record = normalize_element(element, as_of)
            if record:
                yield record
            element.clear()
            root.clear()


def record_identity(record):
    from scripts.solicitation_identity import research_solicitation_key

    scoped = research_solicitation_key(record)
    if scoped:
        return f"solicitation:{scoped[0]}:{scoped[1]}"
    number = re.sub(
        r"\s+", "", str(record.get("opportunity_number") or "")
    ).casefold()
    if number:
        return f"number:{number}"
    return f"id:{record.get('opportunity_id')}"


def record_rank(record):
    return (
        1 if record.get("status") == "posted" else 0,
        record.get("last_updated") or "",
        record.get("version") or "",
    )


def read_archive(archive_path, as_of):
    with ZipFile(archive_path) as archive:
        xml_names = [
            name for name in archive.namelist() if name.lower().endswith(".xml")
        ]
        if len(xml_names) != 1:
            raise RuntimeError(
                f"Expected one XML file in {archive_path}, found {len(xml_names)}."
            )
        with archive.open(xml_names[0]) as xml_stream:
            records = list(iter_catalog_records(xml_stream, as_of))

    deduplicated = {}
    for record in records:
        key = record_identity(record)
        current = deduplicated.get(key)
        if current is None or record_rank(record) > record_rank(current):
            deduplicated[key] = record
    output = list(deduplicated.values())
    output.sort(
        key=lambda record: (
            record.get("close_date") or "9999-12-31",
            (record.get("title") or "").casefold(),
        )
    )
    return output, len(records) - len(output)


def normalize_token(token):
    token = token.casefold().strip(".-")
    if len(token) > 5 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 5 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 4 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def tokenize(value):
    normalized_value = unicodedata.normalize("NFKC", value or "").casefold()
    return [
        normalized
        for raw in TOKEN_RE.findall(normalized_value)
        if (normalized := normalize_token(raw))
        and normalized not in STOP_WORDS
        and len(normalized) > 1
    ]


def build_search_index(records):
    postings = defaultdict(list)
    document_lengths = []
    for document_id, record in enumerate(records):
        weighted_terms = Counter()
        fields = (
            (record.get("title"), 7),
            (record.get("opportunity_number"), 7),
            (record.get("agency"), 3),
            (" ".join(record.get("topic_areas") or []), 5),
            (" ".join(record.get("disciplines") or []), 4),
            (" ".join(record.get("funding_categories") or []), 3),
            (" ".join(record.get("funding_instruments") or []), 2),
            (" ".join(record.get("applicant_types") or []), 1),
            (record.get("eligibility_text"), 1),
            (record.get("description"), 1),
            # Phase 3 adds only compact, cited notice facts here. Raw notice
            # text is never placed in the browser catalog or search index.
            (record.get("document_search_text"), 1),
        )
        for value, weight in fields:
            for term, count in Counter(tokenize(value)).items():
                weighted_terms[term] += count * weight
        length = sum(weighted_terms.values()) or 1
        document_lengths.append(length)
        for term, term_frequency in weighted_terms.items():
            postings[term].extend((document_id, term_frequency))

    document_count = len(records)
    # Very common words add download weight and almost no ranking value.
    maximum_document_frequency = max(1, math.floor(document_count * 0.8))
    compact_postings = {
        term: values
        for term, values in sorted(postings.items())
        if len(values) // 2 <= maximum_document_frequency
    }
    return {
        "algorithm": "bm25",
        "document_count": document_count,
        "average_document_length": (
            round(sum(document_lengths) / document_count, 3)
            if document_count
            else 0
        ),
        "document_lengths": document_lengths,
        "postings": compact_postings,
    }


def facet_counts(records):
    fields = {
        "status": "status",
        "source_type": "source_type",
        "source": "source_facet",
        "agency": "agency",
        "discipline": "disciplines",
        "topic": "topic_areas",
        "eligibility": "applicant_types",
        "funding_instrument": "funding_instruments",
        "funding_category": "funding_categories",
    }
    result = {}
    for facet_name, record_field in fields.items():
        counts = Counter()
        for record in records:
            value = (
                source_facet_value(record)
                if facet_name == "source"
                else record.get(record_field)
            )
            if isinstance(value, list):
                counts.update(value)
            elif value:
                counts[value] += 1
        result[facet_name] = dict(
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )
    return result


def quality_metrics(records):
    def count(predicate):
        return sum(1 for record in records if predicate(record))

    return {
        "close_date_count": count(
            lambda record: record.get("close_date")
        ),
        "status_verification_count": count(
            lambda record: record.get("status_verification_required")
        ),
        "per_award_amount_count": count(
            lambda record: (
                record.get("award_floor")
                or record.get("award_ceiling")
            )
        ),
        "program_total_only_count": count(
            lambda record: (
                not record.get("award_floor")
                and not record.get("award_ceiling")
                and record.get("total_program_funding")
            )
        ),
        "any_amount_count": count(
            lambda record: (
                record.get("award_floor")
                or record.get("award_ceiling")
                or record.get("total_program_funding")
            )
        ),
        "agency_notice_count": count(
            lambda record: record.get("funding_opportunity_url")
        ),
        "preliminary_stage_count": count(
            lambda record: record.get("has_preliminary_stage")
        ),
    }


def build_catalog(records, generated_at, source_file, deduplicated_count):
    records = [normalize_record_facets(dict(record)) for record in records]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "source": {
            "name": "Grants.gov",
            "url": GRANTS_HOME,
            "extract_page": EXTRACT_PAGE,
            "extract_file": source_file,
        },
        "generated_at": iso_utc(generated_at),
        "record_count": len(records),
        "status_counts": dict(
            sorted(Counter(record["status"] for record in records).items())
        ),
        "diagnostics": {
            "deduplicated_count": deduplicated_count,
            "quality": quality_metrics(records),
        },
        "facets": facet_counts(records),
        "opportunities": records,
        "search_index": build_search_index(records),
    }


def compact_catalog_payload(catalog):
    """Remove deadline evidence duplicated elsewhere in the same record.

    ``document_evidence.facts`` is the authoritative citation store. Deadlines
    already point back to those facts with ``evidence_id`` or
    ``document_evidence_id``, so the public asset does not need another full
    citation object. A deadline note that exactly repeats the citation quote is
    similarly redundant. Direct citations and distinct notes remain intact.
    """
    output = deepcopy(catalog)
    for record in output.get("opportunities") or []:
        facts = {
            str(fact.get("id")): fact
            for fact in (
                (record.get("document_evidence") or {}).get("facts") or []
            )
            if isinstance(fact, dict) and fact.get("id")
        }
        for deadline in record.get("deadlines") or []:
            if not isinstance(deadline, dict):
                continue
            citation = deadline.get("citation") or {}
            if deadline.get("note") and deadline.get("note") == citation.get("quote"):
                deadline.pop("note", None)
            evidence_ref = str(
                deadline.get("evidence_id")
                or deadline.get("document_evidence_id")
                or ""
            )
            fact = facts.get(evidence_ref) or {}
            if citation and citation == fact.get("citation"):
                deadline.pop("citation", None)
    return output


def catalog_pipeline_timestamp(catalog):
    """Return the latest completed catalog-stage timestamp in UTC."""
    values = [
        catalog.get("generated_at"),
        catalog.get("detail_enrichment_generated_at"),
        catalog.get("document_evidence_generated_at"),
        catalog.get("catalog_audit_generated_at"),
        catalog.get("link_health_generated_at"),
        ((catalog.get("diagnostics") or {}).get("additional_sources") or {}).get(
            "merged_at"
        ),
    ]
    parsed = []
    for value in values:
        if not value:
            continue
        try:
            timestamp = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        parsed.append(timestamp.astimezone(timezone.utc))
    if not parsed:
        raise ValueError("catalog has no valid generated timestamp")
    return max(parsed)


def catalog_asset_version(catalog):
    """Return the single cache identity used by catalog browser assets."""
    return catalog_pipeline_timestamp(catalog).strftime(
        "catalog-%Y%m%dT%H%M%S%fZ"
    )


def catalog_release_identity(catalog, asset_version=None):
    """Build a bounded identity browsers can recompute after script load."""
    asset_version = asset_version or catalog_asset_version(catalog)
    status = ",".join(
        f"{key}={int(value)}"
        for key, value in sorted((catalog.get("status_counts") or {}).items())
    )
    index = catalog.get("search_index") or {}
    return (
        f"catalog-v{int(catalog.get('schema_version') or 0)}:"
        f"{asset_version}:records={int(catalog.get('record_count') or 0)}:"
        f"documents={int(index.get('document_count') or 0)}:"
        f"terms={len(index.get('postings') or {})}:status={status}"
    )


def catalog_metadata(catalog, catalog_filename="opportunities.js"):
    """Build the small startup sidecar paired with one catalog generation."""
    asset_version = catalog_asset_version(catalog)
    return {
        "schema_version": CATALOG_METADATA_SCHEMA_VERSION,
        "catalog_schema_version": catalog.get("schema_version"),
        "generated_at": catalog.get("generated_at"),
        "pipeline_generated_at": iso_utc(catalog_pipeline_timestamp(catalog)),
        "record_count": catalog.get("record_count"),
        "status_counts": dict(sorted(
            (catalog.get("status_counts") or {}).items()
        )),
        "asset_version": asset_version,
        "catalog_url": (
            f"./data/{catalog_filename}?v={asset_version}"
        ),
        "release_identity": catalog_release_identity(
            catalog, asset_version
        ),
    }


def catalog_javascript_bytes(catalog):
    payload = json.dumps(
        compact_catalog_payload(catalog),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).replace("</", "<\\/")
    return (
        "/* Generated by scripts/build_catalog.py. "
        "Do not edit by hand. */\n"
        f"globalThis.{CATALOG_GLOBAL}={payload};\n"
    ).encode("utf-8")


def catalog_metadata_javascript_bytes(catalog, catalog_filename="opportunities.js"):
    payload = json.dumps(
        catalog_metadata(catalog, catalog_filename),
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return (
        "/* Generated with data/opportunities.js. Do not edit by hand. */\n"
        f"globalThis.{CATALOG_METADATA_GLOBAL}={payload};\n"
    ).encode("utf-8")


def write_catalog(catalog, output_path, metadata_path=None):
    """Stage and replace the full catalog and its bounded metadata sidecar."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_path or output_path.with_name(
        CATALOG_METADATA_FILENAME
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts = (
        (output_path, catalog_javascript_bytes(catalog)),
        (
            metadata_path,
            catalog_metadata_javascript_bytes(catalog, output_path.name),
        ),
    )
    temporary_paths = []
    try:
        for target, payload in artifacts:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.stem}-",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                temporary_paths.append((temporary, target))
                output.write(payload)
        for temporary, target in temporary_paths:
            temporary.replace(target)
    finally:
        for temporary, _target in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def discover_latest_extract(html, base_url=EXTRACT_PAGE):
    candidates = re.findall(
        r"""(?:href=["']([^"']*GrantsDBExtract(\d{8})v2\.zip)["']|"""
        r"""(https?://[^\s"'<>]*GrantsDBExtract(\d{8})v2\.zip))""",
        html,
        flags=re.I,
    )
    normalized = []
    for href_match, href_date, absolute_match, absolute_date in candidates:
        href = href_match or absolute_match
        extract_date = href_date or absolute_date
        normalized.append((extract_date, urljoin(base_url, unescape(href))))
    if not normalized:
        raise RuntimeError("No enhanced Grants.gov XML extract link was found.")
    return max(normalized)[1]


def download_latest_extract(target_path):
    headers = {"User-Agent": USER_AGENT}
    page_response = requests.get(
        EXTRACT_PAGE, headers=headers, timeout=60
    )
    page_response.raise_for_status()
    extract_url = discover_latest_extract(page_response.text)
    with requests.get(
        extract_url, headers=headers, timeout=(30, 600), stream=True
    ) as response:
        response.raise_for_status()
        with target_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
    return extract_url


def validate_catalog(records, minimum, maximum):
    count = len(records)
    if count < minimum:
        raise RuntimeError(
            f"Implausible catalog: {count} records is below minimum {minimum}."
        )
    if count > maximum:
        raise RuntimeError(
            f"Implausible catalog: {count} records exceeds maximum {maximum}."
        )
    if len({record_identity(record) for record in records}) != count:
        raise RuntimeError("Implausible catalog: duplicate identities remain.")
    missing = [
        record for record in records
        if not record.get("title") or not record.get("agency")
    ]
    if len(missing) > max(5, math.ceil(count * 0.01)):
        raise RuntimeError(
            f"Implausible catalog: {len(missing)} records lack title or agency."
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the searchable Grants.gov opportunity catalog."
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use an existing Grants.gov XML extract ZIP instead of downloading.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/opportunities.js"),
        help="Generated JavaScript asset (default: data/opportunities.js).",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="Catalog date in YYYY-MM-DD form (default: today UTC).",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=1000,
        help="Fail below this current-record count (default: 1000).",
    )
    parser.add_argument(
        "--max-record-count",
        type=int,
        default=5000,
        help="Fail above this current-record count (default: 5000).",
    )
    args = parser.parse_args(argv)
    if args.min_records < 1:
        parser.error("--min-records must be at least 1")
    if args.max_record_count < args.min_records:
        parser.error("--max-record-count must be at least --min-records")
    return args


def main(argv=None):
    args = parse_args(argv)
    generated_at = utc_now()
    as_of = args.as_of or generated_at.date()

    if args.archive:
        archive_path = args.archive
        source_file = archive_path.name
        records, deduplicated = read_archive(archive_path, as_of)
    else:
        with tempfile.TemporaryDirectory(prefix="grant-catalog-") as directory:
            archive_path = Path(directory) / "grants-db-extract.zip"
            extract_url = download_latest_extract(archive_path)
            source_file = extract_url.rsplit("/", 1)[-1]
            records, deduplicated = read_archive(archive_path, as_of)

    validate_catalog(records, args.min_records, args.max_record_count)
    catalog = build_catalog(
        records, generated_at, source_file, deduplicated
    )
    write_catalog(catalog, args.output)
    index_terms = len(catalog["search_index"]["postings"])
    status_counts = catalog["status_counts"]
    print(f"Source:      {source_file}")
    print(f"As of:       {as_of.isoformat()}")
    print(f"Published:   {len(records)}")
    print(f"Posted:      {status_counts.get('posted', 0)}")
    print(f"Forecasted:  {status_counts.get('forecasted', 0)}")
    print(f"Index terms: {index_terms}")
    print(f"Wrote:       {args.output}")


if __name__ == "__main__":
    main()
