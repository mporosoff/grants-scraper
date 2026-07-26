"""Merge external-source records into the generated catalog with a safe lifecycle.

Design (addresses the source-lifecycle and currentness audit findings):

- **Atomic per-source replace.** Each source's published records are replaced
  wholesale on a successful refresh, so a changed deadline or a removed
  opportunity is reflected -- not left stale next to an old copy.
- **Last-known-good on failure.** A committed snapshot cache
  (``data/source_records.json``) holds each source's last successful records.
  If a refresh fails or looks unhealthy, that snapshot is republished instead
  of dropping the source. (The daily ``build_catalog`` run rewrites the catalog
  from Grants.gov only, so this cache is what carries external records across
  days and survives a failed fetch.)
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
    quality_metrics,
    record_identity,
    utc_now,
    validate_catalog,
    write_catalog,
)
from .registry import AdapterResult, collect
from .validate import filter_publishable, within_health_bounds

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


def resolve_live_records(results: list[AdapterResult], cache: dict,
                         as_of: date) -> tuple[list[dict], dict, list[dict]]:
    """Return ``(records_to_publish, updated_cache, per_source_summaries)``.

    Successful, healthy sources are refreshed (and their snapshot updated);
    failed or unhealthy sources fall back to their last-known-good snapshot.
    Expired records are removed even from a cached snapshot.
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
                sources[slug] = {
                    "source": result.display_name,
                    "source_type": result.source_type,
                    "fetched_at": iso_utc(utc_now()),
                    "record_count": len(kept),
                    "records": kept,
                }
                published = kept
                status = "refreshed"
            else:
                published = _cached_publishable(sources, slug, as_of)
                status = "unhealthy_kept_last_good"
            summaries.append({
                "slug": slug, "source": result.display_name, "status": status,
                "fetched": len(result.records), "dropped_invalid": len(dropped),
                "published": len(published), "healthy": healthy, "error": None,
            })
        else:
            published = _cached_publishable(sources, slug, as_of)
            summaries.append({
                "slug": slug, "source": result.display_name,
                "status": "failed_kept_last_good", "fetched": 0, "dropped_invalid": 0,
                "published": len(published), "healthy": False, "error": result.error,
            })
        live.extend(published)

    return live, cache, summaries


# --------------------------------------------------------------------------
# Merge + dedup (Grants.gov always wins)
# --------------------------------------------------------------------------
def _norm_title(record: dict) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (record.get("title") or "").casefold()).strip()


def merge_records(base: list[dict], external: list[dict]) -> tuple[list[dict], dict]:
    """Combine base (Grants.gov) and external records; base always wins."""
    combined = list(base)
    seen_identity = {record_identity(r) for r in base}
    base_titles = {
        _norm_title(r) for r in base if r.get("title")
    }
    base_numbers = {
        str(r.get("opportunity_number")).strip().casefold()
        for r in base if r.get("opportunity_number")
    }

    added = dropped_identity = dropped_crossdup = 0
    for record in external:
        identity = record_identity(record)
        if identity in seen_identity:
            dropped_identity += 1
            continue
        number = str(record.get("opportunity_number") or "").strip().casefold()
        if (
            (number and number in base_numbers)
            or _norm_title(record) in base_titles
        ):
            dropped_crossdup += 1
            continue
        seen_identity.add(identity)
        combined.append(record)
        added += 1

    combined.sort(
        key=lambda r: (
            r.get("close_date") or "9999-12-31",
            (r.get("title") or "").casefold(),
        )
    )
    stats = {
        "base_count": len(base),
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
             "ok": r.ok, "record_count": r.record_count, "error": r.error}
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

    base = [
        record for record in (catalog.get("opportunities") or [])
        if record.get("source") == "Grants.gov"
    ]
    cache = load_source_cache(cache_path)
    _, results = collect(adapters=adapters, include_disabled=include_disabled)
    external, cache, source_summaries = resolve_live_records(results, cache, as_of)
    combined, stats = merge_records(base, external)

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
        "validation": {"ok": validation_ok, "error": validation_error},
    }

    if write and validation_ok:
        new_catalog = rebuild_catalog(catalog, combined, results, source_summaries)
        save_catalog(new_catalog, catalog_path)
        save_source_cache(cache, cache_path)
        summary["written"] = True
    return summary
