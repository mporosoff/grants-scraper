"""Generate deterministic Hajim faculty discovery and match assets.

The reviewed canonical faculty JSON is the sole roster authority. Matching is
local, lexical, evidence-qualified, and does not call a model or provider.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from scripts.currentness import record_is_current
from scripts.import_hajim_faculty import validate_payload


SCHEMA_FAMILY = "hajim-faculty-match"
DIRECTORY_SCHEMA_VERSION = 1
GRAPH_SCHEMA_VERSION = 2
MAX_FACULTY_PER_OPPORTUNITY = 12
MAX_OPPORTUNITIES_PER_FACULTY = 25
DIRECTORY_RAW_BUDGET = 350_000
DIRECTORY_GZIP_BUDGET = 90_000
GRAPH_RAW_BUDGET = 2_500_000
GRAPH_GZIP_BUDGET = 500_000

_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", re.I)
_SPACE_RE = re.compile(r"\s+")
_GENERIC = {
    "a", "an", "and", "application", "applications", "approach", "approaches",
    "based", "can", "data", "development", "for", "from", "general", "health",
    "in", "into", "materials", "method", "methods", "model", "modeling", "models",
    "new", "of", "on", "or", "program", "programs", "project", "projects",
    "research", "science", "studies", "study", "support", "system", "systems",
    "technology", "the", "their", "to", "toward", "towards", "using", "with", "energy",
}
_FIELD_WEIGHTS = {"title": 4.5, "description": 2.0, "published_subject": 1.5}


class FacultyMatchError(ValueError):
    """Raised when canonical input or generated assets violate the contract."""


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    return _SPACE_RE.sub(" ", text).strip()


def _stem(token: str) -> str:
    """Small deterministic word-form normalizer, not a synonym map."""
    token = token.casefold()
    if "-" in token or len(token) <= 4:
        return token
    for suffix, replacement in (
        ("ization", "ize"), ("isation", "ise"), ("ational", "ate"),
        ("iveness", "ive"), ("ically", "ic"), ("ments", "ment"),
        ("ation", "ate"), ("ities", "ity"), ("ing", ""), ("ers", "er"),
        ("ies", "y"), ("ed", ""), ("es", ""), ("s", ""),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) + len(replacement) >= 4:
            return token[:-len(suffix)] + replacement
    return token


def _tokens(value: object) -> list[str]:
    return [_stem(token) for token in _WORD_RE.findall(_normalize(value))]


def _distinctive_tokens(value: object) -> list[str]:
    found: list[str] = []
    for token in _tokens(value):
        if token in _GENERIC or len(token) < 3:
            continue
        if token not in found:
            found.append(token)
    return found


def _load_js_object(path: str | Path, global_name: str) -> tuple[dict, bytes]:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    marker = f"globalThis.{global_name}="
    start = text.find(marker)
    if start < 0:
        raise FacultyMatchError(f"{path} does not assign {marker}")
    body = text[start + len(marker):].strip()
    if body.endswith(";"):
        body = body[:-1]
    value = json.loads(body)
    if not isinstance(value, dict):
        raise FacultyMatchError(f"{path} must contain a JSON object")
    return value, raw


def load_catalog(path: str | Path) -> tuple[dict, bytes]:
    catalog, raw = _load_js_object(path, "GRANT_CATALOG")
    records = catalog.get("opportunities")
    if not isinstance(records, list) or catalog.get("record_count") != len(records):
        raise FacultyMatchError("Catalog record_count is incompatible with opportunities")
    return catalog, raw


def load_faculty_config(path: str | Path) -> tuple[dict, bytes]:
    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    validate_payload(payload, require_snapshot=False)
    return payload, raw


def _catalog_identity(catalog: dict, raw: bytes) -> dict:
    return {
        "record_count": catalog["record_count"],
        "generated_at": catalog.get("generated_at") or "",
        "fingerprint": hashlib.sha256(raw).hexdigest(),
    }


_IDENTITY_FIELDS = frozenset({"generation_id", "asset_version", "projection_fingerprints"})


def _projection_fingerprint(value: dict) -> str:
    projection = {key: item for key, item in value.items() if key not in _IDENTITY_FIELDS}
    raw = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _generation_id(source_sha: str, catalog_fingerprint: str,
                   projection_fingerprints: dict[str, str]) -> str:
    identity = {
        "schema_family": SCHEMA_FAMILY,
        "directory_schema_version": DIRECTORY_SCHEMA_VERSION,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "faculty_source_sha256": source_sha,
        "catalog_fingerprint": catalog_fingerprint,
        "projection_fingerprints": projection_fingerprints,
    }
    raw = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _search_document(profile: dict) -> str:
    return " ".join(_tokens(profile.get("research_interests_text"))) if profile.get("rankable") else ""


def build_directory(config: dict, catalog_identity: dict) -> dict:
    profiles = [{
        "faculty_id": profile["faculty_id"],
        "name": profile["name"],
        "home_unit": profile["home_unit"],
        "relationship": profile["relationship"],
        "relationship_label": profile["relationship_label"],
        "rosters": profile["rosters"],
        "appointment_text": profile["appointment_text"],
        "rankable": profile["rankable"],
        "search_document": _search_document(profile),
    } for profile in config["profiles"]]
    return {
        "schema_family": SCHEMA_FAMILY,
        "schema_version": DIRECTORY_SCHEMA_VERSION,
        "catalog": catalog_identity,
        "faculty_source": dict(config["source"]),
        "profiles": profiles,
    }


def _faculty_idf(profiles: list[dict]) -> dict[str, float]:
    rankable = [profile for profile in profiles if profile.get("rankable")]
    document_frequency: Counter[str] = Counter()
    for profile in rankable:
        document_frequency.update(set(_distinctive_tokens(profile["research_interests_text"])))
    total = len(rankable)
    return {token: math.log((total + 1.0) / (count + 1.0)) + 1.0
            for token, count in document_frequency.items()}


def _published_subject_text(record: dict) -> str:
    values: list[str] = []
    for key in ("disciplines", "topic_areas"):
        values.extend(str(item) for item in (record.get(key) or []) if item)
    values.append(str(record.get("document_search_text") or ""))
    for fact in (record.get("document_evidence") or {}).get("facts") or []:
        if isinstance(fact, dict):
            values.extend(str(fact.get(key) or "") for key in ("label", "value", "excerpt"))
    return " ".join(values)


def _opportunity_fields(record: dict) -> dict[str, str]:
    return {
        "title": str(record.get("title") or ""),
        "description": str(record.get("description") or ""),
        "published_subject": _published_subject_text(record),
    }


def _phrase_admitted(phrase: str, field_tokens: set[str], idf: dict[str, float]) -> tuple[bool, float]:
    concepts = _distinctive_tokens(phrase)
    if not concepts:
        return False, 0.0
    covered = [token for token in concepts if token in field_tokens]
    if len(concepts) == 1:
        admitted = len(covered) == 1 and idf.get(concepts[0], 0.0) >= 2.2
    elif len(concepts) <= 3:
        admitted = len(covered) == len(concepts)
    else:
        admitted = len(covered) >= max(3, math.ceil(0.75 * len(concepts)))
    return admitted, sum(idf.get(token, 1.0) for token in covered)


def _excerpt(text: str, concepts: list[str], limit: int = 190) -> str:
    clean = _SPACE_RE.sub(" ", text).strip()
    if len(clean) <= limit:
        return clean
    lowered = _normalize(clean)
    positions = [lowered.find(token) for token in concepts if lowered.find(token) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 55)
    end = min(len(clean), start + limit)
    if end == len(clean):
        start = max(0, end - limit)
    return ("…" if start else "") + clean[start:end].strip() + ("…" if end < len(clean) else "")


def _prepare_opportunity(record: dict) -> tuple[dict[str, str], dict[str, set[str]], set[str]]:
    fields = _opportunity_fields(record)
    token_sets = {field: set(_tokens(text)) for field, text in fields.items()}
    return fields, token_sets, set().union(*token_sets.values())


def score_profile_opportunity(profile: dict, record: dict, idf: dict[str, float],
                              prepared: tuple[dict[str, str], dict[str, set[str]], set[str]] | None = None) -> dict | None:
    if not profile.get("rankable"):
        return None
    fields, token_sets, opportunity_tokens = prepared or _prepare_opportunity(record)
    phrase_hits: list[tuple[str, str, float]] = []
    for phrase in profile["research_phrases"]:
        best: tuple[str, float] | None = None
        for field, tokens in token_sets.items():
            admitted, rarity = _phrase_admitted(phrase, tokens, idf)
            if admitted:
                weighted = rarity * _FIELD_WEIGHTS[field]
                if best is None or weighted > best[1] or (weighted == best[1] and field < best[0]):
                    best = (field, weighted)
        if best is not None:
            phrase_hits.append((phrase, best[0], best[1]))
    if not phrase_hits:
        return None
    phrase_hits.sort(key=lambda item: (-item[2], item[0].casefold(), item[1]))
    chosen = phrase_hits[:4]
    full_overlap = set(_distinctive_tokens(profile["research_interests_text"])) & opportunity_tokens
    theme_hits = []
    for theme in profile.get("derived_themes") or []:
        theme_tokens = _distinctive_tokens(theme)
        if theme_tokens and sum(token in opportunity_tokens for token in theme_tokens) >= min(2, len(theme_tokens)):
            theme_hits.append(theme)
    score = sum(item[2] for item in chosen)
    score += min(8.0, 0.6 * sum(idf.get(token, 1.0) for token in full_overlap))
    score += min(4.5, 1.5 * max(0, len(chosen) - 1))
    score += min(1.5, 0.5 * len(theme_hits))
    score = round(score, 3)
    evidence = []
    for field in ("title", "description", "published_subject"):
        field_hits = [item for item in chosen if item[1] == field]
        if not field_hits:
            continue
        concepts = [token for item in field_hits for token in _distinctive_tokens(item[0])]
        excerpt = _excerpt(fields[field], concepts)
        if excerpt:
            evidence.append({"field": field, "excerpt": excerpt})
    opportunity_id = str(record.get("opportunity_id") or record.get("opportunity_number") or "")
    if not opportunity_id:
        return None
    return {
        "faculty_id": profile["faculty_id"],
        "opportunity_id": opportunity_id,
        "score": score,
        "tier": "likely_relevant" if score >= 32.0 or len(chosen) >= 2 else "possible_relevance",
        "matched_profile_phrases": [item[0] for item in chosen],
        "opportunity_evidence": evidence[:2],
        "corroborating_themes": theme_hits[:3],
    }


def _current_records(catalog: dict) -> list[dict]:
    records = []
    for record in catalog["opportunities"]:
        if record.get("status") and not record_is_current(record)[0]:
            continue
        if not (record.get("opportunity_id") or record.get("opportunity_number")):
            continue
        records.append(record)
    return sorted(records, key=lambda record: (
        str(record.get("opportunity_id") or record.get("opportunity_number")),
        str(record.get("title") or "").casefold(),
    ))


def build_graph(config: dict, catalog: dict, catalog_identity: dict) -> dict:
    profiles = config["profiles"]
    idf = _faculty_idf(profiles)
    candidates_by_opportunity: dict[str, list[dict]] = defaultdict(list)
    for record in _current_records(catalog):
        prepared = _prepare_opportunity(record)
        for profile in profiles:
            edge = score_profile_opportunity(profile, record, idf, prepared)
            if edge is not None:
                candidates_by_opportunity[edge["opportunity_id"]].append(edge)
    opportunity_bounded: list[dict] = []
    for opportunity_id in sorted(candidates_by_opportunity):
        ranked = sorted(candidates_by_opportunity[opportunity_id], key=lambda edge: (
            -edge["score"], edge["faculty_id"], edge["opportunity_id"],
        ))
        opportunity_bounded.extend(ranked[:MAX_FACULTY_PER_OPPORTUNITY])
    candidates_by_faculty: dict[str, list[dict]] = defaultdict(list)
    for edge in opportunity_bounded:
        candidates_by_faculty[edge["faculty_id"]].append(edge)
    retained: set[tuple[str, str]] = set()
    for faculty_id in sorted(candidates_by_faculty):
        ranked = sorted(candidates_by_faculty[faculty_id], key=lambda edge: (
            -edge["score"], edge["opportunity_id"], edge["faculty_id"],
        ))
        retained.update((edge["faculty_id"], edge["opportunity_id"])
                        for edge in ranked[:MAX_OPPORTUNITIES_PER_FACULTY])
    edges = sorted(
        (edge for edge in opportunity_bounded
         if (edge["faculty_id"], edge["opportunity_id"]) in retained),
        key=lambda edge: (edge["opportunity_id"], -edge["score"], edge["faculty_id"]),
    )
    by_opportunity: dict[str, list[int]] = defaultdict(list)
    by_faculty: dict[str, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        by_opportunity[edge["opportunity_id"]].append(index)
        by_faculty[edge["faculty_id"]].append(index)
    contacts = {profile["faculty_id"]: {
        "email": profile["email"],
        "website_url": profile["website_url"],
        "source_urls": profile["source_urls"],
        "checked_date": profile["checked_date"],
    } for profile in profiles}
    return {
        "schema_family": SCHEMA_FAMILY,
        "schema_version": GRAPH_SCHEMA_VERSION,
        "catalog": catalog_identity,
        "faculty_source": dict(config["source"]),
        "contacts": contacts,
        "edges": edges,
        "by_opportunity": dict(by_opportunity),
        "by_faculty": dict(by_faculty),
    }


def validate_assets(directory: dict, graph: dict, *, enforce_budgets: bool = False,
                    directory_bytes: bytes | None = None, graph_bytes: bytes | None = None) -> None:
    if directory.get("schema_family") != SCHEMA_FAMILY or graph.get("schema_family") != SCHEMA_FAMILY:
        raise FacultyMatchError("Generated assets have an incompatible schema family")
    if directory.get("schema_version") != DIRECTORY_SCHEMA_VERSION or graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise FacultyMatchError("Generated assets have incompatible schema versions")
    for field in ("generation_id", "asset_version", "projection_fingerprints", "catalog", "faculty_source"):
        if directory.get(field) != graph.get(field):
            raise FacultyMatchError(f"Generated assets disagree on {field}")
    generation_id = directory.get("generation_id")
    if not re.fullmatch(r"[a-f0-9]{64}", str(generation_id or "")):
        raise FacultyMatchError("Generated assets have an invalid generation identity")
    if directory.get("asset_version") != generation_id:
        raise FacultyMatchError("Generated asset_version must equal the immutable generation identity")
    fingerprints = directory.get("projection_fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != {"directory", "graph"}:
        raise FacultyMatchError("Generated assets require both projection fingerprints")
    expected_fingerprints = {
        "directory": _projection_fingerprint(directory),
        "graph": _projection_fingerprint(graph),
    }
    if fingerprints != expected_fingerprints:
        raise FacultyMatchError("Generated projection fingerprints do not match the asset contents")
    expected_generation_id = _generation_id(
        directory["faculty_source"]["sha256"],
        directory["catalog"]["fingerprint"],
        expected_fingerprints,
    )
    if generation_id != expected_generation_id:
        raise FacultyMatchError("Generated identity does not match the directory and graph fingerprints")
    source = directory["faculty_source"]
    if len(directory.get("profiles") or []) != source.get("record_count"):
        raise FacultyMatchError("Directory profile count disagrees with faculty source")
    edges = graph.get("edges") or []
    if len({(edge["faculty_id"], edge["opportunity_id"]) for edge in edges}) != len(edges):
        raise FacultyMatchError("Graph contains duplicate faculty/opportunity edges")
    seen_indexes: list[int] = []
    for opportunity_id, indexes in graph.get("by_opportunity", {}).items():
        if len(indexes) > MAX_FACULTY_PER_OPPORTUNITY:
            raise FacultyMatchError(f"Opportunity {opportunity_id} exceeds the top-N bound")
        for index in indexes:
            if index < 0 or index >= len(edges) or edges[index]["opportunity_id"] != opportunity_id:
                raise FacultyMatchError("Opportunity reverse index is inconsistent")
            seen_indexes.append(index)
    if sorted(seen_indexes) != list(range(len(edges))):
        raise FacultyMatchError("Every edge must appear exactly once in by_opportunity")
    for faculty_id, indexes in graph.get("by_faculty", {}).items():
        if len(indexes) > MAX_OPPORTUNITIES_PER_FACULTY:
            raise FacultyMatchError(f"Faculty {faculty_id} exceeds the top-N bound")
        for index in indexes:
            if index < 0 or index >= len(edges) or edges[index]["faculty_id"] != faculty_id:
                raise FacultyMatchError("Faculty reverse index is inconsistent")
    unrankable = {profile["faculty_id"] for profile in directory["profiles"] if not profile["rankable"]}
    if any(edge["faculty_id"] in unrankable for edge in edges):
        raise FacultyMatchError("Unrankable faculty must not appear in match edges")
    if enforce_budgets:
        if directory_bytes is None or graph_bytes is None:
            raise FacultyMatchError("Asset bytes are required for budget validation")
        measurements = (
            ("directory raw", len(directory_bytes), DIRECTORY_RAW_BUDGET),
            ("directory gzip", len(gzip.compress(directory_bytes, mtime=0)), DIRECTORY_GZIP_BUDGET),
            ("graph raw", len(graph_bytes), GRAPH_RAW_BUDGET),
            ("graph gzip", len(gzip.compress(graph_bytes, mtime=0)), GRAPH_GZIP_BUDGET),
        )
        for label, actual, budget in measurements:
            if actual > budget:
                raise FacultyMatchError(f"{label} size {actual} exceeds budget {budget}")


def _js_bytes(global_name: str, value: dict) -> bytes:
    header = "/* Generated by scripts/faculty_match.py. Do not edit by hand. */\n"
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return f"{header}globalThis.{global_name}={body};\n".encode("utf-8")


_GENERATION_META_RE = re.compile(
    rb'<meta name="hajim-match-generation" content="[a-f0-9]{64}"\s*/?>',
)
_TEAM_DIRECTORY_SCRIPT_RE = re.compile(
    rb'<script src="data/hajim_faculty_directory\.js\?v=[^"]+"></script>',
)


def _versioned_html_bytes(path: str | Path, generation_id: str) -> bytes:
    raw = Path(path).read_bytes()
    meta = f'<meta name="hajim-match-generation" content="{generation_id}" />'.encode("ascii")
    updated, meta_count = _GENERATION_META_RE.subn(meta, raw)
    if meta_count != 1:
        raise FacultyMatchError(f"{path} must contain exactly one Hajim generation meta marker")
    if Path(path).name == "team_match.html":
        script = (
            '<script src="data/hajim_faculty_directory.js?v='
            f'{generation_id}"></script>'
        ).encode("ascii")
        updated, script_count = _TEAM_DIRECTORY_SCRIPT_RE.subn(script, updated)
        if script_count != 1:
            raise FacultyMatchError(f"{path} must contain exactly one Hajim directory script reference")
    return updated


def _atomic_write(path: str | Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def generate_assets(faculty_config_path: str | Path, catalog_path: str | Path,
                    directory_out: str | Path, graph_out: str | Path,
                    version_targets: tuple[str | Path, ...] = ()) -> tuple[dict, dict]:
    config, _ = load_faculty_config(faculty_config_path)
    catalog, catalog_bytes = load_catalog(catalog_path)
    catalog_identity = _catalog_identity(catalog, catalog_bytes)
    directory = build_directory(config, catalog_identity)
    graph = build_graph(config, catalog, catalog_identity)
    projection_fingerprints = {
        "directory": _projection_fingerprint(directory),
        "graph": _projection_fingerprint(graph),
    }
    generation_id = _generation_id(
        config["source"]["sha256"], catalog_identity["fingerprint"], projection_fingerprints,
    )
    identity = {
        "generation_id": generation_id,
        "asset_version": generation_id,
        "projection_fingerprints": projection_fingerprints,
    }
    directory = {
        "schema_family": directory.pop("schema_family"),
        "schema_version": directory.pop("schema_version"),
        **identity,
        **directory,
    }
    graph = {
        "schema_family": graph.pop("schema_family"),
        "schema_version": graph.pop("schema_version"),
        **identity,
        **graph,
    }
    directory_bytes = _js_bytes("HAJIM_FACULTY_DIRECTORY", directory)
    graph_bytes = _js_bytes("FACULTY_MATCHES", graph)
    validate_assets(directory, graph, enforce_budgets=True,
                    directory_bytes=directory_bytes, graph_bytes=graph_bytes)
    versioned_targets = {
        Path(path): _versioned_html_bytes(path, generation_id) for path in version_targets
    }
    _atomic_write(directory_out, directory_bytes)
    _atomic_write(graph_out, graph_bytes)
    for path, content in versioned_targets.items():
        _atomic_write(path, content)
    return directory, graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    match = sub.add_parser("match")
    match.add_argument("--catalog", default="data/opportunities.js")
    match.add_argument("--faculty-config", default="config/hajim_faculty.json")
    match.add_argument("--directory-out", default="data/hajim_faculty_directory.js")
    match.add_argument("--out", default="data/faculty_matches.js")
    match.add_argument("--version-target", action="append", default=[])
    args = parser.parse_args(argv)
    directory, graph = generate_assets(
        args.faculty_config, args.catalog, args.directory_out, args.out,
        tuple(args.version_target),
    )
    directory_bytes = Path(args.directory_out).read_bytes()
    graph_bytes = Path(args.out).read_bytes()
    print(f"Wrote {args.directory_out}: {len(directory['profiles'])} faculty, "
          f"{len(directory_bytes)} raw / {len(gzip.compress(directory_bytes, mtime=0))} gzip bytes")
    print(f"Wrote {args.out}: {len(graph['edges'])} edges, "
          f"{len(graph_bytes)} raw / {len(gzip.compress(graph_bytes, mtime=0))} gzip bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
