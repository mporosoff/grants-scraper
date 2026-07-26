"""Summarize exported Funding Finder Phase 2 relevance labels.

This intentionally evaluates deterministic retrieval separately from AI
reranking. It never needs an API key, research description, or CV.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


VALID_LABELS = {"useful", "not_relevant", "needs_verification", "partial", "strong"}
# Labels that count as a positive (useful-tier) match for retrieval/precision.
POSITIVE_LABELS = {"useful", "strong"}
# Graded relevance values; needs_verification is intentionally ungraded (None).
GRADE_VALUES = {"not_relevant": 0, "partial": 1, "useful": 2, "strong": 3}


def _load_export(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported evaluation schema")
    if not isinstance(payload.get("feedback"), list):
        raise ValueError(f"{path}: feedback must be a list")
    return payload


def _valid_entries(exports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for export_index, payload in enumerate(exports):
        candidate_ids = {
            str(value)
            for value in payload.get("session", {}).get("candidate_ids", [])
            if value
        }
        for entry in payload["feedback"]:
            if not isinstance(entry, dict) or entry.get("label") not in VALID_LABELS:
                continue
            entries.append({
                **entry,
                "_export_index": export_index,
                "_prompt_version": payload.get("prompt_version"),
                "_candidate_ids": candidate_ids,
            })
    return entries


def _rank(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _ndcg(rank_gain_pairs) -> float | None:
    """Graded nDCG over labeled items placed at their ranks (gain = relevance).

    Each labeled item contributes gain/log2(rank+1); the ideal ordering places
    the same gains at the best ranks. Returns None when nothing is rankable.
    """
    items = [
        (rank, gain)
        for rank, gain in rank_gain_pairs
        if isinstance(rank, int) and rank > 0 and gain is not None
    ]
    if not items:
        return None
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in items)
    ideal = sorted((gain for _, gain in items), reverse=True)
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_exports(exports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    exports = list(exports)
    entries = _valid_entries(exports)
    labels = Counter(entry["label"] for entry in entries)
    reasons = Counter(
        entry.get("reason") or "unspecified"
        for entry in entries
    )

    graded_values = [
        GRADE_VALUES[entry["label"]]
        for entry in entries
        if entry["label"] in GRADE_VALUES
    ]
    graded_distribution = Counter(
        entry["label"] for entry in entries if entry["label"] in GRADE_VALUES
    )

    # Graded ranking quality (nDCG), computed per export/query then averaged.
    by_export: dict[Any, list] = defaultdict(list)
    for entry in entries:
        by_export[entry["_export_index"]].append(entry)
    retrieval_ndcgs = [
        value for value in (
            _ndcg([
                (item.get("retrieval_rank"), GRADE_VALUES.get(item["label"]))
                for item in group
            ])
            for group in by_export.values()
        ) if value is not None
    ]
    reranking_ndcgs = [
        value for value in (
            _ndcg([
                (item.get("ai_rank"), GRADE_VALUES.get(item["label"]))
                for item in group
            ])
            for group in by_export.values()
        ) if value is not None
    ]

    useful = [entry for entry in entries if entry["label"] in POSITIVE_LABELS]
    useful_with_candidate_judgment = [
        entry
        for entry in useful
        if entry["_candidate_ids"] or _rank(entry.get("retrieval_rank"))
    ]
    useful_retrieved_at_32 = [
        entry
        for entry in useful_with_candidate_judgment
        if (
            str(entry.get("opportunity_id")) in entry["_candidate_ids"]
            if entry["_candidate_ids"]
            else entry["retrieval_rank"] <= 32
        )
    ]

    ai_top_12 = [
        entry
        for entry in entries
        if (_rank(entry.get("ai_rank")) or 10_000) <= 12
    ]
    ai_top_12_useful = [
        entry for entry in ai_top_12 if entry["label"] in POSITIVE_LABELS
    ]
    rank_movements = [
        entry["retrieval_rank"] - entry["ai_rank"]
        for entry in entries
        if _rank(entry.get("retrieval_rank")) and _rank(entry.get("ai_rank"))
    ]

    not_relevant = [
        entry for entry in entries if entry["label"] == "not_relevant"
    ]
    eligibility_errors = [
        entry for entry in not_relevant if entry.get("reason") == "eligibility"
    ]
    expired_errors = [
        entry
        for entry in entries
        if entry.get("reason") == "expired_or_closed"
    ]

    provider_models = Counter(
        f"{entry.get('provider') or 'none'} / {entry.get('model') or 'none'}"
        for entry in entries
    )
    prompt_versions = Counter(
        entry.get("_prompt_version") or "unspecified"
        for entry in entries
    )

    return {
        "exports": len(exports),
        "reviewed": len(entries),
        "labels": dict(sorted(labels.items())),
        "reasons": dict(sorted(reasons.items())),
        "graded": {
            "mean_relevance": (mean(graded_values) if graded_values else None),
            "graded_count": len(graded_values),
            "distribution": dict(sorted(graded_distribution.items())),
            "retrieval_ndcg": (mean(retrieval_ndcgs) if retrieval_ndcgs else None),
            "reranking_ndcg": (mean(reranking_ndcgs) if reranking_ndcgs else None),
            "exports_scored": len(by_export),
        },
        "retrieval": {
            "useful_with_known_candidate_membership": len(
                useful_with_candidate_judgment
            ),
            "useful_retrieved_at_32": len(useful_retrieved_at_32),
            "candidate_recall_at_32": (
                len(useful_retrieved_at_32) / len(useful_with_candidate_judgment)
                if useful_with_candidate_judgment
                else None
            ),
        },
        "reranking": {
            "reviewed_in_ai_top_12": len(ai_top_12),
            "useful_in_ai_top_12": len(ai_top_12_useful),
            "precision_at_12": (
                len(ai_top_12_useful) / len(ai_top_12)
                if ai_top_12
                else None
            ),
            "mean_rank_improvement": (
                mean(rank_movements) if rank_movements else None
            ),
        },
        "quality_errors": {
            "eligibility": len(eligibility_errors),
            "eligibility_rate_among_not_relevant": (
                len(eligibility_errors) / len(not_relevant)
                if not_relevant
                else None
            ),
            "expired_or_closed": len(expired_errors),
            "expired_or_closed_rate": (
                len(expired_errors) / len(entries) if entries else None
            ),
        },
        "provider_models": dict(sorted(provider_models.items())),
        "prompt_versions": dict(sorted(prompt_versions.items())),
    }


def evaluate_paths(paths: Iterable[Path]) -> dict[str, Any]:
    return evaluate_exports(_load_export(path) for path in paths)


def _percent(value: float | None) -> str:
    return "not available" if value is None else f"{value:.1%}"


def format_report(summary: dict[str, Any]) -> str:
    retrieval = summary["retrieval"]
    reranking = summary["reranking"]
    errors = summary["quality_errors"]
    lines = [
        "Funding Finder Phase 2 evaluation",
        f"Exports: {summary['exports']}",
        f"Reviewed pairs: {summary['reviewed']}",
        f"Labels: {json.dumps(summary['labels'], sort_keys=True)}",
        (
            "Mean graded relevance (0-3): "
            f"{summary['graded']['mean_relevance']:.2f}"
            if summary["graded"]["mean_relevance"] is not None
            else "Mean graded relevance (0-3): not available"
        ),
        (
            "Graded nDCG retrieval / reranking: "
            + (f"{summary['graded']['retrieval_ndcg']:.3f}"
               if summary["graded"]["retrieval_ndcg"] is not None else "not available")
            + " / "
            + (f"{summary['graded']['reranking_ndcg']:.3f}"
               if summary["graded"]["reranking_ndcg"] is not None else "not available")
        ),
        (
            "Retrieval candidate recall@32: "
            f"{_percent(retrieval['candidate_recall_at_32'])} "
            f"({retrieval['useful_retrieved_at_32']}/"
            f"{retrieval['useful_with_known_candidate_membership']} "
            "useful labels with known candidate membership)"
        ),
        (
            "AI precision@12: "
            f"{_percent(reranking['precision_at_12'])} "
            f"({reranking['useful_in_ai_top_12']}/"
            f"{reranking['reviewed_in_ai_top_12']} reviewed)"
        ),
        (
            "Mean AI rank improvement: "
            f"{reranking['mean_rank_improvement'] if reranking['mean_rank_improvement'] is not None else 'not available'}"
        ),
        (
            "Eligibility error rate among not-relevant labels: "
            f"{_percent(errors['eligibility_rate_among_not_relevant'])}"
        ),
        f"Expired/closed error rate: {_percent(errors['expired_or_closed_rate'])}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure Phase 2 retrieval and AI-reranking quality.",
    )
    parser.add_argument(
        "exports",
        nargs="+",
        type=Path,
        help="One or more exported funding-finder-evaluation JSON files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the aggregate summary as JSON.",
    )
    arguments = parser.parse_args()
    summary = evaluate_paths(arguments.exports)
    if arguments.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_report(summary))


if __name__ == "__main__":
    main()
