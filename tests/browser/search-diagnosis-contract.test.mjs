import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../../", import.meta.url);

async function json(relative) {
  return JSON.parse(await readFile(new URL(relative, ROOT), "utf8"));
}

const frame = await json("evaluation/search_v2_frame.json");
const holdout = await json("evaluation/search_v2_holdout_frame.json");
const truth = await json("evaluation/search_v2_truth.json");
const live = await json("evaluation/search_v2_live_state.json");
const baseline = await json("evaluation/search_v2_baseline.json");
const diagnosis = await json("evaluation/search_v2_diagnosis.json");
const ablation = await json("evaluation/search_v2_field_ablation.json");

test("search-v2 development and holdout frames are frozen and disjoint", () => {
  assert.equal(frame.queries.length, 49);
  assert.equal(frame.queries.filter(item => item.kind === "reported_hard_gate").length, 3);
  assert.equal(frame.queries.filter(item => item.kind === "adversarial").length, 28);
  assert.equal(frame.queries.filter(item => item.kind === "hard_negative").length, 2);
  assert.equal(holdout.status, "sealed");
  assert.equal(holdout.unlock_phase, 4);
  assert.equal(holdout.queries.length, 24);
  const developmentQueries = new Set(frame.queries.map(item => item.query.toLowerCase()));
  assert.deepEqual(
    holdout.queries.filter(item => developmentQueries.has(item.query.toLowerCase())),
    [],
  );
});

test("all admitted REE-family development results have frozen truth labels", () => {
  const reeFamily = /\b(?:ree|rees|lanthanide)|rare[ .-]?earth/i;
  const missing = baseline.results.flatMap(result => (
    reeFamily.test(result.query)
      ? result.top_results.filter(row => !truth.adjudications[row.id])
        .map(row => `${result.id}:${row.id}`)
      : []
  ));
  assert.deepEqual(missing, []);
  assert.equal(truth.current_direct_ree_fit_count, 0);
  assert.deepEqual(truth.required_anchor_ids, ["360678", "361526", "362061"]);
});

test("live and local Phase 1 baselines reproduce the reported failures", () => {
  const baselineByQuery = new Map(baseline.results.map(item => [item.query, item]));
  for (const observed of live.live_queries) {
    const local = baselineByQuery.get(observed.query);
    assert.ok(local, observed.query);
    assert.equal(local.candidate_count, observed.count, observed.query);
    assert.deepEqual(
      local.top_results.map(row => row.id),
      observed.ids.slice(0, local.top_results.length),
      observed.query,
    );
  }
  assert.deepEqual(diagnosis.reported_failures.REE.ids, ["362900"]);
  assert.equal(diagnosis.reported_failures.REEs.candidate_count, 14);
  assert.equal(diagnosis.reported_failures.REE_separations.candidate_count, 0);
});

test("diagnosis records the unguarded plural and target-topic bypass", () => {
  const byId = new Map(baseline.results.map(item => [item.id, item]));
  const pluralPlan = byId.get("ree_02").query_plan;
  assert.equal(pluralPlan.length, 1);
  assert.equal(pluralPlan[0].source, "rees");
  assert.equal(pluralPlan[0].evidence_alternatives, null);

  const singularPlan = byId.get("ree_01").query_plan;
  assert.equal(singularPlan.length, 1);
  assert.equal(singularPlan[0].source, "ree");
  assert.equal(singularPlan[0].required_unless_topic, "Separations and membranes");
  assert.ok(singularPlan[0].evidence_alternatives.length >= 5);

  assert.equal(byId.get("ree_16").query_plan.length, 1);
  assert.equal(byId.get("ree_16").query_plan[0].source, "r.e.e");
  assert.deepEqual(byId.get("ree_16").query_plan[0].evidence_alternatives, null);
  assert.equal(diagnosis.recommended_repair_track, "B");
  assert.equal(diagnosis.holdout_status, "sealed_and_unopened");
});

test("baseline trace preserves contribution, admission, hierarchy, and explanation evidence", () => {
  const ree = baseline.results.find(item => item.id === "ree_01");
  const workshop = ree.top_results[0];
  assert.equal(workshop.id, "362900");
  assert.equal(workshop.truth.label, "irrelevant");
  assert.equal(workshop.parent_trace.admission.admitted, true);
  assert.ok(workshop.parent_trace.groups.length > 0);
  assert.ok(workshop.parent_trace.groups.some(group => (
    group.matched_terms.some(term => term.fields.length > 0)
  )));
  assert.match(workshop.rendered_explanations.join(" "), /Search terms matched:/);

  const children = baseline.results.flatMap(item => item.top_results)
    .filter(row => row.best_child);
  assert.ok(children.length > 0);
  assert.ok(children.every(row => row.best_child.publication_state === "publishable"));
});

test("field ablation covers every required measurement variant", () => {
  assert.deepEqual(
    ablation.variants.map(item => item.id),
    [
      "production",
      "no_exact_title_bonus",
      "parent_title_flattened",
      "parent_child_titles_separated",
      "metadata_rerank_only",
      "description_child_summary_strengthened",
      "citation_source_strengthened",
      "title_removed_diagnostic",
    ],
  );
  assert.ok(ablation.variants.every(item => item.query_count === frame.queries.length));
  assert.ok(ablation.variants.every(item => item.latency_ms.maximum > 0));
  assert.equal(diagnosis.field_ablation_summary.production_admissions, 674);
});

test("the Phase 1 runner refuses to unlock holdout outcomes", async () => {
  const source = await readFile(new URL("tools/run_search_diagnosis.mjs", ROOT), "utf8");
  assert.match(source, /Phase 1 refuses to open the sealed holdout/);
  assert.match(source, /process\.argv\.includes\("--holdout"\)/);
});
