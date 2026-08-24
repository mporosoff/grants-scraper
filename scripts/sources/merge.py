"""Merge external-source records into the generated catalog with a safe lifecycle.

Design (addresses the source-lifecycle and currentness audit findings):

- **Atomic per-source replace.** Each source's published records are replaced
  wholesale on a successful refresh, so a changed deadline or a removed
  opportunity is reflected -- not left stale next to an old copy.
- **Configurable failure policy.** A committed snapshot cache
  (``data/source_records.json``) holds each source's last successful records.
  Most sources republish that snapshot when a refresh fails. Sources whose
  rows cannot be proven current can opt out and publish zero instead. (The
  daily ``build_catalog`` run rewrites the catalog from Grants.gov only, so
  this cache is what carries safe external records across days.)
- **Currentness + actionability gates.** Every external record must have an
  official URL and only plausible, non-expired dates; expired records are
  dropped even from a cached snapshot before publication.
- **Full post-merge validation** runs before anything is written.

Grants.gov always wins on conflicts, and the search index/facets are rebuilt
with Grants.gov's own functions so external records stay indistinguishable.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import tempfile

from scripts.build_catalog import (
    CATALOG_GLOBAL,
    build_search_index,
    facet_counts,
    iso_utc,
    normalize_record_facets,
    quality_metrics,
    record_identity,
    utc_now,
    validate_catalog,
    write_catalog,
)
from .registry import AdapterResult, collect
from .validate import filter_publishable, within_health_bounds
from .discoverability import augment_records

DEFAULT_CATALOG = Path("data/opportunities.js")
DEFAULT_CACHE = Path("data/source_records.json")
CACHE_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# Catalog file I/O (the file is `globalThis.GRANT_CATALOG=<json>;`)
# --------------------------------------------------------------------------
def load_catalog(path: Path = DEFAULT_CATALOG) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    marker = f"globalThis.{CATALOG_GLOBAL}="
    if marker not in text:
        raise ValueError(f"{path} is not a generated catalog (missing {marker!r}).")
    payload = text.split(marker, 1)[1].strip()
    payload = payload.rsplit(";", 1)[0].strip()
    return json.loads(payload)


def save_catalog(catalog: dict, path: Path = DEFAULT_CATALOG) -> None:
    write_catalog(catalog, Path(path))


# --------------------------------------------------------------------------
# Source snapshot cache (last-known-good records per source)
# --------------------------------------------------------------------------
def load_source_cache(path: Path = DEFAULT_CACHE) -> dict:
    path = Path(path)
    if not path.exists():
        return {"schema_version": CACHE_SCHEMA_VERSION, "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": CACHE_SCHEMA_VERSION, "sources": {}}
    if data.get("schema_version") != CACHE_SCHEMA_VERSION or not isinstance(
        data.get("sources"), dict
    ):
        return {"schema_version": CACHE_SCHEMA_VERSION, "sources": {}}
    return data


def save_source_cache(cache: dict, path: Path = DEFAULT_CACHE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cache, ensure_ascii=False, separators=(",", ":"), default=str)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.stem}-", suffix=".tmp", delete=False,
    ) as handle:
        temp = Path(handle.name)
        handle.write(payload)
        handle.write("\n")
    temp.replace(path)


# --------------------------------------------------------------------------
# Lifecycle: decide what each source publishes this run
# --------------------------------------------------------------------------
def _cached_publishable(sources: dict, slug: str, as_of: date) -> list[dict]:
    records = (sources.get(slug) or {}).get("records") or []
    kept, _ = filter_publishable(records, as_of)
    return kept


def _snapshot_age_days(sources: dict, slug: str, as_of: date) -> int | None:
    stamp = str((sources.get(slug) or {}).get("fetched_at") or "")[:10]
    if not stamp:
        return None
    try:
        return max(0, (as_of - date.fromisoformat(stamp)).days)
    except ValueError:
        return None


def _clear_failed_source(sources: dict, result: AdapterResult) -> None:
    """Remove an unsafe snapshot while retaining failure diagnostics."""
    sources[result.slug] = {
        "source": result.display_name,
        "source_type": result.source_type,
        "fetched_at": None,
        "record_count": 0,
        "diagnostics": result.diagnostics,
        "records": [],
    }


def resolve_live_records(results: list[AdapterResult], cache: dict,
                         as_of: date) -> tuple[list[dict], dict, list[dict]]:
    """Return ``(records_to_publish, updated_cache, per_source_summaries)``.

    Successful, healthy sources are refreshed (and their snapshot updated).
    Failed or unhealthy sources use their configured policy: retain a filtered
    last-known-good snapshot, or clear it and publish zero. Expired records are
    removed even from a retained snapshot.
    """
    sources = cache.setdefault("sources", {})
    live: list[dict] = []
    summaries: list[dict] = []

    for result in results:
        slug = result.slug
        if result.ok:
            kept, dropped = filter_publishable(result.records, as_of)
            healthy = within_health_bounds(
                len(kept), result.min_records, result.max_records
            )
            if healthy:
                previous_snapshot = sources.get(slug) or {}
                previous_records = {
                    record_identity(record): record
                    for record in (previous_snapshot.get("records") or [])
                }
                previous_fetch_date = str(
                    previous_snapshot.get("fetched_at") or ""
                )[:10]
                refreshed_records = []
                for record in kept:
                    refreshed = dict(record)
                    previous = previous_records.get(record_identity(refreshed)) or {}
                    refreshed["source_first_seen_date"] = (
                        previous.get("source_first_seen_date")
                        or previous_fetch_date
                        or as_of.isoformat()
                    )
                    refreshed_records.append(refreshed)
                sources[slug] = {
                    "source": result.display_name,
                    "source_type": result.source_type,
                    "fetched_at": iso_utc(utc_now()),
                    "record_count": len(refreshed_records),
                    "diagnostics": result.diagnostics,
                    "records": refreshed_records,
                }
                published = refreshed_records
                status = "refreshed"
            else:
                if result.retain_on_failure:
                    published = _cached_publishable(sources, slug, as_of)
                    status = "unhealthy_kept_last_good"
                else:
                    published = []
                    _clear_failed_source(sources, result)
                    status = "unhealthy_no_fallback"
            summaries.append({
                "slug": slug, "source": result.display_name, "status": status,
                "fetched": len(result.records), "dropped_invalid": len(dropped),
                "published": len(published), "healthy": healthy, "error": None,
                "diagnostics": result.diagnostics,
            })
        else:
            if result.retain_on_failure:
                published = _cached_publishable(sources, slug, as_of)
                snapshot_age = _snapshot_age_days(sources, slug, as_of)
                recent_snapshot = bool(
                    result.fallback_grace_days > 0
                    and snapshot_age is not None
                    and snapshot_age <= result.fallback_grace_days
                    and within_health_bounds(
                        len(published), result.min_records, result.max_records
                    )
                )
                status = (
                    "recent_snapshot" if recent_snapshot
                    else "failed_kept_last_good"
                )
            else:
                published = []
                snapshot_age = None
                recent_snapshot = False
                status = "failed_no_fallback"
                _clear_failed_source(sources, result)
            summaries.append({
                "slug": slug, "source": result.display_name,
                "status": status,
                "fetched": 0, "dropped_invalid": 0,
                "published": len(published), "healthy": recent_snapshot,
                "error": result.error,
                "diagnostics": result.diagnostics,
                "snapshot_age_days": snapshot_age,
                "fallback_grace_days": result.fallback_grace_days,
            })
        live.extend(published)

    return live, cache, summaries


# --------------------------------------------------------------------------
# Merge + dedup (Grants.gov always wins)
# --------------------------------------------------------------------------
def _norm_title(record: dict) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (record.get("title") or "").casefold()).strip()


def _norm_number(value) -> str:
    number = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    # VPR digests commonly spell an NSF solicitation as ``NSF26-511`` while
    # Grants.gov publishes the same identifier as ``26-511``. The sponsor
    # prefix is presentation, not identity.
    return re.sub(r"^nsf(?=\d{5,}$)", "", number)


def _canonical_title(record: dict) -> str:
    title = str(record.get("title") or "").strip()
    title = re.sub(r"^\s*new\s+", "", title, flags=re.I)
    title = re.sub(
        r"^\s*(?:u\.?s\.?\s+)?(?:national\s+science\s+foundation|nsf)\s+",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"\s*\([A-Z][A-Z0-9&/ -]{1,11}\)\s*", " ", title)
    title = re.sub(
        r"(?:\s*\|\s*)?(?:NSF\s*)?\d{2}-\d{3,4}\.?\s*$",
        "",
        title,
        flags=re.I,
    )
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def merge_records(base: list[dict], external: list[dict]) -> tuple[list[dict], dict]:
    """Combine base (Grants.gov) and external records; base always wins."""
    combined = [normalize_record_facets(dict(record)) for record in base]
    external = [normalize_record_facets(dict(record)) for record in external]
    seen_identity = {record_identity(r) for r in combined}
    base_titles = {_norm_title(r) for r in combined if r.get("title")}
    canonical_titles = {
        _canonical_title(r) for r in combined if _canonical_title(r)
    }
    base_numbers = {
        _norm_number(r.get("opportunity_number"))
        for r in combined if r.get("opportunity_number")
    }

    added = dropped_identity = dropped_crossdup = 0
    for record in external:
        identity = record_identity(record)
        if identity in seen_identity:
            dropped_identity += 1
            continue
        number = _norm_number(record.get("opportunity_number"))
        title = _norm_title(record)
        canonical_title = _canonical_title(record)
        if (
            (number and number in base_numbers)
            or title in base_titles
            or (canonical_title and canonical_title in canonical_titles)
        ):
            dropped_crossdup += 1
            continue
        seen_identity.add(identity)
        combined.append(record)
        if number:
            base_numbers.add(number)
        if title:
            base_titles.add(title)
        if canonical_title:
            canonical_titles.add(canonical_title)
        added += 1

    combined.sort(
        key=lambda r: (
            r.get("close_date") or "9999-12-31",
            (r.get("title") or "").casefold(),
        )
    )
    stats = {
        "base_count": len(combined) - added,
        "external_considered": len(external),
        "external_added": added,
        "dropped_duplicate_identity": dropped_identity,
        "dropped_cross_source_duplicate": dropped_crossdup,
        "final_count": len(combined),
    }
    return combined, stats


def rebuild_catalog(catalog: dict, combined: list[dict],
                    results: list[AdapterResult],
                    lifecycle: list[dict] | None = None) -> dict:
    """Return a new catalog with combined records and rebuilt derived data."""
    catalog = dict(catalog)
    combined = [normalize_record_facets(dict(record)) for record in combined]
    catalog["opportunities"] = combined
    catalog["record_count"] = len(combined)
    catalog["status_counts"] = dict(
        sorted(Counter(r.get("status") for r in combined if r.get("status")).items())
    )
    catalog["facets"] = facet_counts(combined)
    catalog["search_index"] = build_search_index(combined)

    diagnostics = dict(catalog.get("diagnostics") or {})
    diagnostics["quality"] = quality_metrics(combined)
    source_counts = Counter(
        r.get("source") for r in combined
        if r.get("source") and r.get("source") != "Grants.gov"
    )
    diagnostics["additional_sources"] = {
        "merged_at": iso_utc(utc_now()),
        "source_record_counts": dict(sorted(source_counts.items())),
        "lifecycle": lifecycle or [],
        "adapters": [
            {"slug": r.slug, "source": r.display_name, "source_type": r.source_type,
             "ok": r.ok, "record_count": r.record_count, "error": r.error,
             "diagnostics": r.diagnostics}
            for r in results
        ],
    }
    catalog["diagnostics"] = diagnostics
    return catalog


# --------------------------------------------------------------------------
# The drop-in entry point
# --------------------------------------------------------------------------
def integrate(catalog_path: Path = DEFAULT_CATALOG,
              cache_path: Path = DEFAULT_CACHE,
              adapters=None,
              include_disabled: bool = False,
              write: bool = False,
              as_of: date | None = None) -> dict:
    """Collect sources, apply the safe lifecycle, and merge into the catalog.

    With ``write=False`` (default) nothing is written; a summary is returned so
    the result can be previewed. With ``write=True`` the catalog and the source
    snapshot cache are rewritten -- but only if post-merge validation passes.
    """
    catalog = load_catalog(catalog_path)
    if as_of is None:
        stamp = str(catalog.get("generated_at") or "")[:10]
        as_of = date.fromisoformat(stamp) if stamp else date.today()

    selected_adapters = None if adapters is None else list(adapters)
    selected_slugs = {
        adapter.slug for adapter in (selected_adapters or [])
    }
    base = [
        record
        for record in (catalog.get("opportunities") or [])
        if (
            record.get("source") == "Grants.gov"
            or (
                selected_adapters is not None
                and not any(
                    str(record.get("opportunity_id") or "").startswith(
                        f"{slug}:"
                    )
                    for slug in selected_slugs
                )
            )
        )
    ]
    cache = load_source_cache(cache_path)
    # Adapters that must reconcile against what is already published -- rather
    # than only add to it -- read the base records from here (§18.1 P8.2). `base`
    # is the right input: it is Grants.gov plus every record this run is not
    # itself responsible for re-supplying.
    _, results = collect(
        adapters=selected_adapters,
        include_disabled=include_disabled,
        context={"catalog_records": base, "as_of": as_of},
    )
    external, cache, source_summaries = resolve_live_records(results, cache, as_of)
    combined, stats = merge_records(base, external)
    # Discoverability: tag opaque umbrella FOAs (e.g. DOE Office of Science) with
    # program-area topics/terms so topical searches surface them.
    augmented = augment_records(combined)

    validation_ok, validation_error = True, None
    try:
        validate_catalog(combined, len(base), len(base) + 20000)
    except Exception as exc:  # noqa: BLE001 - report, never publish an invalid catalog
        validation_ok, validation_error = False, str(exc)

    summary = {
        "catalog_path": str(catalog_path),
        "cache_path": str(cache_path),
        "catalog_date": as_of.isoformat(),
        "written": False,
        "stats": stats,
        "sources": source_summaries,
        "discoverability_augmented": augmented,
        "validation": {"ok": validation_ok, "error": validation_error},
    }

    if write and validation_ok:
        new_catalog = rebuild_catalog(catalog, combined, results, source_summaries)
        save_catalog(new_catalog, catalog_path)
        save_source_cache(cache, cache_path)
        summary["written"] = True
    return summary
