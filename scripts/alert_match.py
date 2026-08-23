"""Server-side search matcher for weekly email digests (and other tooling).

The browser application ranks a search with an index that is *prebuilt* by
``build_catalog`` and shipped inside ``data/opportunities.js``. To make a saved
search rank the *same* way in an email digest as it does on the site, this
module reuses that same prebuilt index and the same tokenizer, and mirrors the
hybrid scorer in ``assets/search-retrieval.js`` -- including typo recovery,
catalog-derived topic similarity, multi-term coverage, exact-record boosts, and
the guarded new-relevant priority boost. It also applies the same facet filters the UI
exposes and provides a "new since" helper so a digest can surface only
opportunities posted since the subscriber's last email.

Pure standard library; no third-party dependencies. Import path:
    from scripts.alert_match import load_catalog, search_catalog, is_new_since
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from pathlib import Path

from .build_catalog import tokenize
from .currentness import record_is_current
from .search_query import expand_query_groups
from .search_v2_contract import (
    authoritative_scope_matches,
    controlled_compound_evidence,
    protected_ai_evidence,
    protected_rare_earth_evidence,
    technical_separation_evidence,
    validate_search_v2_catalog,
)

# Facet name -> record field. Mirrors ``facet_counts`` in build_catalog so the
# filters a user picked in the UI mean the same thing here.
FACET_FIELDS: dict[str, str] = {
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

_K1 = 1.2
_B = 0.75
_STALE_UNDATED_MAX_AGE_DAYS = 5 * 366
NEW_RELEVANT_MAX_AGE_DAYS = 14
NEW_RELEVANT_MIN_SCORE_RATIO = 0.2
NEW_RELEVANT_MIN_BOOST = 8.0


def load_catalog(path: str | Path) -> dict:
    """Load a ``data/opportunities.js`` file into a catalog dict.

    The file assigns ``globalThis.GRANT_CATALOG = { ... };`` -- we take the JSON
    object literal between the first ``{`` and the trailing ``;``.
    """
    import json

    text = Path(path).read_text(encoding="utf-8")
    start = text.index("{")
    payload = text[start:].strip().rstrip(";")
    return json.loads(payload)


def _bounded_damerau_levenshtein(left: str, right: str, maximum: int) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > maximum:
        return maximum + 1
    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        row_minimum = left_index
        for right_index, right_character in enumerate(right, start=1):
            substitution = previous[right_index - 1] + (left_character != right_character)
            distance = min(
                current[right_index - 1] + 1,
                previous[right_index] + 1,
                substitution,
            )
            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left_character == right[right_index - 2]
                and left[left_index - 2] == right_character
            ):
                distance = min(distance, previous_previous[right_index - 2] + 1)
            current.append(distance)
            row_minimum = min(row_minimum, distance)
        if row_minimum > maximum:
            return maximum + 1
        previous_previous, previous = previous, current
    return previous[-1]


def _posting_terms(
    query_term: str,
    postings: dict,
    index_terms: list[str],
    terms_by_length: dict[int, list[str]],
    *,
    exact_only: bool = False,
) -> list[tuple[str, float]]:
    """Resolve exact, prefix, then conservative typo-tolerant index terms."""
    if exact_only:
        return [(query_term, 1.0)] if query_term in postings else []
    if query_term in postings:
        return [(query_term, 1.0)]
    if len(query_term) >= 3:
        prefixes = [
            (term, 0.72)
            for term in index_terms
            if term.startswith(query_term)
        ][:12]
        if prefixes:
            return prefixes
    if len(query_term) < 5:
        return []
    maximum = 2 if len(query_term) >= 8 else 1
    candidates: list[tuple[int, float, str]] = []
    for length in range(len(query_term) - maximum, len(query_term) + maximum + 1):
        for term in terms_by_length.get(length, []):
            if term[0] != query_term[0]:
                continue
            distance = _bounded_damerau_levenshtein(query_term, term, maximum)
            if distance > maximum:
                continue
            similarity = 1 - (distance / max(len(query_term), len(term)))
            candidates.append((distance, 0.62 + 0.16 * similarity, term))
    candidates.sort(key=lambda item: (item[0], -item[1], item[2]))
    return [(term, weight) for _, weight, term in candidates[:6]]


def _authoritative_document_scope(record: dict) -> str:
    values: list[str] = []
    for fact in ((record.get("document_evidence") or {}).get("facts") or []):
        if fact.get("type") != "review_criteria":
            continue
        if isinstance(fact.get("value"), str):
            values.append(fact["value"])
        quote = (fact.get("citation") or {}).get("quote")
        if quote:
            values.append(str(quote))
    return " ".join(values)


def _fielded_local_scores(
    catalog: dict,
    query: str,
    specification: dict,
) -> tuple[list[float], bool, list[float]]:
    """BM25F-style local scoring over authoritative fields only.

    This is the server-side saved-search counterpart of the browser fielded
    path. It deliberately ignores configured scientific relationship tables.
    """
    records = catalog.get("opportunities") or []
    document_count = len(records)
    configuration = specification.get("fielded_ranking") or {}
    field_weights = {
        "parent_title": 8.0,
        "child_title": 9.0,
        "child_summary": 4.0,
        "parent_description": 2.0,
        "authoritative_program_area": 6.0,
        "authoritative_document_scope": 3.0,
        **configuration.get("field_weights", {}),
    }
    field_b = {
        "parent_title": 0.2,
        "child_title": 0.15,
        "child_summary": 0.6,
        "parent_description": 0.75,
        "authoritative_program_area": 0.2,
        "authoritative_document_scope": 0.5,
        **configuration.get("field_length_normalization", {}),
    }
    k1 = float(configuration.get("k1") or 1.2)
    coordination_power = float(configuration.get("coordination_power") or 3.0)
    fuzzy_minimum = int(configuration.get("conservative_fuzzy_minimum_length") or 7)
    proximity_window = int(configuration.get("proximity_window") or 32)
    proximity_bonus = float(configuration.get("proximity_bonus") or 3.0)
    phrase_bonus = float(configuration.get("exact_phrase_bonus") or 8.0)
    title_phrase_bonus = float(configuration.get("title_exact_phrase_bonus") or 12.0)

    def fields(record: dict) -> dict[str, str]:
        child = bool(record.get("subtopic_id"))
        if child:
            return {
                "child_title": str(record.get("title") or ""),
                "child_summary": str(record.get("summary") or record.get("description") or ""),
                "authoritative_program_area": " ".join(
                    str(value) for value in record.get("program_area_labels") or []
                ),
            }
        return {
            "parent_title": str(record.get("title") or ""),
            "parent_description": str(record.get("description") or ""),
            "authoritative_program_area": " ".join(
                str(value) for value in (
                    record.get("program_area_labels")
                    or record.get("document_program_areas")
                    or []
                )
            ),
            "authoritative_document_scope": _authoritative_document_scope(record),
        }

    document_fields = [fields(record) for record in records]
    token_counts: list[dict[str, dict[str, int]]] = []
    vocabulary: set[str] = set()
    document_frequency: dict[str, int] = {}
    for row in document_fields:
        counts_by_field: dict[str, dict[str, int]] = {}
        present: set[str] = set()
        for field, value in row.items():
            counts: dict[str, int] = {}
            for term in tokenize(value):
                counts[term] = counts.get(term, 0) + 1
                vocabulary.add(term)
                present.add(term)
                if "-" in term:
                    for part in (item for item in term.split("-") if len(item) > 1):
                        counts[part] = counts.get(part, 0) + 1
                        vocabulary.add(part)
                        present.add(part)
            counts_by_field[field] = counts
        token_counts.append(counts_by_field)
        for term in present:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    average_lengths = {
        field: (
            sum(sum(row.get(field, {}).values()) for row in token_counts)
            / max(1, sum(field in row for row in token_counts))
        )
        for field in field_weights
    }

    query_terms = tokenize(query)
    uppercase_terms = {
        token
        for value in re.findall(r"\b[A-Z][A-Z0-9.-]{1,7}\b", query)
        for token in tokenize(value)
    }
    groups: list[dict] = []
    for source in query_terms:
        alternatives = [[source]]
        parts = [part for part in source.split("-") if len(part) > 1]
        if len(parts) > 1:
            alternatives.append(parts)
        if source in uppercase_terms:
            expansion = tokenize((specification.get("acronym_expansions") or {}).get(source, ""))
            if len(expansion) >= 2:
                alternatives.append(expansion)
        groups.append({
            "source": source,
            "alternatives": alternatives,
            "exact_acronym": source in uppercase_terms,
        })
    if not groups:
        empty = [0.0] * document_count
        return empty, False, empty.copy()

    def resolutions(term: str, exact_only: bool) -> list[tuple[str, float]]:
        if term in vocabulary:
            return [(term, 1.0)]
        if exact_only or len(term) < fuzzy_minimum:
            return []
        values = [
            candidate
            for candidate in vocabulary
            if candidate[0] == term[0]
            and abs(len(candidate) - len(term)) <= 1
            and _bounded_damerau_levenshtein(term, candidate, 1) == 1
        ]
        return [(candidate, 0.72) for candidate in sorted(values)[:2]]

    def exact_acronym_evidence(document_id: int, source: str) -> bool:
        pattern = re.compile(
            rf"(^|[^A-Za-z0-9]){re.escape(source.upper())}"
            rf"(?![A-Za-z0-9]|\s*/\s*[A-Z])"
        )
        return any(pattern.search(value) for value in document_fields[document_id].values())

    def term_score(document_id: int, term: str, exact_only: bool) -> float:
        best = 0.0
        for resolved, resolution_weight in resolutions(term, exact_only):
            weighted_frequency = 0.0
            for field, counts in token_counts[document_id].items():
                frequency = counts.get(resolved, 0)
                if not frequency:
                    continue
                length = sum(counts.values())
                average = max(1.0, average_lengths.get(field, 1.0))
                normalization = 1 - float(field_b.get(field, 0.0)) + float(
                    field_b.get(field, 0.0)
                ) * length / average
                weighted_frequency += float(field_weights.get(field, 0.0)) * frequency / max(
                    0.1, normalization
                )
            if weighted_frequency <= 0:
                continue
            df = document_frequency.get(resolved, 0)
            inverse_frequency = math.log(
                1 + ((document_count - df + 0.5) / (df + 0.5))
            )
            best = max(
                best,
                resolution_weight * inverse_frequency
                * ((weighted_frequency * (k1 + 1)) / (k1 + weighted_frequency)),
            )
        return best

    scores = [0.0] * document_count
    lexical_scores = [0.0] * document_count
    normalized_phrase = " ".join(query_terms)
    strict = 2 <= len(groups) <= 5
    minimum = 1.0 if strict else float(configuration.get("long_query_minimum_coordination") or 0.7)
    for document_id, record in enumerate(records):
        matched = 0
        base = 0.0
        for group in groups:
            best = 0.0
            for alternative in group["alternatives"]:
                if group["exact_acronym"] and len(alternative) == 1 and not exact_acronym_evidence(
                    document_id, group["source"]
                ):
                    continue
                values = [
                    term_score(
                        document_id,
                        term,
                        group["exact_acronym"] and len(alternative) == 1,
                    )
                    for term in alternative
                ]
                if values and all(value > 0 for value in values):
                    best = max(best, sum(values))
            if best > 0:
                matched += 1
                base += best
        lexical_scores[document_id] = base
        coordination = matched / len(groups)
        identifier = str(record.get("opportunity_number") or "").strip().lower()
        if identifier and query.strip().lower() == identifier:
            scores[document_id] = base + 50.0
            continue
        if (
            len(groups) == 1
            and groups[0]["exact_acronym"]
            and not exact_acronym_evidence(document_id, groups[0]["source"])
        ):
            continue
        if coordination < minimum:
            continue
        bonus = 0.0
        for field, value in document_fields[document_id].items():
            field_tokens = tokenize(value)
            if normalized_phrase and normalized_phrase in " ".join(field_tokens):
                bonus = max(
                    bonus,
                    title_phrase_bonus if field.endswith("title") else phrase_bonus,
                )
            positions = [
                index
                for index, term in enumerate(field_tokens)
                if term in set(query_terms)
            ]
            if len(set(field_tokens) & set(query_terms)) == len(set(query_terms)) and positions:
                span = max(positions) - min(positions) + 1
                if span <= proximity_window:
                    bonus = max(bonus, proximity_bonus * (
                        1 - max(0, span - len(groups)) / proximity_window
                    ))
        scores[document_id] = base * coordination ** coordination_power + bonus
    return scores, True, lexical_scores


def hybrid_scores(
    catalog: dict,
    query: str,
    *,
    search_v2: bool = False,
) -> tuple[list[float], bool, list[float]]:
    """Return blended scores, query presence, and lexical-only scores.

    Document ids are positions in ``catalog['opportunities']`` (the order the
    index was built in), so ``scores[i]`` scores ``opportunities[i]``.
    """
    search_v2_spec = validate_search_v2_catalog(catalog) if search_v2 else None
    if (
        search_v2
        and (search_v2_spec.get("fielded_ranking") or {}).get("architecture")
        == "bm25f_passage_coordination"
    ):
        return _fielded_local_scores(catalog, query, search_v2_spec)
    index = catalog["search_index"]
    postings = index["postings"]
    lengths = index["document_lengths"]
    document_count = index["document_count"]
    average_length = index.get("average_document_length") or 1
    index_terms = list(postings.keys())
    terms_by_length: dict[int, list[str]] = {}
    for term in index_terms:
        terms_by_length.setdefault(len(term), []).append(term)

    lexical_scores = [0.0] * document_count
    discovery_scores = [0.0] * document_count
    semantic_scores = [0.0] * document_count
    lexical_coverage = [0] * document_count
    semantic_coverage = [0] * document_count
    required_group_coverage = [0] * document_count
    always_required_coverage = [0] * document_count
    query_groups = expand_query_groups(query, postings, search_v2=search_v2)
    short_complete_coverage = bool(
        search_v2
        and 2 <= len(query_groups) <= 5
    )
    records = catalog["opportunities"]
    scope_matches = (
        authoritative_scope_matches(records, query_groups, search_v2_spec)
        if search_v2
        else {}
    )
    lexical_group_matches = [set() for _ in range(document_count)]
    substantive_group_matches = [set() for _ in range(document_count)]
    broad_grounded_group_matches = [set() for _ in range(document_count)]
    strict_group_indexes = {
        index for index, group in enumerate(query_groups) if group.get("strict_evidence")
    }
    field_token_sets = []
    narrative_token_sets = []
    admission_scope_fields: list[list[tuple[str, list[str]]]] = []

    def scope_tokens(value: str) -> list[str]:
        return [
            part
            for term in tokenize(value)
            for part in (term, *[item for item in term.split("-") if len(item) > 1])
        ]

    def authoritative_document_scope(record: dict) -> str:
        facts = ((record.get("document_evidence") or {}).get("facts") or [])
        values: list[str] = []
        for fact in facts:
            if fact.get("type") != "review_criteria":
                continue
            if isinstance(fact.get("value"), str):
                values.append(fact["value"])
            quote = (fact.get("citation") or {}).get("quote")
            if quote:
                values.append(str(quote))
        return " ".join(values)

    for record in records:
        title_terms = set(tokenize(str(record.get("title") or "")))
        description_terms = set(tokenize(str(record.get("description") or "")))
        citation_terms = set(tokenize(str(record.get("document_search_text") or "")))
        authoritative_scope_terms = set(tokenize(authoritative_document_scope(record)))
        field_token_sets.append(title_terms | description_terms | citation_terms)
        narrative_token_sets.append(
            title_terms | description_terms | authoritative_scope_terms
        )
        admission_scope_fields.append([
            ("parent_title", scope_tokens(str(record.get("title") or ""))),
            ("parent_description", scope_tokens(str(record.get("description") or ""))),
            (
                "authoritative_document_scope",
                scope_tokens(authoritative_document_scope(record)),
            ),
        ])
    source_scope_relationships: dict[str, list[dict]] = {}
    for relationship in (search_v2_spec or {}).get("source_scope_relationships") or []:
        concept_id = str(relationship.get("query_concept_id") or "")
        if concept_id:
            source_scope_relationships.setdefault(concept_id, []).append(relationship)

    def scope_terms_related(query_term: str, source_term: str) -> bool:
        if query_term == source_term:
            return True
        minimum = min(len(query_term), len(source_term))
        return minimum >= 5 and (
            query_term.startswith(source_term) or source_term.startswith(query_term)
        )

    def field_scope_match(
        field_tokens: list[str],
        requirements: list[str],
        *,
        exact_short: bool = False,
    ) -> list[str] | None:
        maximum_span = len(field_tokens) if len(requirements) <= 1 else 12
        for start in range(len(field_tokens)):
            window = field_tokens[start:start + maximum_span]
            matches: list[str] = []
            for requirement in requirements:
                matched = next((
                    token for token in window
                    if (
                        token == requirement
                        if exact_short and len(requirement) <= 4
                        else scope_terms_related(requirement, token)
                    )
                ), None)
                if matched is None:
                    break
                matches.append(matched)
            if len(matches) == len(requirements):
                return list(dict.fromkeys(matches))
        return None

    def source_grounded_role_evidence(document_id: int, group: dict) -> bool:
        if group.get("exact_indexed_acronym"):
            acronym = str(group.get("source") or "").upper()
            pattern = re.compile(
                rf"(^|[^A-Za-z0-9]){re.escape(acronym)}"
                rf"(?![A-Za-z0-9]|\s*/\s*[A-Z])"
            )
            if not any(
                pattern.search(str(value or ""))
                for field, value in (
                    ("parent_title", records[document_id].get("title")),
                    ("parent_description", records[document_id].get("description")),
                    (
                        "authoritative_document_scope",
                        authoritative_document_scope(records[document_id]),
                    ),
                )
            ):
                return False
        requirements = scope_tokens(str(group.get("source") or ""))
        for _field, tokens in admission_scope_fields[document_id]:
            if requirements and field_scope_match(
                tokens,
                requirements,
                exact_short=bool(group.get("exact_indexed_acronym")),
            ):
                return True
        for relationship in source_scope_relationships.get(
            str(group.get("concept_id") or ""),
            [],
        ):
            for alternative in relationship.get("source_alternatives") or []:
                evidence_class_requirements = (
                    relationship.get("evidence_class_requirements") or {}
                ).get(str(group.get("evidence_class") or ""), [])
                if evidence_class_requirements and not any(
                    term in evidence_class_requirements for term in alternative
                ):
                    continue
                alternative_requirements = scope_tokens(" ".join(alternative or []))
                for _field, tokens in admission_scope_fields[document_id]:
                    if alternative_requirements and field_scope_match(
                        tokens,
                        alternative_requirements,
                    ):
                        return True
        return False
    document_topics = [list(dict.fromkeys(record.get("topic_areas") or [])) for record in records]
    document_phrase_text = [
        " ".join(tokenize(" ".join([
            str(record.get("title") or ""),
            str(record.get("opportunity_number") or ""),
            str(record.get("description") or "")[:5_000],
            str(record.get("document_search_text") or "")[:16_000],
            *[str(item) for item in record.get("topic_areas") or []],
        ])))
        for record in records
    ]
    document_phrase_tokens = [value.split() for value in document_phrase_text]
    topic_documents: dict[str, list[int]] = {}
    for document_id, topics in enumerate(document_topics):
        for topic in topics:
            topic_documents.setdefault(str(topic), []).append(document_id)
    exact_document_cache: dict[str, set[int]] = {}

    def exact_documents(term: str) -> set[int]:
        if term not in exact_document_cache:
            values = postings.get(term) or []
            exact_document_cache[term] = set(values[::2])
        return exact_document_cache[term]

    def terms_within_window(
        document_id: int,
        terms: tuple[str, ...] | list[str],
        maximum_span: int,
    ) -> bool:
        required = tuple(dict.fromkeys(term for term in terms if term))
        span = max(len(required), int(maximum_span or len(required)))
        tokens = document_phrase_tokens[document_id]
        for start, token in enumerate(tokens):
            if token not in required:
                continue
            if set(required) <= set(tokens[start:start + span]):
                return True
        return False

    for group_index, group in enumerate(query_groups):
        group_terms = group["terms"]
        group_documents: set[int] = set()
        group_evidence: dict[int, int] = {}
        group_lexical_scores: dict[int, float] = {}
        group_term_scores: dict[int, dict[str, float]] = {}
        for query_term, query_weight in group_terms:
            query_term_documents: set[int] = set()
            for term, resolution_weight in _posting_terms(
                query_term,
                postings,
                index_terms,
                terms_by_length,
                exact_only=bool(
                    group.get("exact_indexed_acronym")
                    and query_term == group["source"]
                ),
            ):
                # Typo recovery applies to the user's term, not to controlled
                # synonym/word-family alternatives inside the same concept.
                if query_term != group["source"] and term != query_term:
                    continue
                values = postings[term]
                document_frequency = len(values) // 2
                inverse_frequency = math.log(
                    1 + ((document_count - document_frequency + 0.5) / (document_frequency + 0.5))
                )
                term_weight = query_weight * resolution_weight
                for cursor in range(0, len(values), 2):
                    document_id = values[cursor]
                    frequency = values[cursor + 1]
                    denominator = frequency + _K1 * (
                        1 - _B + _B * (lengths[document_id] / average_length)
                    )
                    contribution = term_weight * inverse_frequency * (
                        (frequency * (_K1 + 1)) / denominator
                    )
                    group_lexical_scores[document_id] = (
                        group_lexical_scores.get(document_id, 0.0)
                        + contribution
                    )
                    term_scores = group_term_scores.setdefault(document_id, {})
                    term_scores[term] = term_scores.get(term, 0.0) + contribution
                    query_term_documents.add(document_id)
            for document_id in query_term_documents:
                group_evidence[document_id] = group_evidence.get(document_id, 0) + 1
        required_evidence = (
            int(group.get("minimum_evidence") or 0)
            or (2 if len(group_terms) >= 6 else 1)
        )
        for document_id, value in group_lexical_scores.items():
            discovery_scores[document_id] += value
        alternatives = group.get("evidence_alternatives") or ()
        evidence_phrases = tuple(
            " ".join(tokenize(value))
            for value in group.get("evidence_phrases") or ()
            if tokenize(value)
        )
        evidence_windows = tuple(group.get("evidence_windows") or ())
        evidence_mode = group.get("evidence_mode") or "all"

        def has_required_evidence(document_id: int) -> bool:
            if search_v2 and group.get("exact_indexed_acronym"):
                acronym = str(group.get("source") or "").upper()
                pattern = re.compile(
                    rf"(^|[^A-Za-z0-9]){re.escape(acronym)}"
                    rf"(?![A-Za-z0-9]|\s*/\s*[A-Z])"
                )
                source = " ".join((
                    str(records[document_id].get("title") or ""),
                    str(records[document_id].get("description") or ""),
                    authoritative_document_scope(records[document_id]),
                ))
                if not pattern.search(source):
                    return False
            if search_v2 and group.get("evidence_policy") == "source_grounded_only":
                return False
            if search_v2 and group.get("evidence_policy") == "protected_rare_earth":
                return protected_rare_earth_evidence(records[document_id]) is not None
            if search_v2 and group.get("evidence_policy") == "protected_ai":
                return protected_ai_evidence(records[document_id]) is not None
            if search_v2 and group.get("evidence_policy") == "protected_ai_security":
                text = " ".join((
                    str(records[document_id].get("title") or ""),
                    str(records[document_id].get("description") or ""),
                ))
                pattern = (
                    r"\b(?:secure|security|cybersecurity|adversarial|attack|mitigation)\b"
                    if group.get("evidence_class") == "security"
                    else r"\b(?:secure|security|cybersecurity|adversarial|robustness|robust|"
                         r"resilience|resilient|attack|mitigation|trustworthy)\b"
                )
                return re.search(pattern, text, re.I) is not None
            if search_v2 and group.get("evidence_policy") == "technical_separation":
                return technical_separation_evidence(records[document_id]) is not None
            if search_v2 and group.get("evidence_policy") == "controlled_compound":
                return controlled_compound_evidence(
                    records[document_id],
                    tuple(group.get("evidence_phrases") or ()),
                ) is not None
            checks: list[bool] = []
            if alternatives:
                checks.append(any(
                    all(
                        document_id in exact_documents(term)
                        for term in alternative
                    )
                    for alternative in alternatives
                ))
            if evidence_phrases:
                checks.append(any(
                    f" {phrase} " in f" {document_phrase_text[document_id]} "
                    for phrase in evidence_phrases
                ))
            if evidence_windows:
                checks.append(any(
                    terms_within_window(
                        document_id,
                        window.get("terms") or (),
                        int(window.get("maximum_span") or 0),
                    )
                    for window in evidence_windows
                ))
            return not checks or (
                any(checks) if evidence_mode == "any" else all(checks)
            )

        group_documents = {
            document_id
            for document_id, evidence in group_evidence.items()
            if evidence >= required_evidence
            and has_required_evidence(document_id)
        }
        if short_complete_coverage:
            group_documents = {
                document_id
                for document_id in group_documents
                if len(
                    set(group_term_scores.get(document_id, {}))
                    & field_token_sets[document_id]
                ) >= required_evidence
            }
        for document_id in group_documents:
            substantive_group_matches[document_id].add(group_index)
            if len(
                set(group_term_scores.get(document_id, {}))
                & narrative_token_sets[document_id]
            ) >= required_evidence:
                broad_grounded_group_matches[document_id].add(group_index)
            contribution = group_lexical_scores.get(document_id, 0.0)
            if search_v2 and group.get("saturate_concept"):
                term_contributions = sorted(
                    group_term_scores.get(document_id, {}).values(),
                    reverse=True,
                )
                if term_contributions:
                    contribution = term_contributions[0] + 0.35 * (
                        term_contributions[1] if len(term_contributions) > 1 else 0.0
                    )
            lexical_scores[document_id] += contribution
            lexical_coverage[document_id] += 1
            lexical_group_matches[document_id].add(group_index)
            if group.get("required_unless_topic"):
                required_group_coverage[document_id] += 1
            if group.get("required_always"):
                always_required_coverage[document_id] += 1

        if len(group_documents) < 2:
            continue
        topic_hits: dict[str, int] = {}
        for document_id in group_documents:
            for topic in document_topics[document_id]:
                topic_hits[str(topic)] = topic_hits.get(str(topic), 0) + 1
        required_hits = max(2, math.ceil(len(group_documents) * 0.06))
        inferred: list[tuple[float, str]] = []
        for topic, hits in topic_hits.items():
            topic_size = len(topic_documents.get(topic, []))
            hit_rate = hits / len(group_documents)
            base_rate = topic_size / max(1, document_count)
            lift = hit_rate / max(0.015, base_rate)
            if hits < required_hits or hit_rate < 0.16 or lift < 1.35:
                continue
            confidence = hit_rate * math.log1p(lift) * (1 - min(0.65, base_rate))
            inferred.append((confidence, topic))
        inferred.sort(key=lambda item: (-item[0], item[1]))
        semantic_group_scores: dict[int, float] = {}
        for confidence, topic in inferred[:3]:
            topic_score = 2.6 * confidence
            for document_id in topic_documents.get(topic, []):
                semantic_group_scores[document_id] = max(
                    topic_score, semantic_group_scores.get(document_id, 0.0)
                )
        for document_id, value in semantic_group_scores.items():
            semantic_scores[document_id] += value
            if document_id not in group_documents:
                semantic_coverage[document_id] += 1

    if search_v2 and short_complete_coverage:
        for document_id in range(document_count):
            if (
                discovery_scores[document_id] + semantic_scores[document_id] <= 0
                and document_id not in scope_matches
            ):
                continue
            for group_index, group in enumerate(query_groups):
                if group_index in substantive_group_matches[document_id]:
                    continue
                if not source_grounded_role_evidence(document_id, group):
                    continue
                lexical_group_matches[document_id].add(group_index)
                substantive_group_matches[document_id].add(group_index)
                broad_grounded_group_matches[document_id].add(group_index)
                lexical_coverage[document_id] += 1
                lexical_scores[document_id] += 0.35
                if group.get("required_unless_topic"):
                    required_group_coverage[document_id] += 1
                if group.get("required_always"):
                    always_required_coverage[document_id] += 1

    scope_entailment_score = max(
        0.01,
        float((search_v2_spec or {}).get("scope_entailment_score") or 1.0),
    )
    for document_id, match in scope_matches.items():
        covered_concepts = set(match.get("covered_concepts") or [])
        for group_index, group in enumerate(query_groups):
            if group.get("concept_id") not in covered_concepts:
                continue
            if group_index not in lexical_group_matches[document_id]:
                lexical_group_matches[document_id].add(group_index)
                lexical_coverage[document_id] += 1
                if group.get("required_unless_topic"):
                    required_group_coverage[document_id] += 1
                if group.get("required_always"):
                    always_required_coverage[document_id] += 1
                substantive_group_matches[document_id].add(group_index)
                broad_grounded_group_matches[document_id].add(group_index)
        lexical_scores[document_id] += scope_entailment_score

    import unicodedata

    exact_phrase_documents: set[int] = set()
    phrase = unicodedata.normalize("NFKC", query).strip().lower()
    if len(phrase) >= 4:
        for i, record in enumerate(records):
            title = (record.get("title") or "").lower()
            if phrase in title:
                lexical_scores[i] += 24 if title == phrase else 12
                exact_phrase_documents.add(i)
            if (record.get("opportunity_number") or "").lower() == phrase:
                lexical_scores[i] += 50
                exact_phrase_documents.add(i)

    phrase_tokens = tokenize(query)[:12]
    query_trigrams = [
        " ".join(phrase_tokens[index:index + 3])
        for index in range(max(0, len(phrase_tokens) - 2))
        if all(len(term) >= 3 for term in phrase_tokens[index:index + 3])
    ]
    for document_id, source_text in enumerate(document_phrase_text):
        for trigram in query_trigrams:
            if trigram in source_text:
                lexical_scores[document_id] += 40

    # Keep candidate admission lexical. Catalog topics can rerank a record
    # that already satisfies the query, but cannot create topic-wide matches.
    # Two concepts are conjunctive; longer searches keep a 60% coverage floor.
    protected_complete_coverage = search_v2 and any(
        group.get("evidence_policy") == "protected_rare_earth"
        for group in query_groups
    )
    minimum_coverage = (
        0
        if not query_groups
        else len(query_groups)
        if protected_complete_coverage or short_complete_coverage
        else len(query_groups)
        if len(query_groups) <= 2
        else math.ceil(len(query_groups) * 0.6)
    )
    required_groups = [
        group for group in query_groups if group.get("required_unless_topic")
    ]
    always_required_groups = [
        group for group in query_groups if group.get("required_always")
    ]
    scores = [0.0] * document_count

    def stale_undated(record: dict) -> bool:
        if record.get("rolling") or record.get("close_date") or record.get("archive_date"):
            return False
        if str(record.get("status") or "").lower() not in {"posted", "forecasted"}:
            return False
        try:
            posted = datetime.strptime(str(record.get("posted_date") or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            return False
        return (date.today() - posted).days > _STALE_UNDATED_MAX_AGE_DAYS

    for document_id in range(document_count):
        combined = lexical_scores[document_id] + semantic_scores[document_id]
        if combined <= 0:
            continue
        if search_v2 and stale_undated(records[document_id]):
            continue
        effective_coverage = lexical_coverage[document_id] + 0.55 * semantic_coverage[document_id]
        if (
            minimum_coverage
            and lexical_coverage[document_id] < minimum_coverage
            and document_id not in exact_phrase_documents
        ):
            continue
        if (
            short_complete_coverage
            and len(substantive_group_matches[document_id]) < len(query_groups)
            and document_id not in exact_phrase_documents
            and document_id not in scope_matches
        ):
            continue
        broad_title = str(records[document_id].get("title") or "")
        if (
            short_complete_coverage
            and re.search(
                r"broad agency announcement|\bbaa\b|continuation of solicitation|"
                r"office of science financial assistance|long[\s-]?range|research announcement|"
                r"research interests of|established program to stimulate competitive research|"
                r"research collaboration|\broses\b|omnibus|unsolicited proposal|open topic|"
                r"financial assistance program|annual program statement|office[ -]wide|"
                r"open[ -]scope solicitation",
                broad_title,
                re.I,
            )
            and any(
                group_index not in broad_grounded_group_matches[document_id]
                for group_index in strict_group_indexes
            )
            and document_id not in exact_phrase_documents
            and document_id not in scope_matches
        ):
            continue
        if (
            required_groups
            and required_group_coverage[document_id] < len(required_groups)
            and not all(
                group["required_unless_topic"] in document_topics[document_id]
                for group in required_groups
            )
        ):
            continue
        if (
            always_required_groups
            and always_required_coverage[document_id] < len(always_required_groups)
        ):
            continue
        coverage_ratio = min(1.0, effective_coverage / len(query_groups)) if query_groups else 0.0
        scores[document_id] = combined * (0.78 + 0.5 * coverage_ratio)

    return scores, bool(query_groups), lexical_scores


def bm25_scores(
    catalog: dict,
    query: str,
    *,
    search_v2: bool = False,
) -> tuple[list[float], bool]:
    """Compatibility wrapper for callers that consumed the former BM25 API."""
    scores, has_terms, _ = hybrid_scores(catalog, query, search_v2=search_v2)
    return scores, has_terms


def _facet_values(record: dict, field: str) -> set[str]:
    value = record.get(field)
    if field == "source_facet" and field not in record:
        value = record.get("source")
    if isinstance(value, list):
        return {str(v) for v in value}
    if value is None or value == "":
        return set()
    return {str(value)}


def matches_filters(record: dict, filters: dict | None) -> bool:
    """AND across facets, OR within a facet -- the standard faceted-search rule."""
    if not filters:
        return True
    for facet, selected in filters.items():
        if not selected:
            continue
        field = FACET_FIELDS.get(facet, facet)
        chosen = {str(v) for v in selected}
        if not (chosen & _facet_values(record, field)):
            return False
    return True


def parse_date(value) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _recency_ordinal(record: dict) -> int:
    d = parse_date(record.get("posted_date")) or parse_date(record.get("last_updated"))
    return d.toordinal() if d else 0


def announcement_age_days(record: dict, as_of: date) -> int | None:
    """Return the age of a newly discoverable announcement, if known."""
    announced = parse_date(record.get("posted_date")) or parse_date(
        record.get("source_first_seen_date")
    )
    if announced is None or announced > as_of:
        return None
    return (as_of - announced).days


def new_relevant_boost(
    record: dict,
    score: float,
    peak_score: float,
    as_of: date,
) -> float:
    """Prioritize a recent record only when it has credible base relevance.

    Records posted in the last two weeks must first reach 20% of the strongest
    pre-boost match. Qualifying records receive a boost larger than the peak
    base score, so they appear ahead of older matches while weakly related new
    records remain in their ordinary relevance position.
    """
    if score <= 0 or peak_score <= 0:
        return 0.0
    if score < peak_score * NEW_RELEVANT_MIN_SCORE_RATIO:
        return 0.0
    age = announcement_age_days(record, as_of)
    if age is None or age > NEW_RELEVANT_MAX_AGE_DAYS:
        return 0.0
    freshness = 1 - (age / (NEW_RELEVANT_MAX_AGE_DAYS + 1))
    return peak_score + max(
        NEW_RELEVANT_MIN_BOOST,
        peak_score * 0.15 * freshness,
    )


def is_new_since(record: dict, since: date) -> bool:
    """True if a record became discoverable on or after a date watermark.

    The watermark has day precision, so the comparison is inclusive. Stable
    opportunity IDs in the digest state prevent duplicates while ensuring a
    notice added later on the same day as a prior send is not missed.
    """
    d = (
        parse_date(record.get("posted_date"))
        or parse_date(record.get("source_first_seen_date"))
        or parse_date(record.get("last_updated"))
    )
    return d is not None and d >= since


def search_catalog(
    catalog: dict,
    query: str = "",
    filters: dict | None = None,
    top_k: int | None = None,
    as_of: date | None = None,
    *,
    search_v2: bool = False,
) -> list[dict]:
    """Return matching opportunity records, ranked like the site.

    - With a query: hybrid lexical/concept relevance; records that don't match are
      dropped (same as the site hiding zero-score results for a text search).
    - Without a query (filter-only saved search): all records passing the
      filters, newest first.
    """
    records = catalog.get("opportunities") or []
    if query and query.strip():
        scores, has_terms, lexical_scores = hybrid_scores(
            catalog,
            query,
            search_v2=search_v2,
        )
    else:
        scores, lexical_scores, has_terms = [0.0] * len(records), [0.0] * len(records), False

    ranked: list[tuple[float, int, dict, float]] = []
    for i, record in enumerate(records):
        if not record_is_current(record, as_of)[0]:
            continue
        if not matches_filters(record, filters):
            continue
        if has_terms and scores[i] <= 0:
            continue
        ranked.append((scores[i], _recency_ordinal(record), record, lexical_scores[i]))

    if has_terms and ranked:
        peak_lexical_score = max(lexical for _, _, _, lexical in ranked)
        ranking_date = as_of or date.today()
        ranked = [
            (
                score + new_relevant_boost(
                    record, lexical_score, peak_lexical_score, ranking_date
                ),
                recency,
                record,
                lexical_score,
            )
            for score, recency, record, lexical_score in ranked
        ]

    ranked.sort(key=lambda item: (-item[0], -item[1], (item[2].get("title") or "")))
    results = [record for _, _, record, _ in ranked]
    return results[:top_k] if top_k else results
