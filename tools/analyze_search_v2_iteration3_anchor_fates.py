"""Build the pre-implementation Phase-4B required-anchor fate trace.

This is a reporting-only reader of the immutable Phase-4B raw artifact. It
does not import or execute search code and cannot open the Phase-4C holdout.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sources.merge import load_catalog


RAW = ROOT / "evaluation/search_v2_iteration2_holdout_results_raw.json"
RESULTS = ROOT / "evaluation/search_v2_iteration2_holdout_results.json"
SIDECAR = ROOT / "data/subtopics.js"
OUTPUT = ROOT / "evaluation/search_v2_iteration3_anchor_fates.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sidecar() -> dict:
    source = SIDECAR.read_text(encoding="utf-8")
    return json.loads(source.split("globalThis.SUBTOPIC_CATALOG=", 1)[1].strip()[:-1])


SOURCE = {
    "360678": {
        "kind": "controlled_program_area",
        "label": "Basic Energy Sciences — Separation Science",
        "url": "https://science.osti.gov",
        "scope": ["separation science", "rare-earth separation and recovery"],
    },
    "361526": {
        "kind": "publication_eligible_child",
        "label": "Genesis Mission focus-area workbook",
        "url": "https://www.grants.gov/search-results-detail/361526",
        "scope": ["critical-minerals extraction and processing", "AI science workflows", "scientific software"],
    },
    "362061": {
        "kind": "authoritative_parent_scope",
        "label": "Chemical Process Systems",
        "url": "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506547",
        "scope": ["critical minerals", "separations", "recovery", "chemical process technology"],
    },
    "360205": {
        "kind": "authoritative_parent_and_notice_scope",
        "label": "AFRI Foundational and Applied Science",
        "url": "https://www.nifa.usda.gov/grants/funding-opportunities/agriculture-food-research-initiative-foundational-applied-science",
        "scope": ["plant production", "breeding", "genetics/genome modification", "biotic and abiotic stress"],
    },
    "356623": {
        "kind": "authoritative_parent_source_scope",
        "label": "SCALEUP READY",
        "url": "https://arpa-e-foa.energy.gov",
        "scope": ["energy-storage and grid technologies", "technology scale-up and commercialization"],
    },
    "344592": {
        "kind": "publication_eligible_child",
        "label": "ARL Super-Materials",
        "url": "https://www.arl.devcom.army.mil/opportunities/arl-baa/",
        "scope": ["structural materials", "high-temperature dynamic thermal environments"],
    },
    "356536": {
        "kind": "authoritative_parent_scope",
        "label": "NSF Geospace Cluster",
        "url": "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506312",
        "scope": ["Sun-Earth coupling", "upper atmosphere", "radiation belts", "electrodynamical processes"],
    },
    "363375": {
        "kind": "authoritative_parent_scope",
        "label": "Desalination and Water Purification Research",
        "url": "https://www.grants.gov/search-results-detail/363375",
        "scope": ["pilot-scale treatment", "impaired water", "purification and commercialization"],
    },
    "363537": {
        "kind": "authoritative_parent_scope",
        "label": "Alaska CESU climate-adaptation research",
        "url": "https://www.grants.gov/search-results-detail/363537",
        "scope": ["coastal erosion", "natural hazards", "actionable decision data and tools"],
    },
}


RELEVANT_CHILD = {
    "i2hold_material_01:361526": "361526:d-3",
    "i2hold_material_02:361526": "361526:d-3",
    "i2hold_material_04:361526": "361526:d-3",
    "i2hold_ai_02:361526": "361526:a-20",
    "i2hold_defense_02:344592": "344592:ab-0081",
    "i2hold_child_02:361526": "361526:e-18",
}


PRIMARY_CLASS = {
    "i2hold_material_01:360678": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_01:361526": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_01:362061": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_02:360678": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_02:361526": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_02:362061": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_04:361526": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_material_04:362061": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_ag_01:360205": "SCOPE_REPRESENTATION_FAILURE",
    "i2hold_ag_02:360205": "SCOPE_REPRESENTATION_FAILURE",
    "i2hold_energy_01:356623": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_energy_02:356623": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_ai_02:361526": "VERIFICATION_FAILURE",
    "i2hold_defense_02:344592": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_space_01:356536": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_space_02:356536": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_env_01:363375": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_env_02:363537": "QUERY_INTERPRETATION_FAILURE",
    "i2hold_child_02:361526": "VERIFICATION_FAILURE",
}


SECONDARY_CLASS = {
    "i2hold_ag_01:360205": ["DISCOVERY_FAILURE"],
    "i2hold_ag_02:360205": ["QUERY_INTERPRETATION_FAILURE"],
}


CAUSAL_TRACE = {
    "QUERY_INTERPRETATION_FAILURE": "The source candidate exists, but hyphenated compounds, modifiers, or synonymous scientific roles remain separate literal requirements instead of a coherent canonical intent.",
    "SCOPE_REPRESENTATION_FAILURE": "The authoritative notice contains the needed scientific scope, but the searchable parent representation exposes only a broad program synopsis and no reusable role-level scope signature.",
    "VERIFICATION_FAILURE": "The relevant publication-eligible child is discovered and contains the complete intent, but the verifier rejects it because one surface-form/acronym group is not counted as satisfied.",
}


def evidence_score(evidence: dict | None) -> float:
    admission = (evidence or {}).get("admission") or {}
    return float(admission.get("lexicalScore") or 0) + float(admission.get("semanticScore") or 0)


def discovery_ranks(query: dict) -> dict[str, int]:
    scores: dict[str, float] = {}
    for item in query.get("rejected_candidates", []):
        parent = str(item.get("parent_id") or item.get("id") or "")
        score = float(item.get("lexical_score") or 0) + float(item.get("semantic_score") or 0)
        scores[parent] = max(scores.get(parent, 0), score)
    for item in query.get("visible_primary_results", []) + query.get("broader_program_fits", []):
        scores[str(item["id"])] = max(scores.get(str(item["id"]), 0), float(item.get("score") or 0))
    ordered = sorted(scores, key=lambda item: (-scores[item], item))
    return {item: index + 1 for index, item in enumerate(ordered)}


def main() -> None:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    catalog = load_catalog(ROOT / "data/opportunities.js")
    parents = {str(item["opportunity_id"]): item for item in catalog["opportunities"]}
    sidecar = load_sidecar()
    children = {
        str(child["subtopic_id"]): child
        for parent in sidecar["records"].values()
        for child in parent.get("subtopics", [])
    }
    missed = results["gates"]["A_required_primary_recall"]["missed_required_anchors"]
    by_query = {item["id"]: item for item in raw["results"]}
    rows = []
    for key in missed:
        query_id, result_id = key.split(":", 1)
        query = by_query[query_id]
        anchor = next(item for item in query["required_anchor_checks"] if item["id"] == result_id)
        relevant_child_id = RELEVANT_CHILD.get(key)
        child_trace = next(
            (item for item in anchor.get("discovered_children", []) if item["id"] == relevant_child_id),
            None,
        )
        decisive_evidence = child_trace.get("evidence") if child_trace else anchor.get("parent_evidence")
        parent_discovered = evidence_score(anchor.get("parent_evidence")) > 0
        child_discovered = None if relevant_child_id is None else child_trace is not None
        primary_class = PRIMARY_CLASS[key]
        source = SOURCE[result_id]
        rows.append({
            "query_id": query_id,
            "query": query["query"],
            "required_result_id": result_id,
            "required_result_title": parents[result_id]["title"],
            "authoritative_source": {
                "kind": source["kind"],
                "label": source["label"],
                "url": source["url"],
                "relevant_child_id": relevant_child_id,
                "relevant_child_title": children.get(relevant_child_id, {}).get("title") if relevant_child_id else None,
            },
            "source_evidence_available": True,
            "source_scope_summary": source["scope"],
            "parent_candidate_discovered": parent_discovered,
            "relevant_child_required": relevant_child_id is not None,
            "relevant_child_candidate_discovered": child_discovered,
            "candidate_rank_before_verification": discovery_ranks(query).get(result_id),
            "candidate_rank_definition": "rank of the parent rollup by maximum raw lexical-plus-topic discovery score before admission verification",
            "query_concepts_produced": [
                {
                    "concept_id": item["concept_id"],
                    "role": item["role"],
                    "source": item["source"],
                    "required": item["required"],
                }
                for item in query["query_plan"]
            ],
            "scope_concepts_available": source["scope"],
            "verification_result": (decisive_evidence or {}).get("admission", {}).get("classification", "not_scored"),
            "rejection_reason": (decisive_evidence or {}).get("admission", {}).get("reason", "no_scoring_evidence"),
            "evidence_tier": (decisive_evidence or {}).get("admission", {}).get("evidenceTier", 5),
            "final_result_state": "rejected_not_visible",
            "primary_failure_class": primary_class,
            "secondary_failure_classes": SECONDARY_CLASS.get(key, []),
            "causal_trace": CAUSAL_TRACE[primary_class],
            "smallest_general_fix": {
                "QUERY_INTERPRETATION_FAILURE": "Derive role-aware intent from compound/modifier structure and compare it to source roles without query-string allowlists.",
                "SCOPE_REPRESENTATION_FAILURE": "Expose provenance-backed role phrases from authoritative parent/notice text as a reusable source scope signature.",
                "VERIFICATION_FAILURE": "Let exact source-backed child phrases satisfy their semantic role even when the query uses a resolved acronym or inflectional surface variant.",
            }[primary_class],
        })

    primary_counts = Counter(row["primary_failure_class"] for row in rows)
    parent_discovered = sum(row["parent_candidate_discovered"] for row in rows)
    child_required = sum(row["relevant_child_required"] for row in rows)
    child_discovered = sum(row["relevant_child_candidate_discovered"] is True for row in rows)
    payload = {
        "schema_version": 1,
        "iteration": 3,
        "created_at": "2026-08-22",
        "status": "pre_implementation_anchor_fate_trace_complete",
        "source_raw_artifact": str(RAW.relative_to(ROOT)).replace("\\", "/"),
        "source_raw_sha256": sha256(RAW),
        "source_results_artifact": str(RESULTS.relative_to(ROOT)).replace("\\", "/"),
        "source_results_sha256": sha256(RESULTS),
        "missed_anchor_count": len(rows),
        "primary_failure_class_counts": dict(sorted(primary_counts.items())),
        "all_failure_class_counts": {
            "DISCOVERY_FAILURE": 1,
            "QUERY_INTERPRETATION_FAILURE": 16,
            "SCOPE_REPRESENTATION_FAILURE": 2,
            "VERIFICATION_FAILURE": 2,
            "ROLLUP_FAILURE": 0,
            "RANKING_FAILURE": 0,
            "SOURCE_COVERAGE_FAILURE": 0,
        },
        "discovery_summary": {
            "parent_candidates_discovered": parent_discovered,
            "parent_candidates_not_discovered": len(rows) - parent_discovered,
            "relevant_children_required": child_required,
            "relevant_children_discovered": child_discovered,
            "verified_primary_before_final_ranking": 0,
            "ranking_owned_misses": 0,
        },
        "semantic_benchmark_trigger": {
            "triggered": False,
            "reason": "18 of 19 required parents and every required publication-eligible child were already discovered; the dominant owners are query/scope representation and verification, not semantic candidate recall.",
            "ppmi_result_interpretation": "The prior PPMI result is not treated as evidence against modern semantic retrieval; a new benchmark is simply not justified by this fate trace.",
        },
        "architecture_implication": "Keep broad internal discovery, complete-intent verification, evidence tiers, and causal explanations. Replace query-string/program allowlists with source-grounded role signatures and a generic role-aware verifier; do not add semantic candidate infrastructure in this iteration.",
        "rows": rows,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "missed_anchor_count": len(rows),
        "primary_failure_class_counts": payload["primary_failure_class_counts"],
        "discovery_summary": payload["discovery_summary"],
        "semantic_benchmark_triggered": False,
    }, indent=2))


if __name__ == "__main__":
    main()
