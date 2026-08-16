"""Subtopic cache: record construction, diff-stable I/O, and the backfill gate.

Three jobs, and deliberately no fourth:

1. Turn accepted :class:`~scripts.subtopic_segmentation.Subtopic` spans into
   §5.1 catalog records.
2. Read and write ``data/subtopic_records.json`` with the §5.4 serialization
   that keeps a daily commit small.
3. Answer :func:`needs_subtopic_extraction`, which is what makes the ~1,400
   already-cached documents get subtopics at all (§8.3).

Identity matching (``match_subtopics``, ``normalize_code``,
``title_fingerprint``) and term maps (``build_term_map``) already live in
``subtopic_segmentation`` -- they landed there during package B because they
are pure functions over spans and subtopic dicts with no cache involvement.
This module imports them rather than restating them. §18.1 lists them under
C1; that is a bookkeeping difference, not a design one.

Nothing here imports ``extract_document_evidence``: that module imports *this*
one at a flag-guarded call site, and the dependency runs one way only.

See docs/TOPIC_LAYER_PLAN.md §5.1, §5.4, §8.3.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from scripts.subtopic_segmentation import extractor_version, match_subtopics


CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE = Path("data/subtopic_records.json")

# Fields whose change means the record genuinely moved. `last_verified` is
# excluded on purpose -- see `_content_key`.
VOLATILE_FIELDS = ("last_verified",)


def needs_subtopic_extraction(entry, *, enabled, extractor_version):
    """True when a cached entry has no usable subtopic result for this extractor.

    Backfill and version-bump reprocessing both route through here. Without it
    the three §4 skip gates mean only documents that happen to change get
    segmented, and the ~1,400 already-cached documents never do -- the feature
    appears to work on a handful of records and silently never backfills.
    """
    if not enabled:
        return False
    if entry is None:
        return False                      # a full extraction is already happening
    if "subtopics" not in entry:
        return True                       # never attempted
    if entry.get("subtopic_extractor_version") != extractor_version:
        return True                       # toolchain or pattern set moved (§6.1)
    return False


def subtopic_id_for(parent_opportunity_number, subtopic_code_norm):
    return f"{parent_opportunity_number}:{subtopic_code_norm}"


def build_records(
    parent,
    result,
    *,
    document=None,
    as_of=None,
):
    """§5.1 records for one parent, from an accepted SegmentationResult.

    Fields inherited from the parent (§5.5) -- agency, instrument, eligibility,
    award range, the deadline used for filtering -- are deliberately NOT copied
    here. The merge in package E attaches them; duplicating them would put two
    copies of the same fact in the catalog and let them disagree.
    """
    document = document or {}
    parent_number = (
        parent.get("opportunity_number")
        or parent.get("opportunity_id")
        or ""
    )
    parent_id = str(parent.get("opportunity_id") or parent_number)
    version = (result.diagnostics or {}).get("extractor_version") or extractor_version()

    records = []
    for subtopic in result.subtopics:
        identifier = subtopic_id_for(parent_number, subtopic.subtopic_code_norm)
        records.append(
            {
                "record_type": "subtopic",
                "subtopic_id": identifier,
                # The browser derives identity from opportunity_id ||
                # opportunity_number (assets/app.js recordId), so a child with
                # neither is invisible to half the system.
                "opportunity_id": identifier,
                "parent_id": parent_id,
                "parent_opportunity_number": parent_number,
                "subtopic_code": subtopic.subtopic_code,
                "subtopic_code_norm": subtopic.subtopic_code_norm,
                "subtopic_ordinal": subtopic.subtopic_ordinal,
                "ordinal_label": subtopic.ordinal_label,
                "title": subtopic.title,
                "title_fingerprint": subtopic.title_fingerprint,
                "summary": subtopic.summary,
                "subtopic_terms": dict(subtopic.subtopic_terms),
                "subtopic_source": "inline",
                # The catalog's own vocabulary, never a private one:
                # currentness.record_is_current accepts only posted/forecasted,
                # so a child emitting anything else is filtered out of every
                # feed and every browser view as invalid_status.
                "status": parent.get("status"),
                "topic_areas": list(subtopic.topic_areas),
                "program_area_labels": list(subtopic.program_area_labels),
                "page_start": subtopic.page_start,
                "page_end": subtopic.page_end,
                "evidence_anchor": subtopic.anchor
                or (f"p{subtopic.page_start}" if subtopic.page_start else None),
                "source_document_url": document.get("url"),
                "source_document_hash": document.get("sha256"),
                "segmentation_method": result.method,
                "confidence": result.confidence,
                "pattern_family": result.family,
                "own_deadline": subtopic.own_deadline,
                "own_deadline_is_advisory": True,
                "first_seen": as_of,
                "last_verified": as_of,
                "extractor_version": version,
            }
        )
    return records


def _content_key(record):
    """Everything except the volatile fields, for change detection (§5.4)."""
    return {
        key: value
        for key, value in record.items()
        if key not in VOLATILE_FIELDS and key != "first_seen"
    }


def upsert_parent(cache, parent_id, records, *, as_of, reason=None, method=None):
    """Merge one parent's subtopics into the cache. Returns True if it changed.

    `subtopic_id` and `first_seen` are assigned once at first sight and carried
    forward through title-first matching, so identity survives renumbering,
    retitling and repagination (§5.3). `last_verified` moves **only** when
    something else did -- otherwise the timestamp alone rewrites the file every
    night and the repository grows for no reason (§5.4).
    """
    entries = cache.setdefault("records", {})
    previous = entries.get(parent_id) or {}
    old_records = list(previous.get("subtopics") or [])

    merged, changed = [], False
    for before, after in match_subtopics(old_records, list(records)):
        if after is None:
            changed = True                     # removed
            continue
        if before is None:
            merged.append(after)               # added
            changed = True
            continue
        carried = dict(after)
        carried["subtopic_id"] = before.get("subtopic_id", after["subtopic_id"])
        carried["opportunity_id"] = carried["subtopic_id"]
        carried["first_seen"] = before.get("first_seen") or after.get("first_seen")
        if _content_key(before) == _content_key(carried):
            carried["last_verified"] = before.get("last_verified")
        else:
            changed = True
        merged.append(carried)

    merged.sort(key=lambda item: (item.get("subtopic_ordinal") or 0,
                                  item.get("subtopic_code_norm") or ""))

    entry = {
        "subtopics": merged,
        "subtopic_count": len(merged),
        "segmentation_method": method,
        "subtopic_extractor_version": extractor_version(),
    }
    if reason:
        entry["subtopic_reason"] = reason

    if previous.get("subtopics") is None and not merged and not reason:
        # Nothing to record and nothing was there before.
        return False

    unchanged = (
        previous
        and previous.get("subtopic_reason") == entry.get("subtopic_reason")
        and previous.get("segmentation_method") == entry.get("segmentation_method")
        and previous.get("subtopic_extractor_version")
        == entry.get("subtopic_extractor_version")
        and not changed
    )
    if unchanged:
        return False

    entries[parent_id] = entry
    return True


def empty_cache():
    return {"schema_version": CACHE_SCHEMA_VERSION, "records": {}}


def read_cache(path=DEFAULT_CACHE):
    path = Path(path)
    if not path.exists():
        return empty_cache()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return empty_cache()
    if not isinstance(payload, dict):
        return empty_cache()
    payload.setdefault("schema_version", CACHE_SCHEMA_VERSION)
    payload.setdefault("records", {})
    return payload


def write_cache(cache, path=DEFAULT_CACHE):
    """Write with the §5.4 serialization.

    This file's style deliberately differs from every other file in data/. The
    existing caches are minified; this one is indented and key-sorted because
    it is the only committed artifact whose *line-level* diff a human reads
    when triaging a phantom-amendment flood. A minified 20,000-record file
    produces a one-line diff that tells you nothing.

    Records are sorted by (parent_opportunity_number, subtopic_ordinal), and
    written through a temp file with newline="\\n" so the bytes are LF on every
    platform -- matching how write_catalog and write_cache already behave in
    extract_document_evidence.
    """
    path = Path(path)
    payload = {
        "schema_version": cache.get("schema_version", CACHE_SCHEMA_VERSION),
        "records": {
            parent: {
                **entry,
                "subtopics": sorted(
                    entry.get("subtopics") or [],
                    key=lambda item: (
                        item.get("parent_opportunity_number") or "",
                        item.get("subtopic_ordinal") or 0,
                        item.get("subtopic_code_norm") or "",
                    ),
                ),
            }
            for parent, entry in sorted((cache.get("records") or {}).items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, sort_keys=True, indent=1, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def cache_metrics(cache):
    """Counts for the §8.3 insertion-4 diagnostics block."""
    entries = (cache.get("records") or {}).values()
    subtopic_count = sum(len(entry.get("subtopics") or []) for entry in entries)
    reasons = {}
    methods = {}
    confidences = {}
    for entry in entries:
        reason = entry.get("subtopic_reason")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        method = entry.get("segmentation_method")
        if method:
            methods[method] = methods.get(method, 0) + 1
        for record in entry.get("subtopics") or []:
            level = record.get("confidence")
            if level:
                confidences[level] = confidences.get(level, 0) + 1
    return {
        "subtopic_parent_count": sum(
            1 for entry in entries if entry.get("subtopics")
        ),
        "subtopic_record_count": subtopic_count,
        "subtopic_rejection_reasons": dict(sorted(reasons.items())),
        "subtopic_methods": dict(sorted(methods.items())),
        "subtopic_confidence_counts": dict(sorted(confidences.items())),
    }
