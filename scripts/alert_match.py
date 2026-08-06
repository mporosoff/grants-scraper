"""Server-side search matcher for weekly email digests (and other tooling).

The browser application ranks a search with a BM25 index that is *prebuilt* by
``build_catalog`` and shipped inside ``data/opportunities.js``. To make a saved
search rank the *same* way in an email digest as it does on the site, this
module reuses that same prebuilt index and the same tokenizer, and mirrors the
browser scorer in ``assets/app.js`` (``bm25Scores``) term for term -- including
prefix expansion, title/opportunity-number phrase boosts, and the guarded
new-relevant priority boost. It also applies the same facet filters the UI
exposes and provides a "new since" helper so a digest can surface only
opportunities posted since the subscriber's last email.

Pure standard library; no third-party dependencies. Import path:
    from scripts.alert_match import load_catalog, search_catalog, is_new_since
"""

from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path

from .build_catalog import tokenize  # identical tokenizer -> identical terms
from .currentness import record_is_current

# Facet name -> record field. Mirrors ``facet_counts`` in build_catalog so the
# filters a user picked in the UI mean the same thing here.
FACET_FIELDS: dict[str, str] = {
    "status": "status",
    "source_type": "source_type",
    "source": "source",
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


def _posting_terms(query_term: str, postings: dict, index_terms: list[str]) -> list[str]:
    """Exact term if indexed, else short prefix expansion -- mirrors app.js."""
    if query_term in postings:
        return [query_term]
    if len(query_term) < 3:
        return []
    return [term for term in index_terms if term.startswith(query_term)][:12]


def bm25_scores(catalog: dict, query: str) -> tuple[list[float], bool]:
    """Return (per-document scores, has_query_terms), matching app.js bm25Scores.

    Document ids are positions in ``catalog['opportunities']`` (the order the
    index was built in), so ``scores[i]`` scores ``opportunities[i]``.
    """
    index = catalog["search_index"]
    postings = index["postings"]
    lengths = index["document_lengths"]
    document_count = index["document_count"]
    average_length = index.get("average_document_length") or 1
    index_terms = list(postings.keys())

    scores = [0.0] * document_count
    query_terms = list(dict.fromkeys(tokenize(query)))

    for query_term in query_terms:
        for term in _posting_terms(query_term, postings, index_terms):
            values = postings[term]
            document_frequency = len(values) // 2
            inverse_frequency = math.log(
                1 + ((document_count - document_frequency + 0.5) / (document_frequency + 0.5))
            )
            prefix_weight = 1.0 if term == query_term else 0.72
            for cursor in range(0, len(values), 2):
                document_id = values[cursor]
                frequency = values[cursor + 1]
                denominator = frequency + _K1 * (1 - _B + _B * (lengths[document_id] / average_length))
                scores[document_id] += prefix_weight * inverse_frequency * (
                    (frequency * (_K1 + 1)) / denominator
                )

    phrase = query.strip().lower()
    if len(phrase) >= 4:
        for i, record in enumerate(catalog["opportunities"]):
            if phrase in (record.get("title") or "").lower():
                scores[i] += 12
            if (record.get("opportunity_number") or "").lower() == phrase:
                scores[i] += 30

    return scores, len(query_terms) > 0


def _facet_values(record: dict, field: str) -> set[str]:
    value = record.get(field)
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

    - With a query: BM25 relevance, records that don't match the query are
      dropped (same as the site hiding zero-score results for a text search).
    - Without a query (filter-only saved search): all records passing the
      filters, newest first.
    """
    records = catalog.get("opportunities") or []
    if query and query.strip():
        scores, has_terms = bm25_scores(catalog, query)
    else:
        scores, has_terms = [0.0] * len(records), False

    ranked: list[tuple[float, int, dict]] = []
    for i, record in enumerate(records):
        if not record_is_current(record, as_of)[0]:
            continue
        if not matches_filters(record, filters):
            continue
        if has_terms and scores[i] <= 0:
            continue
        ranked.append((scores[i], _recency_ordinal(record), record))

    if has_terms and ranked:
        peak_score = max(score for score, _, _ in ranked)
        ranking_date = as_of or date.today()
        ranked = [
            (
                score + new_relevant_boost(record, score, peak_score, ranking_date),
                recency,
                record,
            )
            for score, recency, record in ranked
        ]

    ranked.sort(key=lambda item: (-item[0], -item[1], (item[2].get("title") or "")))
    results = [record for _, _, record in ranked]
    return results[:top_k] if top_k else results
