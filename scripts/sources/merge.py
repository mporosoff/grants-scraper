"""Merge external-source records into the generated catalog with a safe lifecycle.

Design (addresses the source-lifecycle and currentness audit findings):

- **Atomic per-source replace.** Complete source snapshots are replaced
  wholesale on a successful refresh, so a changed deadline or a removed
  opportunity is reflected -- not left stale next to an old copy.
- **Bounded observations.** Incremental mailbox windows retain current records
  outside the window. Fresh observations supersede old records; absence alone
  never verifies removal, and carried evidence keeps its actual last-seen date.
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
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit

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
from .registry import REGISTRY, AdapterResult, collect
from .validate import filter_publishable, record_is_publishable, within_health_bounds
from .discoverability import augment_records
from scripts.source_documents import merge_duplicate_evidence
from scripts.currentness import record_is_current

DEFAULT_CATALOG = Path("data/opportunities.js")
DEFAULT_CACHE = Path("data/source_records.json")
CACHE_SCHEMA_VERSION = 1
OPERATIONAL_SOURCE_EVIDENCE_KEYS = {
    "failure_class",
    "failure_reason",
    "last_successful_refresh_at",
    "retained_data_age_days",
    "publication_decision",
}
TERMINAL_REASONS = {"expired", "closed", "archived", "cancelled", "canceled", "withdrawn"}


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


def _unobserved_current(sources: dict, result: AdapterResult, as_of: date, witnesses=None) -> list[dict]:
    """Carry only current records that no fresh observation supersedes.

    Check every observed identity before filtering. An expired, withdrawn or
    invalid replacement must never resurrect the previously open record.
    """
    observed_ids = {r.get("opportunity_id") for r in result.records}
    observed_keys = {record_identity(r) for r in result.records}
    snapshot = sources.get(result.slug) or {}
    last_seen = str(snapshot.get("fetched_at") or "")[:10] or None
    carried = []
    latest, _ = _incremental_observations(snapshot.get("records") or [], witnesses)
    publishable, _ = filter_publishable(latest, as_of)
    for record in publishable:
        ident, key = record.get("opportunity_id"), record_identity(record)
        if (ident in observed_ids or key in observed_keys
                or not record_is_current(record, as_of)[0]):
            continue
        carried.append({**record,
            "source_last_seen_date": record.get("source_last_seen_date") or last_seen,
            "source_observation": "retained_outside_window"})
    return carried


def _latest_observations(records: list[dict]) -> list[dict]:
    """Mailbox records are ordered oldest first; select before date filtering.

    An expired or invalid latest version still supersedes its older version.
    Keep selected records in their original order for deterministic merging.
    """
    selected, ids, keys = [], set(), set()
    for record in reversed(records):
        ident, key = record.get("opportunity_id"), record_identity(record)
        if ident not in ids and key not in keys:
            selected.append(record)
        ids.add(ident)
        keys.add(key)
    return list(reversed(selected))


def _observation_url(record: dict) -> tuple | None:
    """Ignore presentation/tracking differences, not distinct sponsor programs."""
    from .adapters.vpr_email import unwrap_urldefense
    value = (record.get("detail_page") or record.get("funding_opportunity_url")
             or record.get("primary_document_url"))
    if not value:
        return None  # An invalid newest observation still supersedes its old row.
    try:
        parsed = urlsplit(unwrap_urldefense(value))
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        query = sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                       if not k.casefold().startswith("utm_") and k.casefold() not in {"gclid", "fbclid"})
        return host, parsed.port if parsed.port not in (None, 80, 443) else None, parsed.path.rstrip("/"), urlencode(query)
    except (TypeError, ValueError):
        return (str(value),)


IDENTITY_WITNESS_LIMIT = 500


def _identity_witness(record):
    from .official_identity import record_grants_ids
    url = _observation_url(record)
    return {"id": str(record.get("opportunity_id") or ""), "key": record_identity(record),
            "url": list(url) if url else None, "number": _norm_number(record.get("opportunity_number")),
            "title": _canonical_title(record), "grants": sorted(record_grants_ids(record))}


def _identity_history(snapshot, fresh):
    """Keep bounded identity witnesses even when live/terminal records disappear.

    These are identity observations, not currentness or freshness assertions.
    Full source records remain in the retained generation artifact. A changed
    source ID or exact official alias proof can resolve a program's identity;
    simply dropping one conflicting email from a later window cannot do so.
    """
    prior = snapshot.get("identity_witnesses", {"version": 1, "observations": []})
    if (not isinstance(prior, dict) or set(prior) != {"version", "observations"}
            or type(prior["version"]) is not int or prior["version"] != 1
            or not isinstance(prior["observations"], list)):
        raise ValueError("Invalid incremental identity witness metadata")
    observations = prior["observations"] + [_identity_witness(r) for r in (snapshot.get("records") or []) + fresh]
    unique = {}
    for witness in observations:
        if (not isinstance(witness, dict) or set(witness) != {"id", "key", "url", "number", "title", "grants"}
                or not all(isinstance(witness[k], str) and len(witness[k]) <= 2048 for k in ("id", "key", "number", "title"))
                or not witness["id"] or not witness["key"]
                or not isinstance(witness["grants"], list) or len(witness["grants"]) > 4
                or any(not isinstance(x, str) or not re.fullmatch(r"[0-9]{1,40}", x) for x in witness["grants"])
                or (witness["url"] is not None and (not isinstance(witness["url"], list)
                    or len(witness["url"]) not in (1, 4)
                    or any(x is not None and (type(x) not in (str, int) or len(str(x)) > 4096) for x in witness["url"])))):
            raise ValueError("Invalid incremental identity witness fields")
        identity = json.dumps(witness, sort_keys=True, separators=(",", ":"))
        unique[identity] = witness
    if len(unique) > IDENTITY_WITNESS_LIMIT:
        raise ValueError("Incremental identity witness capacity exceeded; retained evidence requires review")
    return {"version": 1, "observations": [unique[key] for key in sorted(unique)]}


def _incremental_observations(records: list[dict], witnesses=None) -> tuple[list[dict], list[str]]:
    """Select latest genuine versions; quarantine unresolved stable-ID collisions.

    A digest title hash or a number copied into an event is not enough to merge
    different programs. Tracking links, exact Grants.gov aliases, and an intact
    source-owned number plus unchanged program title remain supported aliases.
    No missing item or collision is evidence of an official withdrawal.
    """
    evidence = (witnesses or {}).get("observations", []) + [_identity_witness(r) for r in records]
    groups = []
    for record in evidence:
        ident, key = record["id"], record["key"]
        linked = [group for group in groups if ident in group[0] or key in group[1]]
        ids, keys, members = {ident}, {key}, [record]
        for group in linked:
            ids.update(group[0]); keys.update(group[1]); members.extend(group[2])
            groups.remove(group)
        groups.append((ids, keys, members))
    withheld = set()
    for ids, _, members in groups:
        urls = {tuple(row["url"]) for row in members if row["url"] is not None}
        if len(urls) <= 1:
            continue
        # A later verified official mapping can add proof for an older resource
        # without deleting that original unresolved witness from history.
        grants = [{ident for row in members if row["url"] is not None and tuple(row["url"]) == url
                   for ident in row["grants"]} for url in urls]
        exact_grants_alias = all(len(proof) == 1 for proof in grants) and len(set.union(*grants)) == 1
        numbers = {row["number"] for row in members}
        stable_number_and_title = (len(numbers) == 1 and bool(next(iter(numbers)))
                                   and len({row["title"] for row in members}) == 1
                                   and bool(members[0]["title"])
                                   and len(set.union(*grants)) <= 1)
        if not exact_grants_alias and not stable_number_and_title:
            withheld.update(ids)
    selected = _latest_observations([row for row in records if row.get("opportunity_id") not in withheld])
    return selected, sorted(str(ident) for ident in withheld if ident)


def _snapshot_age_days(sources: dict, slug: str, as_of: date) -> int | None:
    stamp = str((sources.get(slug) or {}).get("fetched_at") or "")[:10]
    if not stamp:
        return None
    try:
        return max(0, (as_of - date.fromisoformat(stamp)).days)
    except ValueError:
        return None


def _last_successful_refresh_at(sources: dict, slug: str) -> str | None:
    source = sources.get(slug) or {}
    stamp = source.get("last_successful_refresh_at") if "last_successful_refresh_at" in source else source.get("fetched_at")
    return str(stamp) if stamp else None


def _classify_failure(result: AdapterResult) -> str:
    explicit = (result.diagnostics or {}).get("failure_class")
    if explicit:
        return str(explicit)
    message = str(result.error or "").casefold()
    if any(token in message for token in (
        "http error", "httperror", "http ", "timeout", "timed out", "connection",
        "network", "ssl", "tls", "dns",
    )):
        return "request_network"
    if any(token in message for token in (
        "parse", "worksheet", "header", "malformed", "unexpected shape",
    )):
        return "parser_drift"
    return "validation_failure"


def _source_evidence(
    sources: dict,
    result: AdapterResult,
    *,
    publication_decision: str,
    failure_class: str | None,
    retained_data_age_days: int | None,
) -> dict:
    return {
        "failure_class": failure_class,
        "failure_reason": (result.diagnostics or {}).get("failure_reason"),
        "last_successful_refresh_at": _last_successful_refresh_at(
            sources, result.slug
        ),
        "retained_data_age_days": retained_data_age_days,
        "publication_decision": publication_decision,
    }


def _clear_failed_source(sources: dict, result: AdapterResult) -> None:
    """Remove an unsafe snapshot while retaining failure diagnostics."""
    previous = sources.get(result.slug) or {}
    last_successful_refresh_at = _last_successful_refresh_at(sources, result.slug)
    last_successful_record_count = previous.get("last_successful_record_count")
    if last_successful_record_count is None and last_successful_refresh_at:
        last_successful_record_count = previous.get("record_count")
        if last_successful_record_count is None:
            last_successful_record_count = len(previous.get("records") or [])
    cleared = {
        "source": result.display_name,
        "source_type": result.source_type,
        "fetched_at": None,
        "record_count": 0,
        "diagnostics": result.diagnostics,
        "records": [],
    }
    if last_successful_refresh_at:
        cleared["last_successful_refresh_at"] = last_successful_refresh_at
        cleared["last_successful_record_count"] = last_successful_record_count
    sources[result.slug] = cleared


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
        partitions = (result.diagnostics or {}).get("partitions") or []
        verified_prefixes = [part.get("id_prefix") for part in partitions
            if isinstance(part, dict) and part.get("healthy") is True and part.get("status") == "refreshed"
            and isinstance(part.get("id_prefix"), str) and part["id_prefix"].startswith(slug + ":")]
        partial = bool((result.diagnostics or {}).get("partial_failure") and verified_prefixes
            and all(any(str(record.get("opportunity_id") or "").startswith(prefix) for prefix in verified_prefixes)
                    for record in result.records))
        incremental = result.snapshot_complete is False
        witnesses = (_identity_history(sources.get(slug) or {}, result.records if result.ok or partial else [])
                     if incremental else None)
        if result.ok or partial:
            fresh, collisions = _incremental_observations(result.records, witnesses) if incremental else (result.records, [])
            kept, dropped = filter_publishable(fresh, as_of)
            carried = []
            terminal_observations = []
            health_count = len(kept)
            if incremental:
                kept = [r for r in kept if record_is_current(r, as_of)[0]]
                # A successfully parsed window may contain only newly closed
                # or expired calls. That is an observation, not parser failure.
                terminal_observations = [
                    {**{k: r.get(k) for k in ("opportunity_id", "source", "status", "close_date",
                                             "deadlines", "last_updated", "version")},
                     "canonical_identity": record_identity(r)}
                    for r in fresh
                    if record_is_current(r, as_of)[1] in TERMINAL_REASONS
                    and record_is_publishable(r, as_of)[1] in {"ok", "expired"}]
                health_count = len(kept) + len(terminal_observations)
                carried = _unobserved_current(sources, result, as_of, witnesses)
                if result.max_records is not None and max(len(result.records), len(kept) + len(carried)) > result.max_records:
                    # No truncation or partially updated cache on overflow.
                    raise ValueError(f"{slug}: incremental snapshot exceeds maximum records")
            healthy = within_health_bounds(
                health_count, result.min_records, result.max_records
            )
            if healthy:
                previous_snapshot = sources.get(slug) or {}
                previous_success = _last_successful_refresh_at(sources, slug)
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
                    if incremental:
                        refreshed["source_last_seen_date"] = as_of.isoformat()
                        refreshed["source_observation"] = "observed_in_window"
                    refreshed_records.append(refreshed)
                refreshed_records.extend(carried)
                diagnostics = result.diagnostics or {}
                source_snapshot_at = diagnostics.get("source_snapshot_at")
                if source_snapshot_at:
                    refreshed_at = f"{source_snapshot_at}T00:00:00Z"
                else:
                    refreshed_at = iso_utc(utc_now())
                sources[slug] = {
                    "source": result.display_name,
                    "source_type": result.source_type,
                    "fetched_at": refreshed_at,
                    "record_count": len(refreshed_records),
                    "diagnostics": result.diagnostics,
                    "records": refreshed_records,
                }
                published = refreshed_records
                status = "recent_snapshot" if source_snapshot_at else "refreshed"
                publication_decision = (
                    "published_bounded_source_snapshot"
                    if source_snapshot_at
                    else "published_fresh_records"
                )
                failure_class = None
                retained_data_age_days = (
                    diagnostics.get("source_snapshot_age_days")
                    if source_snapshot_at
                    else 0
                )
                if partial:
                    sources[slug]["last_successful_refresh_at"] = previous_success
                    sources[slug]["last_successful_record_count"] = previous_snapshot.get(
                        "last_successful_record_count", previous_snapshot.get("record_count"))
                    healthy = False
                    status = "partial_refresh"
                    publication_decision = "published_independently_verified_records"
                    failure_class = _classify_failure(result)
            else:
                if result.retain_on_failure:
                    published = carried if incremental else _cached_publishable(sources, slug, as_of)
                    if incremental:
                        # A malformed new version is not a verified withdrawal,
                        # but it durably invalidates the older cached version.
                        # Preserve the successful-refresh timestamp/provenance.
                        previous = sources.get(slug) or {}
                        sources[slug] = {**previous, "records": carried, "record_count": len(carried),
                            "last_successful_refresh_at": _last_successful_refresh_at(sources, slug),
                            "last_successful_record_count": previous.get("last_successful_record_count",
                                previous.get("record_count", len(previous.get("records") or [])))}
                    status = "unhealthy_kept_last_good"
                    publication_decision = "published_filtered_last_known_good"
                    retained_data_age_days = _snapshot_age_days(
                        sources, slug, as_of
                    )
                else:
                    published = []
                    _clear_failed_source(sources, result)
                    status = "unhealthy_no_fallback"
                    publication_decision = "published_zero_fail_closed"
                    retained_data_age_days = None
                failure_class = "health_bound_violation"
            evidence = _source_evidence(
                sources,
                result,
                publication_decision=publication_decision,
                failure_class=failure_class,
                retained_data_age_days=retained_data_age_days,
            )
            summaries.append({
                "slug": slug, "source": result.display_name, "status": status,
                "fetched": len(result.records), "dropped_invalid": len(dropped),
                "published": len(published), "healthy": healthy, "error": result.error if partial else None,
                "diagnostics": result.diagnostics,
                **evidence,
                **({"withheld_ids": [r["opportunity_id"] for r in dropped if r["reason"] != "expired"]}
                   if any(r["reason"] != "expired" for r in dropped) else {}),
                **({"snapshot_complete": False,
                    "retained_outside_window_ids": [r["opportunity_id"] for r in carried],
                    "identity_collision_ids": collisions,
                    "observed_terminal_records": terminal_observations if healthy else []}
                   if incremental else {}),
            })
        else:
            if result.retain_on_failure:
                if result.snapshot_complete is False:
                    selected, _ = _incremental_observations((sources.get(slug) or {}).get("records") or [], witnesses)
                    published, _ = filter_publishable(selected, as_of)
                    published = [r for r in published if record_is_current(r, as_of)[0]]
                else:
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
                publication_decision = "published_filtered_last_known_good"
                retained_data_age_days = snapshot_age
            else:
                published = []
                snapshot_age = None
                recent_snapshot = False
                status = "failed_no_fallback"
                _clear_failed_source(sources, result)
                publication_decision = "published_zero_fail_closed"
                retained_data_age_days = None
            evidence = _source_evidence(
                sources,
                result,
                publication_decision=publication_decision,
                failure_class=_classify_failure(result),
                retained_data_age_days=retained_data_age_days,
            )
            summaries.append({
                "slug": slug, "source": result.display_name,
                "status": status,
                "fetched": 0, "dropped_invalid": 0,
                "published": len(published), "healthy": recent_snapshot,
                "error": result.error,
                "diagnostics": result.diagnostics,
                "snapshot_age_days": snapshot_age,
                "fallback_grace_days": result.fallback_grace_days,
                **evidence,
                **({"snapshot_complete": False} if result.snapshot_complete is False else {}),
            })
        if incremental:
            # Current records are replaceable, but evidence of source identity
            # must survive terminal observations, quarantine and failed scans.
            # This does not assert that an old notice is still open or fresh.
            sources.setdefault(slug, {"source": result.display_name,
                "source_type": result.source_type, "fetched_at": None,
                "record_count": 0, "records": []})["identity_witnesses"] = witnesses
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
    # A normalized sponsor and complete official number prove a cross-source
    # duplicate. Similar titles alone never do. Stable public IDs are retained.
    identities = {record_identity(record): record for record in combined}
    ids = {str(record.get('opportunity_id')): record for record in combined if record.get('opportunity_id')}
    from .official_identity import record_grants_ids
    from scripts.solicitation_identity import solicitation_key
    grants = {str(r.get('opportunity_id')): r for r in combined if r.get('source') == 'Grants.gov'}
    added = dropped_identity = dropped_crossdup = 0
    for record in external:
        identity = record_identity(record)
        by_identity, by_id = identities.get(identity), ids.get(str(record.get('opportunity_id')))
        winner = by_identity or by_id
        official_ids = record_grants_ids(record)
        if official_ids:
            # Reconcile every supported identity path before moving evidence.
            # A number/stable-ID match must not bypass contradictory links,
            # even when the linked canonical record is absent from this feed.
            proofs = set(official_ids)
            for selected in (by_identity, by_id):
                if selected is not None:
                    proofs.update(record_grants_ids(selected))
                    if selected.get('source') == 'Grants.gov':
                        proofs.add(str(selected.get('opportunity_id')))
            if len(proofs) != 1:
                raise ValueError('Official record link conflicts with another record identity')
            linked = grants.get(next(iter(official_ids)))
            if linked is not None:
                if any(selected is not None and selected is not linked for selected in (by_identity, by_id)):
                    raise ValueError('Official record link conflicts with a preselected source identity')
                left, right = solicitation_key(linked), solicitation_key(record)
                if left and right and left != right:
                    raise ValueError('Official record link conflicts with sponsor/solicitation identity')
                winner = linked
        if winner is not None:
            if (winner.get('opportunity_id') == record.get('opportunity_id')
                or winner.get('opportunity_number') == record.get('opportunity_number')):
                dropped_identity += 1
            else:
                dropped_crossdup += 1
            merge_duplicate_evidence(winner, record)
            continue
        combined.append(record)
        identities[identity] = record
        if record.get('opportunity_id'):
            ids[str(record['opportunity_id'])] = record
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
        # Operational evidence belongs in the run summary/issue body. Keeping
        # it out of the generated product artifact preserves the established
        # catalog contract and the hermetic flag-off baseline.
        "lifecycle": [
            {
                key: value
                for key, value in source.items()
                if key not in OPERATIONAL_SOURCE_EVIDENCE_KEYS
            }
            for source in (lifecycle or [])
        ],
        "adapters": [
            {"slug": r.slug, "source": r.display_name, "source_type": r.source_type,
             "ok": r.ok, "record_count": r.record_count, "error": r.error,
             "diagnostics": r.diagnostics,
             **({"snapshot_complete": False} if r.snapshot_complete is False else {})}
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
              as_of: date | None = None,
              intake_path: Path | None = None) -> dict:
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
        context={"catalog_records": base, "as_of": as_of, "intake_path": intake_path},
    )
    external, cache, source_summaries = resolve_live_records(results, cache, as_of)
    identity_stats = {'enabled': False}
    if os.environ.get('VPR_ENRICH_LINKS', '').casefold() == 'true':
        from .official_identity import resolve
        identity_stats = {'enabled': True, **resolve(external, cache.setdefault('official_identities', {}))}
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
        'official_identity_resolution': identity_stats,
        "catalog_path": str(catalog_path),
        "cache_path": str(cache_path),
        "catalog_date": as_of.isoformat(),
        "written": False,
        "stats": stats,
        "sources": source_summaries,
        "disabled_sources": [
            {
                "slug": adapter.slug,
                "source": adapter.display_name,
                "reason": str(getattr(adapter, "disabled_reason", "")),
                "publication_decision": "not_run_published_zero",
            }
            for adapter in (selected_adapters if selected_adapters is not None else REGISTRY)
            if (
                not adapter.enabled
                and not include_disabled
                and str(getattr(adapter, "disabled_reason", ""))
            )
        ],
        "discoverability_augmented": augmented,
        "validation": {"ok": validation_ok, "error": validation_error},
    }
    selectors = [selector for result in results for selector in result.diagnostics.get("native_url_selectors", [])]
    if selectors:
        summary["intake"] = []
        for selector in selectors:
            result = next((r for r in results if r.slug == selector["adapter"]), None)
            selected_identities = {record_identity(r) for r in (result.records if result else [])
                                   if selector["url"] in {r.get("detail_page"), r.get("funding_opportunity_url"), r.get("primary_document_url")}}
            matching = [r for r in combined if selector["url"] in
                        {r.get("detail_page"), r.get("funding_opportunity_url"), r.get("primary_document_url")}
                        or record_identity(r) in selected_identities]
            summary["intake"].append(selector | {"state": "unavailable" if not result or not result.ok else
                "canonical" if matching else "not_currently_listed", "opportunity_ids": [r["opportunity_id"] for r in matching]})

    if write and validation_ok:
        new_catalog = rebuild_catalog(catalog, combined, results, source_summaries)
        save_catalog(new_catalog, catalog_path)
        save_source_cache(cache, cache_path)
        summary["written"] = True
    return summary
