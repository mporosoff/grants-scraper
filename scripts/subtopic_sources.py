"""Multi-attachment segmentation (§6.6).

A notice's topic list is not always in the file `source_for_record()` picks.
The census measured the scale of that assumption: **12 of 20 records carry more
than one attachment**, and NRL's 32 research topics with 25 per-topic contact
mailboxes live in `Amendment 0004.pdf` while the primary notice contains none
of them.

**This is a parallel path for subtopics only.** `source_for_record()` keeps its
single-source contract exactly, so administrative fact extraction --
deadlines, cost share, eligibility, program areas -- reads the same one
document it always has, from the same URL, and `document_evidence.json` is
unchanged. Nothing here runs unless `--enable-subtopics` is on, which is what
makes §0.5 flag-off parity hold by construction rather than by testing.

**Why the attachment list is fetched rather than read from the catalog.** It is
not stored anywhere: `document_urls` on a record holds agency web links from
`synopsisDocumentURLs`, not Grants.gov attachments, and only `attachment_count`
survives enrichment. Storing the list would mean changing `compact_detail` and
therefore changing `data/opportunity_enrichment.json` on the next nightly with
the flag off -- exactly what §0.5 forbids. Fetching it inside the flag guard
costs one API call per segmented document and changes nothing when off.

Two behaviours the census made non-negotiable (see docs/CORPUS_CENSUS.md):

1. **Dedup by content hash.** Seven secondaries carry a topic list and all seven
   are *revisions* of a document already segmented. `363065` alone would
   otherwise contribute the same list four times from four revisions.
2. **Rank by result quality, not attachment order.** `332894`'s 887 KB primary
   yields 113 extractable lines and matches a family three times inside prose;
   selecting the first thing that segments would let it win.
"""

from __future__ import annotations

import dataclasses
import hashlib
from urllib.parse import urlparse

from scripts.subtopic_segmentation import SegmentationResult, segment_document


# How many attachments to try per record, best-ranked first. A record with more
# than this many is carrying a template pack, not a topic list -- 363489 has ten
# attachments of which nine are proposal forms.
MAX_ATTACHMENTS = 6

# Confidence ordering for ranking results. Layer D's `low` never publishes, so a
# high-confidence result from any attachment beats a low one from the primary.
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

# Below this, an .html attachment is a redirect stub rather than a document.
# Measured (docs/COVERAGE_SURVEY.md stage 1): all 366 .html attachments in the
# catalog belong to NIH and split hard by size -- **255 are stubs under 1 KB**
# (the census's 355867 was 429 bytes) and **111 are complete announcements
# averaging ~145 KB** across 108 records. There is nothing between the two
# populations, so the threshold is not a tuned parameter; it sits in an empty
# gap two orders of magnitude wide. A stub must be filtered rather than parsed:
# parsed, it yields a container with no text and displaces nothing, but it
# still costs a fetch and lands in the diagnostics as a document that failed.
MIN_HTML_BYTES = 2048

# Names that are never worth a fetch. Deliberately short: this skips obvious
# proposal furniture, and anything not listed still gets tried and judged on its
# content. The census found no topic list in any of these shapes.
SKIP_TOKENS = (
    "cost_proposal", "cost proposal", "milestones_and_payments",
    "associate_contractor", "model_other_transaction", "privacy act",
    "security program questionnaire", "abstract_summary_side",
    "proposal_summary_slides", "sf-424", "sf424",
)


def _skippable(name):
    lowered = (name or "").casefold()
    return any(token in lowered for token in SKIP_TOKENS)


def _is_html_stub(name, size):
    """True for an .html attachment too small to be an announcement.

    §18.1 Cov2. Size is what separates the two NIH populations; the filename is
    identical in both (`PAR-25-210-Full-Announcement.html` is a 422-byte stub,
    and `RFA-RM-27-002-Full-Announcement.html` is 137 KB of announcement).
    """
    if not str(name or "").casefold().endswith((".html", ".htm")):
        return False
    if size is None:
        # `size_bytes` is not guaranteed by the API. Unknown size must mean
        # "not a stub": dropping an announcement because its metadata was
        # missing loses a real document, while fetching a stub costs one
        # request and is judged on its content anyway.
        return False
    try:
        return int(size) < MIN_HTML_BYTES
    except (TypeError, ValueError):
        return False


def subtopic_only_primary(record):
    """The first document to try for a record `source_for_record()` declines.

    §18.1 Cov1. `source_for_record()` returns ``None`` for **685 of 1,475
    catalog records -- 46.4%** -- and 672 of those have never been fetched even
    once (docs/COVERAGE_SURVEY.md). Two measured populations sit inside that
    number: **236 carry live Grants.gov attachments**, which
    :func:`attachment_sources` already reaches, and **221 carry an agency URL
    that is declined only because the record needs no gap-fill**. The second
    group is what this function is for.

    It is deliberately not a change to `source_for_record()`. That function
    answers *"which document may this record cite?"* -- a question where a
    wrong one-click link is worse than none -- and it must keep answering it
    the same way. This answers *"which bytes may segmentation read?"*, which
    publishes no link at all.
    """
    url = (record or {}).get("funding_opportunity_url")
    if not url:
        return None
    return {"url": url, "name": None, "kind": "subtopic_agency_notice"}


def attachment_sources(opportunity_id, *, detail_fetcher, collector):
    """Every Grants.gov attachment on a record, best candidates first.

    `detail_fetcher` and `collector` are injected so this module never imports
    the pull_grants network layer at module scope, and so tests can drive it
    without a network.
    """
    try:
        detail = detail_fetcher(str(opportunity_id))
    except Exception:                       # noqa: BLE001 - never break the parent
        return []
    data = detail.get("data", detail) if isinstance(detail, dict) else detail
    try:
        attachments = collector(data)
    except Exception:                       # noqa: BLE001
        return []

    sources = []
    for attachment in attachments:
        url = attachment.get("download_url")
        name = attachment.get("file_name") or ""
        size = attachment.get("size_bytes")
        if not url or _skippable(name) or _is_html_stub(name, size):
            continue
        sources.append({
            "url": url,
            "name": name,
            "id": attachment.get("id"),
            "size": size,
        })
    return sources[:MAX_ATTACHMENTS]


def _score(result):
    """Rank a segmentation result. Higher is better; None never wins."""
    if result is None or not result.subtopics:
        return (0, 0)
    return (CONFIDENCE_RANK.get(result.confidence, 0), len(result.subtopics))


def _announcement_url(record, primary_document):
    """The URL of the document this record's announcement *is*, or None.

    Two sources, in order, and both name a **document** rather than describing
    how :func:`best_segmentation` was called:

    1. `primary_document_url` -- what `select_primary_document` designated for
       this record, and the field `source_for_record` reads. It is the record's
       own answer to "which document is my announcement?".
    2. failing that, the primary document this run was actually handed. A record
       reached through the ordinary path has one even when enrichment stored no
       URL, and it is that run's announcement by construction.

    ``None`` means **the record has no announcement at all** -- neither
    designated nor supplied. That is the shape of the 685 records
    `source_for_record` declines, and it is the case §18.1 Cov6 is about.
    """
    designated = (record or {}).get("primary_document_url")
    if designated:
        return designated
    supplied = (primary_document or {}).get("url") or None
    if supplied:
        return supplied
    agency_url = (record or {}).get("funding_opportunity_url")
    return agency_url if _is_announcement_url(agency_url) else None


def _is_announcement_url(url):
    """Whether a URL identifies a notice rather than a generic portal.

    BUG-14's live case stores ``https://www.grants.gov/`` as the agency URL.
    Root, search and generic landing pages do not identify an announcement and
    therefore cannot make a Grants.gov-bound notice look secondary. The rule is
    intentionally host/path narrow; an actual agency page remains authoritative.
    """
    if not url:
        return False
    parsed = urlparse(str(url))
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "/").rstrip("/").casefold()
    if host in {"grants.gov", "www.grants.gov"}:
        if path in {"", "/", "/search-results", "/search"}:
            return False
    return True


def _attachment_source_kind(record, source, announcement_url):
    """Truthful source role without changing attachment ownership semantics."""
    if announcement_url:
        return (
            "primary_notice"
            if source.get("url") == announcement_url
            else "secondary_attachment"
        )
    number = "".join(
        char for char in str((record or {}).get("opportunity_number") or "").casefold()
        if char.isalnum()
    )
    name = "".join(
        char for char in str(source.get("name") or "").casefold()
        if char.isalnum()
    )
    notice_words = ("nofo", "fundopp", "announcement", "solicitation")
    if (number and number in name) or any(word in name for word in notice_words):
        return "authoritative_notice"
    # There is no identified announcement to which this can truthfully be
    # secondary. Grants.gov still establishes ownership for Cov4.
    return "attached_source"


def _is_secondary_to(document, announcement_url):
    """Is this document *secondary* to the record's own announcement?

    §18.1 Cov6, and this is the whole fix. **The test is whether the winning
    document is the record's own announcement -- not whether an argument was
    populated**, which is what the previous implementation asked and is why it
    was wrong.

    1. **A record with no announcement has nothing to be secondary to.** Its own
       Grants.gov attachments are then the best announcement material it has,
       and Grants.gov bound every one of them to this record -- the same binding
       Cov4's ownership guard relies on. Calling such a document "secondary"
       names a relationship that does not exist.
    2. **A record that does have one is secondary exactly when the winning
       document is a different file.** That is the measured risk, preserved
       unchanged: CDC `360339` and AFRL PACER `349554` both have an
       announcement and both win from another attachment, so both still demote.
    """
    if not announcement_url:
        return False
    return (document or {}).get("url") != announcement_url


def _demote(result, document=None, announcement_url=None):
    """Cap a genuinely-secondary result at `low`. See :func:`_is_secondary_to`.

    Measured, and still the only measurement available for the risk this
    protects against: exactly one census record segmented from a secondary
    attachment and its result was **wrong**. CDC `360339` yielded 17 spans from
    `DGHP FY26 M&E Indicator List` -- entries like `2.1. Point of Entry (POE)
    General Capacity` and `5.2. Laboratory Quality Control` -- which are
    monitoring-and-evaluation indicator categories, not the five fundable
    Components the record actually offers. **That record has since left the
    catalog**, so the 0-of-1 figure can no longer be re-run; it is retained as
    the reason for the rule rather than refreshed.

    §18.3's asymmetry is explicit about which way to err: a missing subtopic
    costs one search, a wrong one puts a plausible card with a page anchor in
    front of a PI. So the cap stays wherever the risk it was fitted to is
    present, and is **narrowed** -- not lifted -- where that risk is absent.

    **Measured effect of the narrowing (§18.1 Cov6, live 2026-08-27):** across a
    50-record sample of the 236 no-primary records carrying attachments, exactly
    one enumerates -- `363526`, whose own `NOFOAFRLAFOSR20260004 DEPSCoR-RC.pdf`
    yields 8 spans at method `toc`. Before: `low`. After: `medium`, which is the
    §5.1 `inferred` ceiling and is what `segment_document` earns on that
    document directly. **Neither value auto-publishes** (§7.1), so the narrowing
    buys a truthful confidence and correct ranking, not publication.

    Ranking is the substantive half. `_score` reads confidence, so when every
    candidate is flattened to `low` the comparison degenerates to span count and
    a wrong 17-span list beats a right 8-span one -- defeating the census's
    non-negotiable "rank by result quality, not attachment order" for exactly
    the population that has no primary to rank against.
    """
    if result is None or not result.subtopics or result.confidence == "low":
        return result
    if not _is_secondary_to(document, announcement_url):
        return result
    return dataclasses.replace(result, confidence="low")


def best_segmentation(
    record,
    primary_content,
    primary_document,
    *,
    extract_containers,
    download,
    detail_fetcher,
    collector,
    parent_deadline=None,
    run_budget=None,
):
    """Segment every attachment and return the best result and its document.

    Returns ``(result, document, diagnostics)``. The primary is always tried
    first and from bytes already in hand, so a record whose topics are in the
    primary costs no extra fetch at all.

    Never raises. Zero subtopics is a normal outcome (§9.3).
    """
    seen_hashes = set()
    attempts = []

    def consider(content, document, label):
        if not content:
            return None
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen_hashes:
            # A revision of something already segmented. The census found seven
            # such files and every one duplicated a list already counted.
            attempts.append({"source": label, "outcome": "duplicate_hash"})
            return None
        seen_hashes.add(digest)
        try:
            containers, _extraction = extract_containers(
                content,
                (document or {}).get("content_type"),
                (document or {}).get("name"),
                (document or {}).get("url"),
            )
            outcome = segment_document(
                record,
                content,
                containers,
                document,
                parent_deadline=parent_deadline,
                run_budget=run_budget,
            )
        except Exception:                   # noqa: BLE001 - try the next one
            attempts.append({"source": label, "outcome": "error"})
            return None
        attempts.append({
            "source": label,
            "outcome": outcome.reason or outcome.method,
            "subtopics": len(outcome.subtopics),
        })
        return outcome

    best_result = consider(primary_content, primary_document, "primary")
    best_document = primary_document if best_result else None
    if best_result is None:
        best_result = SegmentationResult.empty("no_layer_accepted")

    # A high-confidence primary is already the best available answer; spending
    # fetches to look for a better one is waste.
    if _score(best_result) >= (CONFIDENCE_RANK["high"], 1):
        return best_result, primary_document, {"attempts": tuple(attempts)}

    # §18.1 Cov6: resolved once, before the loop, so every attachment is
    # judged against the same answer to "which document is the announcement?".
    announcement = _announcement_url(record, primary_document)
    opportunity_id = record.get("opportunity_id") or record.get("opportunity_number")
    for source in attachment_sources(
        opportunity_id, detail_fetcher=detail_fetcher, collector=collector
    ):
        if run_budget is not None and run_budget.exhausted():
            attempts.append({"source": source["name"], "outcome": "run_budget"})
            break
        try:
            response = download(source["url"])
            content = response.get("content")
        except Exception:                   # noqa: BLE001 - a failed fetch is not fatal
            attempts.append({"source": source["name"], "outcome": "fetch_failed"})
            continue
        document = {
            "url": response.get("url") or source["url"],
            "name": source["name"],
            "content_type": response.get("content_type"),
            "sha256": hashlib.sha256(content).hexdigest() if content else None,
            "source_kind": _attachment_source_kind(
                record,
                {**source, "url": response.get("url") or source["url"]},
                announcement,
            ),
        }
        outcome = consider(content, document, source["name"])
        outcome = _demote(outcome, document, announcement)
        if _score(outcome) > _score(best_result):
            best_result, best_document = outcome, document

    return (
        best_result,
        best_document or primary_document,
        {"attempts": tuple(attempts)},
    )


def segment_without_primary(record, **kwargs):
    """:func:`best_segmentation` for a record that has no selected primary.

    §18.1 Cov1. `best_segmentation` already tolerates a missing primary -- it
    skips the empty content and goes straight to the attachment list -- so this
    is a name for the case rather than a second implementation. It exists so
    the call site reads as what it is, and so the behaviour has a test that
    fails if the tolerance is ever removed.
    """
    return best_segmentation(record, None, None, **kwargs)
