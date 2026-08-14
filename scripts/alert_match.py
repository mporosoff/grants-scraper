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
from datetime import date, datetime
from pathlib import Path

from .build_catalog import tokenize
from .currentness import record_is_current
from .search_query import expand_query_groups

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
) -> list[tuple[str, float]]:
    """Resolve exact, prefix, then conservative typo-tolerant index terms."""
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


def hybrid_scores(catalog: dict, query: str) -> tuple[list[float], bool, list[float]]:
    """Return blended scores, query presence, and lexical-only scores.

    Document ids are positions in ``catalog['opportunities']`` (the order the
    index was built in), so ``scores[i]`` scores ``opportunities[i]``.
    """
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
    semantic_scores = [0.0] * document_count
    lexical_coverage = [0] * document_count
    semantic_coverage = [0] * document_count
    required_group_coverage = [0] * document_count
    always_required_coverage = [0] * document_count
    query_groups = expand_query_groups(query, postings)
    records = catalog["opportunities"]
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

    for group in query_groups:
        group_terms = group["terms"]
        group_documents: set[int] = set()
        group_evidence: dict[int, int] = {}
        group_lexical_scores: dict[int, float] = {}
        for query_term, query_weight in group_terms:
            query_term_documents: set[int] = set()
            for term, resolution_weight in _posting_terms(
                query_term, postings, index_terms, terms_by_length
            ):
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
                    group_lexical_scores[document_id] = (
                        group_lexical_scores.get(document_id, 0.0)
                        + term_weight * inverse_frequency * (
                        (frequency * (_K1 + 1)) / denominator
                        )
                    )
                    query_term_documents.add(document_id)
            for document_id in query_term_documents:
                group_evidence[document_id] = group_evidence.get(document_id, 0) + 1
        required_evidence = (
            int(group.get("minimum_evidence") or 0)
            or (2 if len(group_terms) >= 6 else 1)
        )
        alternatives = group.get("evidence_alternatives") or ()
        evidence_phrases = tuple(
            " ".join(tokenize(value))
            for value in group.get("evidence_phrases") or ()
            if tokenize(value)
        )
        group_documents = {
            document_id
            for document_id, evidence in group_evidence.items()
            if evidence >= required_evidence
            and (
                not alternatives
                or any(
                    all(
                        document_id in exact_documents(term)
                        for term in alternative
                    )
                    for alternative in alternatives
                )
            )
            and (
                not evidence_phrases
                or any(
                    f" {phrase} " in f" {document_phrase_text[document_id]} "
                    for phrase in evidence_phrases
                )
            )
        }
        for document_id in group_documents:
            lexical_scores[document_id] += group_lexical_scores.get(document_id, 0.0)
            lexical_coverage[document_id] += 1
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

    minimum_coverage = (
        max(2, math.ceil(len(query_groups) * 0.38))
        if len(query_groups) >= 3
        else 2
        if len(query_groups) >= 2 and any(
            group.get("required_always") for group in query_groups
        )
        else 0
    )
    required_groups = [
        group for group in query_groups if group.get("required_unless_topic")
    ]
    always_required_groups = [
        group for group in query_groups if group.get("required_always")
    ]
    scores = [0.0] * document_count
    for document_id in range(document_count):
        combined = lexical_scores[document_id] + semantic_scores[document_id]
        if combined <= 0:
            continue
        effective_coverage = lexical_coverage[document_id] + 0.55 * semantic_coverage[document_id]
        if (
            minimum_coverage
            and lexical_coverage[document_id] < minimum_coverage
            and document_id not in exact_phrase_documents
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


def bm25_scores(catalog: dict, query: str) -> tuple[list[float], bool]:
    """Compatibility wrapper for callers that consumed the former BM25 API."""
    scores, has_terms, _ = hybrid_scores(catalog, query)
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
) -> list[dict]:
    """Return matching opportunity records, ranked like the site.

    - With a query: hybrid lexical/concept relevance; records that don't match are
      dropped (same as the site hiding zero-score results for a text search).
    - Without a query (filter-only saved search): all records passing the
      filters, newest first.
    """
    records = catalog.get("opportunities") or []
    if query and query.strip():
        scores, has_terms, lexical_scores = hybrid_scores(catalog, query)
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
