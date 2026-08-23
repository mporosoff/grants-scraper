"""Summarize Iteration-3 spent-challenge results without reading Phase 4C."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "evaluation/search_v2_iteration3_spent_challenge_raw.json"
SUPPLEMENT = ROOT / "evaluation/search_v2_iteration3_truth_supplement.json"
OUTPUT = ROOT / "evaluation/search_v2_iteration3_results.json"
TRUTH_PATHS = {
    "phase4_iteration1_spent": ROOT / "evaluation/search_v2_holdout_truth.json",
    "phase4b_iteration2_spent": ROOT / "evaluation/search_v2_iteration2_holdout_truth.json",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rounded(value: float) -> float:
    return round(value, 6)


def average(values: list[float]) -> float:
    return rounded(sum(values) / len(values)) if values else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return rounded(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)])


def dcg(labels: list[str]) -> float:
    grades = {"primary_relevant": 2, "broader_program_fit": 1, "irrelevant": 0}
    return sum(((2 ** grades.get(label, 0)) - 1) / math.log2(index + 2)
               for index, label in enumerate(labels))


def metrics(rows: list[dict], truth: dict[str, dict]) -> dict:
    precisions: list[float] = []
    recalls10: list[float] = []
    recalls50: list[float] = []
    ndcgs: list[float] = []
    anchor_count = recovered10 = recovered50 = 0
    primary_count = irrelevant_primary = broader_as_primary = 0
    visible = candidates = rejected = broader = 0
    admission_counts: Counter[str] = Counter()
    latencies: list[float] = []
    explanation_violations: list[str] = []
    unexpected_unjudged: list[str] = []

    for row in rows:
        query_truth = truth[row["id"]]
        judgments = query_truth["judgments"]
        top = row["top_10"]
        labels: list[str] = []
        for result in top:
            judgment = judgments.get(result["id"])
            if not judgment:
                unexpected_unjudged.append(f'{row["id"]}:{result["id"]}')
                labels.append("irrelevant")
                continue
            label = judgment["label"]
            labels.append(label)
            primary_count += int(label == "primary_relevant")
            irrelevant_primary += int(label == "irrelevant")
            broader_as_primary += int(label == "broader_program_fit")
            path = (result.get("admitted_by") or [{}])[0].get("path", "explicit_evidence")
            admission_counts[path] += 1
            explanation = result.get("explanation") or {}
            serialized = json.dumps(explanation).lower()
            if label != "primary_relevant" or explanation.get("primary") is not True:
                explanation_violations.append(f'{row["id"]}:{result["id"]}:primary_label')
            if not explanation.get("reasons"):
                explanation_violations.append(f'{row["id"]}:{result["id"]}:empty')
            if "semantic similarity" in serialized or "private" in serialized:
                explanation_violations.append(f'{row["id"]}:{result["id"]}:prohibited_text')
        precisions.append(
            sum(label == "primary_relevant" for label in labels) / len(labels)
            if labels else 1.0
        )
        required = [str(value) for value in query_truth.get("required_primary_ids", [])]
        ranks = row["required_primary_ranks"]
        if required:
            anchor_count += len(required)
            at10 = sum(ranks.get(value) is not None and ranks[value] <= 10 for value in required)
            at50 = sum(ranks.get(value) is not None and ranks[value] <= 50 for value in required)
            recovered10 += at10
            recovered50 += at50
            recalls10.append(at10 / len(required))
            recalls50.append(at50 / len(required))
        ideal_labels = sorted(
            (item["label"] for item in judgments.values()),
            key=lambda label: {"primary_relevant": 2, "broader_program_fit": 1, "irrelevant": 0}.get(label, 0),
            reverse=True,
        )[:10]
        ideal = dcg(ideal_labels)
        ndcgs.append(rounded(dcg(labels) / ideal) if ideal else (1.0 if not labels else 0.0))
        for result in row.get("broader_program_fits", []):
            judgment = judgments.get(result["id"])
            explanation = result.get("explanation") or {}
            if not judgment or judgment.get("label") != "broader_program_fit":
                explanation_violations.append(f'{row["id"]}:{result["id"]}:broader_truth')
            if explanation.get("primary") is not False or explanation.get("tier") != "broader_program":
                explanation_violations.append(f'{row["id"]}:{result["id"]}:broader_explanation')
        visible += row["visible_primary_count"]
        candidates += row["internal_candidate_count"]
        rejected += row.get("rejected_partial_intent_count", 0)
        broader += len(row.get("broader_program_fits", []))
        latencies.append(float(row["latency_ms"]))

    return {
        "query_count": len(rows),
        "required_anchor_count": anchor_count,
        "query_average_primary_precision_at_10": average(precisions),
        "positive_query_required_primary_recall_at_10": average(recalls10),
        "positive_query_required_primary_recall_at_50": average(recalls50),
        "required_anchor_micro_recall_at_10": rounded(recovered10 / anchor_count) if anchor_count else 1.0,
        "required_anchor_micro_recall_at_50": rounded(recovered50 / anchor_count) if anchor_count else 1.0,
        "query_average_ndcg_at_10": average(ndcgs),
        "visible_primary_count": visible,
        "broader_fit_count": broader,
        "internal_candidate_discovery_count": candidates,
        "rejected_partial_intent_count": rejected,
        "irrelevant_visible_primary_count": irrelevant_primary,
        "broader_as_visible_primary_count": broader_as_primary,
        "maximum_visible_primary_count": max((row["visible_primary_count"] for row in rows), default=0),
        "maximum_internal_candidate_count": max((row["internal_candidate_count"] for row in rows), default=0),
        "admission_path_counts": dict(sorted(admission_counts.items())),
        "latency_ms": {
            "p50": percentile(latencies, .5),
            "p95": percentile(latencies, .95),
            "maximum": rounded(max(latencies, default=0.0)),
        },
        "unexpected_unjudged_visible_primary_pairs": unexpected_unjudged,
        "explanation_violations": explanation_violations,
    }


def main() -> None:
    raw = load(RAW)
    supplement = load(SUPPLEMENT)
    supplement_by_population: dict[str, dict[str, dict[str, dict]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for item in supplement["judgments"]:
        supplement_by_population[item["population"]][item["query_id"]][item["result_id"]] = {
            "label": item["label"],
            "evidence": item["evidence"],
            "source": "iteration3_query_specific_supplement",
        }

    populations: dict[str, dict] = {}
    all_rows: list[dict] = []
    all_truth: dict[str, dict] = {}
    domain_rows: dict[str, list[dict]] = defaultdict(list)
    domain_truth: dict[str, dict[str, dict]] = defaultdict(dict)
    for population in raw["populations"]:
        population_id = population["id"]
        original = load(TRUTH_PATHS[population_id])["queries"]
        merged: dict[str, dict] = {}
        for query_id, value in original.items():
            merged[query_id] = {
                **value,
                "judgments": {
                    **value.get("judgments", {}),
                    **supplement_by_population[population_id].get(query_id, {}),
                },
            }
        population_metrics = metrics(population["results"], merged)
        populations[population_id] = population_metrics
        for row in population["results"]:
            composite_id = f"{population_id}:{row['id']}"
            copied = {**row, "id": composite_id}
            truth_copy = merged[row["id"]]
            all_rows.append(copied)
            all_truth[composite_id] = truth_copy
            domain = row.get("discipline") or "unclassified"
            domain_rows[domain].append(copied)
            domain_truth[domain][composite_id] = truth_copy

    payload = {
        "schema_version": 1,
        "iteration": 3,
        "status": "spent_challenge_development_results",
        "sealed_phase4c_read_or_executed": False,
        "truth_contract": "exact (population, query_id, result_id); immutable original truth plus an additive Iteration-3 supplement",
        "truth_supplement_judgment_count": len(supplement["judgments"]),
        "populations": populations,
        "combined": metrics(all_rows, all_truth),
        "by_domain": {
            domain: metrics(rows, domain_truth[domain])
            for domain, rows in sorted(domain_rows.items())
        },
        "comparison": {
            "phase4_iteration1_acceptance_before": {
                "primary_precision_at_10": 0.373,
                "required_primary_recall_at_10": 0.633,
                "required_primary_recall_at_50": 0.650,
                "ndcg_at_10": 0.586,
                "maximum_candidate_count": 213,
                "irrelevant_top_ten_primary_admissions": 43,
            },
            "phase4b_iteration2_acceptance_before": {
                "primary_precision_at_10": 0.410714,
                "required_primary_recall_at_10": 0.3,
                "required_primary_recall_at_50": 0.3,
                "ndcg_at_10": 0.392857,
                "maximum_visible_primary_count": 3,
                "maximum_internal_candidate_count": 1142,
                "irrelevant_visible_primary_count": 3,
                "broader_as_visible_primary_count": 1,
            },
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), **payload["combined"]}, indent=2))


if __name__ == "__main__":
    main()
