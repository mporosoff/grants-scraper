#!/usr/bin/env node

// Builds the bounded manual/source-backed precision review for the disabled
// hybrid production candidate. No provider call or sealed holdout input exists.

import { readFile, writeFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const OUTPUT = "evaluation/search_v2_hybrid_precision_review.json";

const MANUAL_POSITIVE_TOP1 = {
  hold_ree_01: {
    supported: true,
    rationale: "EWRE explicitly supports recycling and management of materials and critical minerals and recovery/re-use of resources.",
  },
  hold_ree_03: {
    supported: false,
    rationale: "The MPS Materials umbrella describes broad materials research but does not establish lanthanide ion-exchange scope.",
  },
  hold_ree_04: {
    supported: false,
    rationale: "The Burma governance notice has no rare-earth or hydrometallurgy research purpose; its extracted hydrometallurgy program-area value is a source-representation collision.",
  },
  hold_chem_01: {
    supported: true,
    rationale: "CPS explicitly supports catalysis, electrochemical systems, reaction engineering, and chemical synthesis/process innovation.",
  },
  hold_chem_02: {
    supported: false,
    rationale: "FINDERS FOUNDRY supports K-12 learning innovation but does not establish the catalyst/innovation-economy student-success intent used by the required anchors.",
  },
  hold_bio_01: {
    supported: false,
    rationale: "The cancer-technology program is adjacent but its published passage does not establish the single-cell immunology method and domain together.",
  },
  hold_space_02: {
    supported: true,
    rationale: "CESEV explicitly supports geochemical and petrologic research on the chemical evolution and systems of the solid Earth.",
  },
  hold_ai_02: {
    supported: false,
    rationale: "The Ukraine program supports AI-enabled journalism training but does not establish the requested journalism exchange mechanism.",
  },
  i2hold_energy_01: {
    supported: true,
    rationale: "PART finances energy-storage systems supporting power-generation projects and is an implementation/scale-up funding path.",
  },
  i2hold_energy_02: {
    supported: false,
    rationale: "MERC's generic applied-research and commercialization scope does not establish seasonal thermal storage.",
  },
  i2hold_space_02: {
    supported: false,
    rationale: "CEDAR supports upper-atmosphere dynamics and particle inputs but its passage does not establish radiation-belt dynamics.",
  },
  i2hold_env_02: {
    supported: true,
    rationale: "The Gulf Coast CESU passage explicitly supports coastal-erosion risk prediction and decision-relevant hazard tools.",
  },
};

const ZERO_ANCHOR_RATIONALES = {
  hold_ree_07: "Each surfaced result supplies Earth/observation/material wording separately; none establishes the complete rare-Earth-observation-elements intent.",
  hold_bio_02: "The surfaced biomedical data and training programs do not establish training for the named BioData Catalyst platform.",
  hold_health_02: "The surfaced results each omit at least one major health, data, workforce, or workshop dimension; the two NIOSH meeting programs are only adjacent.",
  hold_space_01: "The frozen catalog has no current microgravity radiation-biology anchor; surfaced radiation/biology programs omit microgravity scope.",
  i2hold_defense_01: "The surfaced defense and sensing programs do not jointly establish autonomous, naval, and sensing-system scope.",
  i2hold_negative_01: "The surfaced maternal-health programs omit the data-workforce symposium intent.",
  i2hold_negative_02: "The surfaced rare-disease programs omit the planetary dimension.",
  i2hold_negative_03: "The surfaced oncology/instrumentation programs omit microgravity scope.",
  i2hold_negative_04: "The surfaced drought, crop, exchange, and diplomacy programs do not contain all four dimensions in one published scope.",
  i2hold_acronym_01: "The strict acronym and complete-intent guard correctly returns no result.",
  i2hold_acronym_02: "The strict acronym and complete-intent guard correctly returns no result.",
  i2hold_broader_01: "The surfaced ocean/coastal programs are adjacent to marine ecosystem resilience but do not establish the complete primary scope in the sampled passage.",
};

async function main() {
  const results = await readFile(
    new URL("evaluation/search_v2_hybrid_production_results.json", ROOT),
    "utf8",
  ).then(JSON.parse);
  const truths = await Promise.all([
    readFile(new URL("evaluation/search_v2_holdout_truth.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("evaluation/search_v2_iteration2_holdout_truth.json", ROOT), "utf8").then(JSON.parse),
  ]);
  const truthByQuery = new Map(truths.flatMap(truth => Object.entries(truth.queries)));
  const pairs = [];

  for (const row of results.rows) {
    const queryTruth = truthByQuery.get(row.id);
    if (!queryTruth) throw new Error(`Missing spent query truth for ${row.id}.`);
    if (!row.required_primary_ids.length) {
      for (const item of row.top_50.slice(0, 10)) {
        const existing = queryTruth.judgments?.[item.id] || null;
        pairs.push({
          query_id: row.id,
          query: row.query,
          result_id: item.id,
          rank: item.rank,
          title: item.title,
          source_field: item.explanation?.source_field || null,
          source_excerpt: item.explanation?.excerpt || "",
          complete_intent_supported: false,
          label: existing?.label || "not_primary_relevant",
          rationale: existing?.evidence || ZERO_ANCHOR_RATIONALES[row.id],
          judgment_source: existing ? "existing_exact_query_result_truth" : "bounded_manual_public_passage_review",
        });
      }
      continue;
    }

    const item = row.top_50[0];
    if (!item) continue;
    const existing = queryTruth.judgments?.[item.id] || null;
    const manual = MANUAL_POSITIVE_TOP1[row.id] || null;
    if (!existing && !manual) throw new Error(`Missing manual top-1 review for ${row.id}/${item.id}.`);
    const supported = existing
      ? existing.label === "primary_relevant"
      : manual.supported;
    pairs.push({
      query_id: row.id,
      query: row.query,
      result_id: item.id,
      rank: 1,
      title: item.title,
      source_field: item.explanation?.source_field || null,
      source_excerpt: item.explanation?.excerpt || "",
      complete_intent_supported: supported,
      label: existing?.label || (supported ? "primary_relevant" : "not_primary_relevant"),
      rationale: existing?.evidence || manual.rationale,
      judgment_source: existing ? "existing_exact_query_result_truth" : "bounded_manual_public_passage_review",
    });
  }

  const zeroAnchorPairs = pairs.filter(item => !results.rows.find(row => row.id === item.query_id).required_primary_ids.length);
  const positiveTop1Pairs = pairs.filter(item => results.rows.find(row => row.id === item.query_id).required_primary_ids.length);
  const payload = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    status: "bounded_source_backed_precision_review_complete",
    methodology: {
      population: "two spent holdouts only",
      sample: "Top 10 for every zero-required-anchor query plus top 1 for every positive query with a returned result.",
      exact_key: "query_id,result_id",
      evidence: "Winning existing public indexed passage and existing exact-pair truth where available.",
      voyage_score_used_as_truth: false,
      sealed_phase4c_read_or_executed: false,
    },
    summary: {
      reviewed_pair_count: pairs.length,
      zero_anchor_top_10_pair_count: zeroAnchorPairs.length,
      zero_anchor_complete_intent_supported_count: zeroAnchorPairs.filter(item => item.complete_intent_supported).length,
      zero_anchor_non_primary_count: zeroAnchorPairs.filter(item => !item.complete_intent_supported).length,
      positive_query_top_1_pair_count: positiveTop1Pairs.length,
      positive_query_top_1_complete_intent_precision: Number((
        positiveTop1Pairs.filter(item => item.complete_intent_supported).length
        / positiveTop1Pairs.length
      ).toFixed(6)),
      bounded_sample_complete_intent_precision: Number((
        pairs.filter(item => item.complete_intent_supported).length / pairs.length
      ).toFixed(6)),
      full_precision_at_10_established: false,
      precision_gate_supported: false,
      blocking_observation: "All 100 surfaced top-ten results on zero-anchor queries were non-primary in the bounded review; the ranked engine does not suppress partial-intent hard negatives.",
    },
    source_representation_findings: [{
      query_id: "hold_ree_04",
      result_id: "363604",
      rank: 1,
      extracted_field: "document_program_areas",
      extracted_value: "hydrometallurgy",
      authoritative_parent_purpose: "community-backed governance and peace in Burma",
      finding: "The field value is not supported by the parent title/description and creates a false semantic/ranking and explanation signal.",
      owner: "source ingestion / document program-area extraction",
    }],
    cutoff_review: {
      conclusion: "No conservative relevance-score cutoff separates hard negatives from required anchors.",
      evidence: "Hard-negative top scores reach 0.640625 while required-anchor scores extend down to 0.339844; a 0.45 cutoff reduces required Recall@50 to 0.584615 and still leaves 49 hard-negative top-ten results.",
      cutoff_added: false,
    },
    pairs,
  };
  await writeFile(new URL(OUTPUT, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(payload.summary, null, 2)}\n`);
}

await main();
