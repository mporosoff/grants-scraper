import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [
  appSource,
  hybridSource,
  workerSource,
  wranglerSource,
  configSource,
  manifest,
  vectorBuffer,
  results,
  productTruth,
  gate,
  historicalIntentGate,
  coherenceTrace,
] = await Promise.all([
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("assets/search-hybrid.js", root), "utf8"),
  readFile(new URL("workers/search-voyage-proxy/src/index.js", root), "utf8"),
  readFile(new URL("workers/search-voyage-proxy/wrangler.jsonc", root), "utf8"),
  readFile(new URL("assets/app-config.js", root), "utf8"),
  readFile(new URL("data/search-v2-voyage-manifest.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/search-v2-voyage-vectors.f16", root)),
  readFile(new URL("evaluation/search_v2_strong_potential_results.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/search_v2_strong_potential_truth.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/search_v2_strong_potential_gate_report.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/search_v2_intent_gate_gate_report.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/search_v2_strong_coherence_root_causes.json", root), "utf8").then(JSON.parse),
]);

test("the disabled browser contract renders Strong before bounded deduplicated Potential", () => {
  assert.match(configSource, /searchV2:\s*false/);
  assert.match(appSource, /const POTENTIAL_MATCH_LIMIT = 12/);
  assert.match(appSource, /state\.matches = \[\.\.\.state\.strongMatches, \.\.\.state\.potentialMatches\]/);
  assert.match(appSource, /\.filter\(match => !strongIds\.has/);
  assert.match(appSource, /Strong matches/);
  assert.match(appSource, /Potential matches/);
  assert.match(appSource, /No strong matches found/);
  assert.match(appSource, /Why this may be relevant/);
  assert.doesNotMatch(appSource, /Voyage score|Matched because semantic similarity/);
  results.rows.forEach(row => {
    assert.equal(row.potential.ids.length <= 12, true, row.id);
    assert.deepEqual(row.deduplication_overlap, [], row.id);
    assert.deepEqual(
      row.combined.visible_ids,
      [...row.strong.ids, ...row.potential.ids],
      row.id,
    );
  });
});

test("Potential uses the preserved hybrid retrieval path without a live intent judge", () => {
  assert.match(hybridSource, /voyage-4-lite/);
  assert.match(hybridSource, /rerank-2\.5/);
  assert.match(hybridSource, /fuseCandidates/);
  assert.match(hybridSource, /deterministicSafeguard/);
  assert.match(hybridSource, /strongestParents/);
  assert.doesNotMatch(hybridSource, /\/judge|JUDGE_MODEL|intent_classification/);
  assert.doesNotMatch(workerSource, /\/judge|JUDGE_MODEL|env\?\.AI|AI\.run/);
  assert.doesNotMatch(wranglerSource, /"ai"|"binding"\s*:\s*"AI"/i);
  assert.deepEqual(results.architecture.proxy_endpoints, ["/embed-query", "/rerank"]);
  assert.equal(results.product_contract.live_intent_judge, false);
  assert.equal(results.product_contract.semantic_score_creates_primary_evidence, false);
  assert.equal(historicalIntentGate.decision.includes("INTENT GATE"), true);
});

test("the static vector handshake and safety boundary remain intact", () => {
  assert.equal(results.static_assets.passage_count, 1659);
  assert.equal(results.static_assets.corpus_sha256, manifest.corpus_sha256);
  assert.equal(results.static_assets.vector_sha256, manifest.vector_sha256);
  assert.equal(createHash("sha256").update(vectorBuffer).digest("hex"), manifest.vector_sha256);
  assert.equal(vectorBuffer.byteLength, 3_397_632);
  assert.equal(results.safety.sealed_acceptance_population_read_or_executed, false);
  assert.equal(results.safety.private_profile_cv_or_orcid_sent, false);
  assert.equal(results.safety.secret_printed_or_persisted, false);
});

test("spent product metrics pass the atomic Strong-coherence gates without losing discovery", () => {
  const metrics = results.quality.global;
  assert.equal(metrics.strong.precision_at_10_over_reviewed, 1);
  assert.equal(metrics.strong.known_irrelevant_at_10_count, 0);
  assert.equal(metrics.strong.zero_anchor_visible_count, 0);
  assert.equal(metrics.combined.required_recall_at_10, 0.861538);
  assert.equal(metrics.combined.required_recall_at_20, 0.907692);
  assert.equal(metrics.combined.required_recall_at_50, 0.953846);
  assert.equal(metrics.potential.maximum_displayed_count, 12);
  assert.equal(metrics.potential.top_10_known_irrelevant_count, 5);
  assert.equal(metrics.potential.top_10_reviewed_primary_count, 50);
  assert.equal(results.quality.acronym_safeguard.appears_in_strong, false);
  assert.deepEqual(gate.blocking_gates, []);
  assert.equal(gate.phase4c_authorized_for_separate_session, true);
});

test("the generic coherence rule removes both traced non-primary Strong results", () => {
  assert.equal(coherenceTrace.root_cause.shared_generic_bug, true);
  assert.equal(coherenceTrace.root_cause.separate_rule_needed, false);
  assert.deepEqual(
    coherenceTrace.reviewed_non_primary_strong.map(item => item.result_id),
    ["334326", "363316"],
  );
  const health = results.rows.find(row => row.id === "hold_health_02");
  const diplomacy = results.rows.find(row => row.id === "hold_energy_02");
  const geospace = results.rows.find(row => row.id === "i2hold_space_02");
  assert.deepEqual(health.strong.ids, []);
  assert.equal(diplomacy.strong.ids.includes("363316"), false);
  assert.equal(diplomacy.potential.ids.includes("363316"), true);
  assert.equal(geospace.strong.ids.includes("356536"), false);
  assert.equal(geospace.potential.ids.includes("356536"), true);
});

test("new truth is exact-pair scoped and does not rewrite historical holdout truth", () => {
  assert.equal(productTruth.judgments.hold_health_02["334326"].label, "irrelevant");
  assert.match(productTruth.judgments.hold_health_02["334326"].evidence, /separate educational tracks/);
  assert.equal(productTruth.sealed_phase4c_read_or_executed, false);
});
