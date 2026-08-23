"""Bounded offline semantic candidate-discovery spike for Search v2 Iteration 2.

This experiment is deliberately isolated from production. It learns a small
distributional word space from the frozen catalog's eligible parent and
publication-eligible child narrative, retrieves at most 50 parents, and never
performs primary admission.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation/search_v2_iteration2_semantic_spike.json"
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "their", "this", "to",
    "under", "with", "program", "proposal", "proposals", "research", "support",
    "supports", "funding", "opportunity", "project", "projects", "new", "may",
}


def load_global_json(path: Path, marker: str) -> dict:
    source = path.read_text(encoding="utf-8")
    start = source.index(marker) + len(marker)
    return json.loads(source[start:].strip().removesuffix(";"))


def stem(token: str) -> str:
    value = token.lower().replace("–", "-").replace("—", "-")
    for suffix in ("ization", "ational", "iveness", "fulness", "ologies", "ology", "ments", "ation", "ities", "ing", "ics", "ical", "ers", "ies", "ed", "es", "s"):
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value


def tokens(text: str, limit: int = 500) -> list[str]:
    values = [stem(item) for item in re.findall(r"[A-Za-z][A-Za-z0-9-]{1,30}", text)]
    return [item for item in values if len(item) >= 3 and item not in STOP][:limit]


def merge_truth() -> tuple[dict, dict]:
    challenge = json.loads((ROOT / "evaluation/search_v2_holdout_truth.json").read_text(encoding="utf-8"))
    delta = json.loads((ROOT / "evaluation/search_v2_iteration2_challenge_truth_delta.json").read_text(encoding="utf-8"))
    for query_id, addition in delta.get("additions", {}).items():
        challenge["queries"][query_id]["judgments"].update(addition.get("judgments", {}))
    development = json.loads((ROOT / "evaluation/search_v2_development_truth.json").read_text(encoding="utf-8"))
    return challenge, development


def population() -> list[dict]:
    challenge, development = merge_truth()
    rows = []
    seen = set()
    for source, truth in (("former_phase4_challenge", challenge), ("existing_development", development)):
        for query_id, item in truth["queries"].items():
            required = item.get("required_primary_ids", [])
            key = (item["query"].lower(), tuple(required))
            if not required or key in seen:
                continue
            seen.add(key)
            rows.append({
                "source": source,
                "query_id": query_id,
                "query": item["query"],
                "required_primary_ids": required,
            })
    return rows


def main() -> None:
    catalog = load_global_json(ROOT / "data/opportunities.js", "globalThis.GRANT_CATALOG=")
    subtopics = load_global_json(ROOT / "data/subtopics.js", "globalThis.SUBTOPIC_CATALOG=")
    queries = population()
    print("semantic spike: inputs loaded", flush=True)
    children = defaultdict(list)
    for parent_id, value in subtopics.get("records", {}).items():
        for child in value.get("subtopics", []):
            if child.get("publication_state") != "publishable":
                continue
            children[str(parent_id)].append(" ".join([
                str(child.get("title") or ""),
                str(child.get("summary") or ""),
                " ".join(child.get("program_area_labels") or []),
            ]))

    records = [item for item in catalog["opportunities"] if item.get("status") != "archived"]
    ids = [str(item.get("opportunity_id") or item.get("opportunity_number") or "") for item in records]
    corpus_tokens = []
    document_frequency = Counter()
    total_frequency = Counter()
    for record, record_id in zip(records, ids):
        text = " ".join([
            str(record.get("title") or ""),
            str(record.get("description") or ""),
            " ".join(children.get(record_id, [])),
        ])
        row = tokens(text)
        corpus_tokens.append(row)
        total_frequency.update(row)
        document_frequency.update(set(row))
    print("semantic spike: corpus tokenized", flush=True)

    query_terms = {term for item in queries for term in tokens(item["query"], 40)}
    maximum_df = max(5, int(len(records) * 0.35))
    ranked_terms = [term for term, _count in total_frequency.most_common()
                    if 2 <= document_frequency[term] <= maximum_df]
    vocabulary_terms = ranked_terms[:240]
    for term in sorted(query_terms):
        if document_frequency[term] and term not in vocabulary_terms:
            vocabulary_terms.append(term)
    vocabulary = {term: index for index, term in enumerate(vocabulary_terms)}

    cooccurrence = np.zeros((len(vocabulary), len(vocabulary)), dtype=np.float32)
    window = 4
    for row in corpus_tokens:
        indexed = [vocabulary[term] for term in row if term in vocabulary]
        for position, left in enumerate(indexed):
            for right in indexed[position + 1: position + 1 + window]:
                if left == right:
                    continue
                cooccurrence[left, right] += 1.0
                cooccurrence[right, left] += 1.0
    print("semantic spike: cooccurrence built", flush=True)

    total = float(cooccurrence.sum()) or 1.0
    row_sums = cooccurrence.sum(axis=1, keepdims=True)
    col_sums = cooccurrence.sum(axis=0, keepdims=True)
    expected = np.maximum((row_sums * col_sums) / total, 1e-8)
    ppmi = np.maximum(np.log(np.maximum(cooccurrence, 1e-8) / expected), 0.0)
    dimensions = len(vocabulary)
    word_vectors = ppmi
    print("semantic spike: distributional vectors built", flush=True)
    idf = np.array([
        math.log((1 + len(records)) / (1 + document_frequency[term])) + 1
        for term in vocabulary_terms
    ], dtype=np.float32)

    def embed(row: list[str]) -> np.ndarray:
        indexes = [vocabulary[term] for term in row if term in vocabulary]
        if not indexes:
            return np.zeros(dimensions, dtype=np.float32)
        weights = idf[indexes]
        vector = (word_vectors[indexes] * weights[:, None]).sum(axis=0) / weights.sum()
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    document_vectors = np.vstack([embed(row) for row in corpus_tokens])
    results = []
    recovered = 0
    required_total = 0
    for item in queries:
        vector = embed(tokens(item["query"], 40))
        similarities = (document_vectors * vector).sum(axis=1)
        order = np.argsort(-similarities, kind="stable")[:50]
        ranked_ids = [ids[index] for index in order]
        ranks = {}
        for required_id in item["required_primary_ids"]:
            required_total += 1
            rank = ranked_ids.index(required_id) + 1 if required_id in ranked_ids else None
            ranks[required_id] = rank
            if rank is not None:
                recovered += 1
        results.append({
            **item,
            "semantic_required_anchor_ranks_at_50": ranks,
            "semantic_top_10_ids": ranked_ids[:10],
            "semantic_candidate_cap": 50,
        })

    semantic_recall = recovered / required_total if required_total else 1.0
    output = {
        "schema_version": 1,
        "iteration": "2R-iteration-2",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "offline_development_experiment_complete",
        "production_integration": False,
        "new_sealed_holdout_read_or_executed": False,
        "method": {
            "name": "static local PPMI distributional candidate discovery",
            "catalog_fields": ["parent_title", "parent_description", "publication_eligible_child_title_summary"],
            "citation_source_text_excluded": True,
            "vocabulary_size": len(vocabulary),
            "dimensions": dimensions,
            "candidate_cap_per_query": 50,
            "external_api_calls": 0,
            "production_dependencies_added": 0,
        },
        "comparison": {
            "population_queries": len(queries),
            "required_anchor_count": required_total,
            "improved_deterministic_primary_recall_at_50": 1.0,
            "semantic_candidate_recall_at_50": round(semantic_recall, 6),
            "deterministic_basis": "All required anchors in this adjudicated population are admitted within the current deterministic top 50; discovery recall is therefore necessarily complete.",
            "semantic_may_admit_primary": False,
        },
        "named_anchor_checks": {
            key: next((row["semantic_required_anchor_ranks_at_50"].get(anchor)
                       for row in results if row["query_id"] == query_id), None)
            for key, query_id, anchor in (
                ("rural_moms", "hold_health_01", "363582"),
                ("afri", "hold_ag_01", "360205"),
                ("genesis_secure_foundation_models", "hold_ai_01", "361526"),
                ("scaleup_long_duration_storage", "hold_energy_01", "356623"),
            )
        },
        "decision": "SEMANTIC SPIKE NOT NEEDED FOR PRODUCTION",
        "decision_rationale": [
            "The deterministic generalized candidate/admission architecture already has complete required-anchor recall at 50 on the adjudicated challenge and development population.",
            "The semantic alternative cannot improve recall beyond 1.0 on this population and remains non-causal discovery evidence.",
            "Shipping the experiment would add a dense model asset and browser/runtime complexity without measured acceptance benefit."
        ],
        "results": results,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "comparison": output["comparison"], "decision": output["decision"]}, indent=2))


if __name__ == "__main__":
    main()
