#!/usr/bin/env node
// Iteration-3 leave-out evaluation over spent challenge evidence only.

import { readFile, writeFile } from "node:fs/promises";
import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const OUTPUT = "evaluation/search_v2_iteration3_leaveout.json";
const POPULATIONS = [
  ["phase4_iteration1_spent", "evaluation/search_v2_holdout_frame.json", "evaluation/search_v2_holdout_truth.json"],
  ["phase4b_iteration2_spent", "evaluation/search_v2_iteration2_holdout_frame.json", "evaluation/search_v2_iteration2_holdout_truth.json"],
];

function withoutProgramConcepts(config, concepts) {
  const blocked = new Set(concepts);
  return (config.authoritative_scope_entailments || []).filter(entry => (
    !(entry.supported_query_concepts || []).some(concept => blocked.has(concept))
  ));
}

function withoutRelationships(config, relationshipIds) {
  const blocked = new Set(relationshipIds);
  return (config.source_scope_relationships || []).filter(entry => (
    !blocked.has(entry.canonical_id)
  ));
}

function variants(config) {
  const base = structuredClone(config);
  return [
    { id: "full_iteration3", config: base, withheld: [], heldQueryIds: [] },
    {
      id: "all_program_contracts_withheld",
      config: { ...structuredClone(config), authoritative_scope_entailments: [] },
      withheld: ["all program-specific authoritative-scope contracts"],
    },
    {
      id: "all_relationships_withheld",
      config: { ...structuredClone(config), source_scope_relationships: [] },
      withheld: ["all Iteration-3 source-side controlled relationships"],
    },
    {
      id: "pure_source_representation",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: [],
        source_scope_relationships: [],
      },
      withheld: ["all program contracts", "all source-side controlled relationships"],
    },
    {
      id: "material_family_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: withoutProgramConcepts(config, [
          "rare-earth-elements", "critical-minerals", "separations",
        ]),
        source_scope_relationships: withoutRelationships(config, [
          "rare-earth-subset-to-critical-mineral-scope", "separation-processing-source-family",
        ]),
      },
      withheld: ["rare-earth/critical-mineral program contracts", "material/separation relationships"],
      heldQueryIds: [
        "hold_ree_01", "hold_ree_02", "hold_ree_03", "hold_ree_04", "hold_ree_05", "hold_ree_06",
        "i2hold_material_01", "i2hold_material_02", "i2hold_material_03", "i2hold_material_04",
      ],
    },
    {
      id: "agriculture_family_and_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: withoutProgramConcepts(config, [
          "drought-resilience", "abiotic-stress-resilience", "biotic-stress-resilience", "crop-genetics",
        ]),
        source_scope_relationships: withoutRelationships(config, [
          "heat-resilience-to-abiotic-stress", "disease-resistance-to-biotic-stress",
          "crop-genetics-source-family",
        ]),
      },
      withheld: ["agriculture program contract", "abiotic/biotic stress relationships"],
      heldQueryIds: ["hold_ag_01", "i2hold_ag_01", "i2hold_ag_02"],
    },
    {
      id: "energy_family_and_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: withoutProgramConcepts(config, [
          "long-duration", "energy-storage", "technology-maturation",
        ]),
        source_scope_relationships: withoutRelationships(config, [
          "seasonal-to-long-duration", "storage-technology-family", "technology-maturation-process",
        ]),
      },
      withheld: ["energy-storage program contract", "storage duration/maturation relationships"],
      heldQueryIds: ["hold_energy_01", "i2hold_energy_01", "i2hold_energy_02"],
    },
    {
      id: "ai_family_and_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: withoutProgramConcepts(config, [
          "security-resilience", "foundation-models", "scientific-workflows", "scientific-software",
        ]),
        source_scope_relationships: withoutRelationships(config, [
          "ai-security-resilience-property", "scientific-workflow-context", "scientific-software-target",
        ]),
      },
      withheld: ["AI security/program contracts", "AI security/workflow/software relationships"],
      heldQueryIds: ["hold_ai_01", "i2hold_ai_02", "i2hold_child_02"],
    },
    {
      id: "genesis_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: (config.authoritative_scope_entailments || [])
          .filter(entry => String(entry.parent_id) !== "361526"),
      },
      withheld: ["all Genesis program-specific contracts"],
      heldQueryIds: [
        "hold_ree_01", "hold_ree_02", "hold_ree_03", "hold_ree_04", "hold_ree_05", "hold_ree_06",
        "hold_ai_01", "i2hold_material_01", "i2hold_material_02", "i2hold_material_03",
        "i2hold_ai_01", "i2hold_ai_02", "i2hold_child_01", "i2hold_child_02",
      ],
    },
    {
      id: "afri_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: (config.authoritative_scope_entailments || [])
          .filter(entry => String(entry.parent_id) !== "360205"),
      },
      withheld: ["all AFRI program-specific contracts"],
      heldQueryIds: ["hold_ag_01", "i2hold_ag_01", "i2hold_ag_02"],
    },
    {
      id: "scaleup_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: (config.authoritative_scope_entailments || [])
          .filter(entry => String(entry.parent_id) !== "356623"),
      },
      withheld: ["all SCALEUP program-specific contracts"],
      heldQueryIds: ["hold_energy_01", "i2hold_energy_01", "i2hold_energy_02"],
    },
    {
      id: "bes_program_out",
      config: {
        ...structuredClone(config),
        authoritative_scope_entailments: (config.authoritative_scope_entailments || [])
          .filter(entry => String(entry.parent_id) !== "360678"),
      },
      withheld: ["all BES umbrella program-specific contracts"],
      heldQueryIds: [
        "hold_ree_01", "hold_ree_02", "hold_ree_03", "hold_ree_04", "hold_ree_05", "hold_ree_06",
        "i2hold_material_01", "i2hold_material_02", "i2hold_material_03",
      ],
    },
  ];
}

async function main() {
  if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
    throw new Error("Leave-out evaluation refuses the sealed Phase-4C population.");
  }
  const base = await loadHarness();
  const populations = await Promise.all(POPULATIONS.map(async ([id, framePath, truthPath]) => ({
    id,
    frame: JSON.parse(await readFile(new URL(framePath, ROOT), "utf8")),
    truth: JSON.parse(await readFile(new URL(truthPath, ROOT), "utf8")),
  })));
  const results = [];
  for (const variant of variants(base.searchV2Config)) {
    const candidate = makeVariantHarness(base, {
      searchV2: true,
      searchV2Config: variant.config,
    });
    const checks = [];
    for (const population of populations) {
      for (const item of population.frame.queries) {
        const queryTruth = population.truth.queries[item.id];
        const ranked = rankQuery(candidate, item.query, { evidence: false });
        const ids = ranked.rows.map(row => row.id);
        for (const requiredId of queryTruth.required_primary_ids || []) {
          const rank = ids.indexOf(String(requiredId));
          checks.push({
            population: population.id,
            query_id: item.id,
            query: item.query,
            required_id: String(requiredId),
            rank: rank < 0 ? null : rank + 1,
          });
        }
      }
    }
    const recovered10 = checks.filter(item => item.rank !== null && item.rank <= 10).length;
    const recovered50 = checks.filter(item => item.rank !== null && item.rank <= 50).length;
    const held = variant.heldQueryIds?.length
      ? checks.filter(item => variant.heldQueryIds.includes(item.query_id))
      : [];
    const heldRecovered10 = held.filter(item => item.rank !== null && item.rank <= 10).length;
    const heldRecovered50 = held.filter(item => item.rank !== null && item.rank <= 50).length;
    results.push({
      id: variant.id,
      withheld: variant.withheld,
      required_anchor_count: checks.length,
      required_recall_at_10: Number((recovered10 / Math.max(1, checks.length)).toFixed(6)),
      required_recall_at_50: Number((recovered50 / Math.max(1, checks.length)).toFixed(6)),
      held_out_anchor_count: held.length,
      held_out_recall_at_10: held.length
        ? Number((heldRecovered10 / held.length).toFixed(6))
        : null,
      held_out_recall_at_50: held.length
        ? Number((heldRecovered50 / held.length).toFixed(6))
        : null,
      held_out_misses_at_50: held.filter(item => item.rank === null || item.rank > 50),
      misses_at_50: checks.filter(item => item.rank === null || item.rank > 50),
      checks,
    });
  }
  const payload = {
    schema_version: 1,
    iteration: 3,
    status: "spent_challenge_leave_out_development_evidence",
    sealed_phase4c_read_or_executed: false,
    methodology: "Program contracts and/or bounded relationship families are removed from a cloned in-memory configuration; production artifacts are not changed.",
    results,
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify(Object.fromEntries(results.map(result => [result.id, {
    recall_at_10: result.required_recall_at_10,
    recall_at_50: result.required_recall_at_50,
    held_out_recall_at_50: result.held_out_recall_at_50,
    misses_at_50: result.misses_at_50.map(item => `${item.query_id}:${item.required_id}`),
  }])), null, 2));
}

await main();
