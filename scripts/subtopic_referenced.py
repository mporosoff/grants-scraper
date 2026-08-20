"""Referenced subtopic sources — P6.3, and today exactly one of them.

**What a referenced source is (§5.1, §6.7).** A solicitation that *delegates* its
list of fundable subdivisions to a stable external page the agency maintains. The
parent→child relationship is established by the **notice pointing at that page**, not
by this project inferring anything, and not by the agency publishing the relationship
as data. So the rung is `referenced` — never `native`, and never `inferred`.

**Why there is one source here and not a DoD router.** MEAS-7 measured the two
outward-pointing DoD category-(a) records in the catalog and found exactly one real
hierarchy (`docs/DOD_MEAS7_INSPECTION.md`). ONR's "technology areas" are an
alphabetical research-interest list that names neither its BAA nor any way to apply
against an area, so it is organizational taxonomy and is deliberately absent from this
module. **Do not add an agency here without the same measurement.**

**The Army TDAC contract, measured 2026-08-22 and re-measured before shipping.**
`W911NF-23-S-0003`'s notice says, in its own words, that DAC publishes its current
research topics at `army.mil/article/261533` and that *"a change to the DAC BAA topics
website is not an amendment to this BAA"*. The page:

* names `W911NF-23-S-0003` in its own lead — so the parent is asserted by the source,
  never guessed;
* prints each topic as `Title:` / `Announcement ID:` / `TPOC:`;
* publishes a compact 13-topic **index** followed by 14 fuller **entries**, so an
  `Announcement ID` occurs up to twice and the richer occurrence carries the topic's
  description. Dedup is by **`Announcement ID`**, keeping the richer block — never by
  title (§P6.3.2).

**First refusal, and declining is normal.** `first_refusal()` answers only for the one
parent it knows, only when the page still names that BAA number, and only when the
result clears the health floor. Every other case returns `None`, which leaves the
generic path exactly as it was: a referenced source that cannot answer must never
suppress the answer something else could give (§6.7·0, §7.4).
"""

from __future__ import annotations

import re

# --- the measured source contract -------------------------------------------
#: The one parent this module serves. Compared normalised, because Grants.gov and
#: the Army page differ only in punctuation across their many renderings.
ARMY_TDAC_BAA_NUMBER = "W911NF-23-S-0003"

#: The page the notice names. Recorded here as the measured default; the caller
#: supplies the fetcher, so nothing in this module reaches the network by itself.
ARMY_TDAC_TOPICS_URL = "https://www.army.mil/article/261533"

#: Measured 2026-08-22: 14 unique Announcement IDs.
ARMY_TDAC_MEASURED_TOPICS = 14
#: Conservative floor, well below the measured count. It exists to catch a
#: collapsed parse or a gutted page, not to pin the Army's topic list -- topics are
#: expected to come and go, and the notice says so explicitly.
ARMY_TDAC_MIN_TOPICS = 8

_TAG = re.compile(r"<[^>]+>")
_TITLE_BLOCK = re.compile(r"<p><strong>\s*Title:", re.IGNORECASE)
_TITLE_TEXT = re.compile(r"Title:\s*(.+?)\s*(?:Announcement ID|$)", re.IGNORECASE | re.DOTALL)
_ANNOUNCEMENT_ID = re.compile(r"Announcement ID:\s*([A-Z][A-Z0-9]{1,7}\s+BAA-\d{1,4})", re.IGNORECASE)
_TPOC = re.compile(r"TPOC:\s*([^\s<][^<]{0,120}?)\s*(?:Title:|$)", re.IGNORECASE)
_MAILTO = re.compile(r'href="mailto:([^"]+)"', re.IGNORECASE)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", fragment or "")).strip()


def normalise_solicitation_number(value) -> str:
    """Upper-cased alphanumerics only, so `W911NF-23-S-0003` == `W911NF23S0003`."""
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def normalise_announcement_id(value) -> str:
    """`TDAC BAA-001` -> `tdac-baa-001`. The child's stable key."""
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


def page_names_parent(html: str, baa_number: str = ARMY_TDAC_BAA_NUMBER) -> bool:
    """Does the page assert the parent itself? If not, this module declines.

    This is the single most important check in the file. Without it the module
    would be attaching topics to a parent by assumption, which is precisely what
    P6.3.2 forbids.
    """
    return normalise_solicitation_number(baa_number) in normalise_solicitation_number(
        _text(html)
    )


def parse_army_tdac(html: str) -> list[dict]:
    """Every `Title:` / `Announcement ID:` / `TPOC:` topic, deduped by id.

    Returns topics in first-appearance order. For an id that appears twice -- the
    index and then the full entry -- the **longer** block wins, because that is the
    one carrying the topic's description.
    """
    starts = [match.start() for match in _TITLE_BLOCK.finditer(html or "")]
    if not starts:
        return []
    bounds = list(zip(starts, starts[1:] + [len(html)]))

    best: dict = {}
    order: list = []
    for start, end in bounds:
        block = html[start:end]
        flat = _text(block)
        id_match = _ANNOUNCEMENT_ID.search(flat)
        title_match = _TITLE_TEXT.search(flat)
        if not id_match or not title_match:
            # A block without both is not a topic. Never guessed at.
            continue
        announcement_id = re.sub(r"\s+", " ", id_match.group(1)).upper()
        key = normalise_announcement_id(announcement_id)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        if not key or not title:
            continue
        tpoc_match = _MAILTO.search(block) or _TPOC.search(flat)
        topic = {
            "announcement_id": announcement_id,
            "announcement_id_norm": key,
            "title": title,
            "tpoc": (tpoc_match.group(1).strip() if tpoc_match else None),
            # The topic's own prose, which is what the term map is built from.
            "detail_text": flat,
            "block_length": len(block),
        }
        if key not in best:
            order.append(key)
            best[key] = topic
        elif topic["block_length"] > best[key]["block_length"]:
            best[key] = topic
    return [best[key] for key in order]


def check_health(html: str, topics: list[dict], *,
                 baa_number: str = ARMY_TDAC_BAA_NUMBER,
                 minimum: int = ARMY_TDAC_MIN_TOPICS) -> dict:
    """Conservative, and every failure means *decline*, never *publish zero*.

    Ordered by what each check protects:

    1. **Parent assertion.** The page must still name the BAA. Losing this means we
       no longer know these topics belong to this parent (§P6.3.5).
    2. **Topic floor.** Measured 14; the floor is 8. A zero-row HTTP 200 and a
       catastrophic shrinkage both land here.
    3. **Identifier validity.** Every accepted topic must carry a parseable
       `Announcement ID`, because that is the child key.
    """
    failures = []
    if not page_names_parent(html, baa_number):
        failures.append(f"parent assertion: page no longer names {baa_number}")
    if len(topics) < minimum:
        failures.append(
            f"topic floor: parsed {len(topics)}, floor {minimum} "
            f"(measured {ARMY_TDAC_MEASURED_TOPICS})"
        )
    unkeyed = [t for t in topics if not t.get("announcement_id_norm")]
    if unkeyed:
        failures.append(f"identifier: {len(unkeyed)} topics without an Announcement ID")
    return {
        "healthy": not failures,
        "failures": failures,
        "topics": len(topics),
        "measured": ARMY_TDAC_MEASURED_TOPICS,
        "floor": minimum,
        "names_parent": page_names_parent(html, baa_number),
    }


def applies_to(record, baa_number: str = ARMY_TDAC_BAA_NUMBER) -> bool:
    """Is this the one catalog parent the source serves? Deterministic, no fuzz."""
    return normalise_solicitation_number(
        (record or {}).get("opportunity_number")
    ) == normalise_solicitation_number(baa_number)


def build_result(topics, *, url=ARMY_TDAC_TOPICS_URL):
    """Turn measured topics into a `SegmentationResult` of `referenced` children.

    Imports are function-local for the same reason the call site's are: with
    `--enable-subtopics` off, nothing under `scripts.subtopic_*` is imported at all
    (§8.3). `page_start`/`page_end` stay `None` and the anchor is the source URL,
    which is exactly §6.7's `inline` vs `referenced` field table.

    **`method` and `family` are None on purpose.** No segmentation layer and no
    pattern family produced these; provenance and method stay orthogonal (§5.1), and
    claiming a method here would be inventing a mechanism that did not run.
    """
    from scripts.subtopic_segmentation import (
        SegmentationResult,
        Subtopic,
        build_term_map,
        extractor_version,
        title_fingerprint,
    )

    subtopics = []
    for ordinal, topic in enumerate(topics, start=1):
        from scripts.subtopic_segmentation import summarize

        summary = summarize(topic["detail_text"])
        subtopics.append(
            Subtopic(
                subtopic_code=topic["announcement_id"],
                subtopic_code_norm=topic["announcement_id_norm"],
                subtopic_ordinal=ordinal,
                ordinal_label=topic["announcement_id"],
                title=topic["title"],
                title_fingerprint=title_fingerprint(topic["title"]),
                summary=summary,
                subtopic_terms=build_term_map(
                    f"{topic['title']} {topic['detail_text']}"
                ),
                page_start=None,
                page_end=None,
                anchor=url,
                char_start=0,
                char_end=len(topic["detail_text"]),
                program_area_labels=(),
                topic_areas=(),
                own_deadline=None,
            )
        )
    return SegmentationResult(
        subtopics=tuple(subtopics),
        method=None,
        confidence="high",
        family=None,
        reason=None,
        diagnostics={
            "referenced_source": "army-tdac",
            "source_url": url,
            "extractor_version": extractor_version(),
        },
    )


def first_refusal(record, *, fetch, url=ARMY_TDAC_TOPICS_URL,
                  baa_number=ARMY_TDAC_BAA_NUMBER):
    """Offer the referenced answer for this parent, or decline.

    Returns ``(result, document, diagnostics)`` when the source answers credibly and
    ``(None, None, diagnostics)`` in every other case -- not applicable, fetch
    failed, page stopped naming the parent, or health floor missed.

    **Declining is not publishing zero.** The caller falls through to the generic
    path unchanged, so an unhealthy referenced source can never cost a parent the
    children some other mechanism would have found (§6.7·0, §7.4).

    Never raises: a transport failure is a fact about the fetch path until the layer
    is isolated (§17.11), and it is reported in the diagnostics rather than thrown.
    """
    if not applies_to(record, baa_number):
        return None, None, {"referenced_source": None, "reason": "not_applicable"}

    diagnostics = {"referenced_source": "army-tdac", "source_url": url}
    try:
        html = fetch(url)
    except Exception as exc:  # noqa: BLE001 - §17.11: report the layer, do not throw
        diagnostics.update(reason=f"fetch_failed_{type(exc).__name__}", healthy=False)
        return None, None, diagnostics

    topics = parse_army_tdac(html)
    health = check_health(html, topics, baa_number=baa_number)
    diagnostics.update(health=health, topics=len(topics))
    if not health["healthy"]:
        diagnostics["reason"] = "unhealthy_declined"
        return None, None, diagnostics

    result = build_result(topics, url=url)
    document = {"url": url, "sha256": None, "name": "TDAC BAA Research Topics"}
    diagnostics["reason"] = "answered"
    return result, document, diagnostics
