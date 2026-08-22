"""Shared deterministic search-v2 concept and scope-entailment contract."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "search_v2.json"
RETRIEVAL_API_CONTRACT_VERSION = 2
SCIENTIFIC_CONCEPT_ROLES = {"target", "method"}
TECHNICAL_SCOPE_RE = re.compile(
    r"\b(?:research|r&d|scientific|hypothesis|experimental|computational|"
    r"chemical|materials?|separat(?:e|ion|ions)|extract(?:ion)?|process(?:ing)?|"
    r"recover(?:y)?|purif(?:y|ication)|hydrometallurgy|refin(?:e|ing)|synthesis)\b",
    re.I,
)
NON_RESEARCH_SCOPE_RE = re.compile(
    r"\b(?:workshops?|training|advocacy|policy recommendations?|public diplomacy|participants?)\b",
    re.I,
)
STRONG_RESEARCH_RE = re.compile(
    r"\b(?:research|r&d|fundamental|hypothesis|experimental|computational)\b",
    re.I,
)
NAMED_RARE_EARTH_RE = re.compile(
    r"\brare[\s-]+earth(?:[\s-]+elements?)?\b|\blanthanides?\b|\bscandium\b|\byttrium\b",
    re.I,
)
RARE_EARTH_ACRONYM_RE = re.compile(
    r"\bREEs?\b|\bR\s*\.\s*E\s*\.\s*E(?:\s*\.)?s?(?![A-Za-z0-9])"
)
RARE_EARTH_ACRONYM_CONTEXT_RE = re.compile(
    r"\bcritical[\s-]+minerals?\b|\bseparat(?:e|ion|ions)\b|\bextract(?:ion)?\b|"
    r"\brecover(?:y)?\b|\bhydrometallurgy\b|\brefin(?:e|ing)\b",
    re.I,
)


@lru_cache(maxsize=1)
def load_search_v2_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def validate_search_v2_catalog(catalog: dict, *, role: str = "parent") -> dict:
    specification = load_search_v2_config()
    compatibility = specification.get("compatibility") or {}
    expected_schema = int(
        compatibility[
            "child_catalog_schema_version"
            if role == "child"
            else "parent_catalog_schema_version"
        ]
    )
    if int(catalog.get("schema_version") or 0) != expected_schema:
        raise ValueError(f"Search v2 rejected an incompatible {role} catalog schema.")
    if RETRIEVAL_API_CONTRACT_VERSION != int(
        compatibility.get("retrieval_api_contract_version") or 0
    ):
        raise ValueError("Search v2 retrieval code is incompatible with its concept contract.")
    index = catalog.get("search_index") or {}
    if (index.get("algorithm") or "bm25") != compatibility.get("search_index_algorithm"):
        raise ValueError("Search v2 rejected an incompatible search-index algorithm.")
    if int(index.get("document_count") or 0) != len(catalog.get("opportunities") or []):
        raise ValueError("Search v2 rejected a mixed catalog/search-index asset set.")
    return specification


def _admission_fields(record: dict) -> list[tuple[str, str]]:
    if record.get("subtopic_id"):
        return [
            ("child_title", str(record.get("title") or "")),
            ("child_summary", str(record.get("description") or record.get("summary") or "")),
            (
                "authoritative_program_area",
                " ".join(str(item) for item in record.get("program_area_labels") or []),
            ),
        ]
    return [
        ("parent_title", str(record.get("title") or "")),
        ("parent_description", str(record.get("description") or "")),
        ("citation_source_evidence", str(record.get("document_search_text") or "")),
    ]


def protected_rare_earth_evidence(record: dict) -> dict | None:
    fields = _admission_fields(record)
    matching_fields: list[str] = []
    for field, text in fields:
        named_target = bool(NAMED_RARE_EARTH_RE.search(text))
        acronym = bool(RARE_EARTH_ACRONYM_RE.search(text))
        acronym_context = bool(RARE_EARTH_ACRONYM_CONTEXT_RE.search(text))
        if named_target or (acronym and acronym_context):
            matching_fields.append(field)
    if not matching_fields:
        return None
    substantive = " ".join(text for _, text in fields)
    if not TECHNICAL_SCOPE_RE.search(substantive):
        return None
    if NON_RESEARCH_SCOPE_RE.search(substantive) and not STRONG_RESEARCH_RE.search(substantive):
        return None
    return {
        "policy": "protected_rare_earth",
        "fields": list(dict.fromkeys(matching_fields)),
    }


def authoritative_scope_matches(
    records: list[dict],
    groups: list[dict],
    specification: dict,
) -> dict[int, dict]:
    scientific_concepts = list(dict.fromkeys(
        str(group.get("concept_id") or "")
        for group in groups
        if group.get("role") in SCIENTIFIC_CONCEPT_ROLES and group.get("concept_id")
    ))
    if not scientific_concepts:
        return {}
    record_by_id = {
        str(record.get("opportunity_id") or record.get("opportunity_number") or ""): index
        for index, record in enumerate(records)
    }
    matches: dict[int, dict] = {}
    for entry in specification.get("authoritative_scope_entailments") or []:
        supported = set(entry.get("supported_query_concepts") or [])
        required = entry.get("required_query_concepts") or []
        if not all(concept in scientific_concepts for concept in required):
            continue
        if (
            specification.get("scope_entailment_requires_complete_scientific_query")
            and any(concept not in supported for concept in scientific_concepts)
        ):
            continue
        document_id = record_by_id.get(str(entry.get("parent_id") or ""))
        if document_id is None:
            continue
        matches[document_id] = {
            **entry,
            "covered_concepts": [
                concept for concept in scientific_concepts if concept in supported
            ],
        }
    return matches
