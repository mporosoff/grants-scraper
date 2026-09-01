import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [workflowSource, querySource, app, hybrid, searchPage, help] = await Promise.all([
  readFile(new URL("assets/result-workflow.js", root), "utf8"),
  readFile(new URL("assets/search-query.js", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("assets/search-hybrid.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("assets/site-help.js", root), "utf8"),
]);

function loadWorkflow() {
  const context = { globalThis: {} };
  vm.runInNewContext(querySource, context, { filename: "search-query.js" });
  vm.runInNewContext(workflowSource, context, { filename: "result-workflow.js" });
  return context.globalThis.FUNDING_RESULT_WORKFLOW;
}

test("AI-expanded matches retain bounded Strong objects without mutating the ordinary baseline", () => {
  const workflow = loadWorkflow();
  const baseStrong = { id: "strong", index: 0, workflowTier: "strong" };
  const basePotential = {
    id: "potential",
    index: 1,
    workflowTier: "potential",
    hybridExplanation: {
      source_field: "parent_description",
      source_label: "Opportunity description",
      excerpt: "A public source sentence supporting the submitted topic.",
    },
  };
  const expanded = [
    { id: "new-ai", index: 9, score: 42 },
    { id: "potential", index: 1, score: 41 },
    { id: "strong", index: 0, score: 40 },
  ];
  const originalIds = [baseStrong.id, basePotential.id];
  const candidates = workflow.buildCandidateMatchMap({
    candidates: expanded,
    baseMatches: [baseStrong, basePotential],
    idForMatch: match => match.id,
    limit: 32,
  });

  assert.notEqual(candidates.get("new-ai"), expanded[0]);
  assert.equal(candidates.get("new-ai").index, 9);
  assert.equal(candidates.get("new-ai").workflowTier, "strong");
  assert.equal(candidates.get("new-ai").aiIdentified, true);
  assert.equal(expanded[0].workflowTier, undefined);
  assert.equal(candidates.get("potential"), basePotential);
  assert.deepEqual(
    workflow.resolveCandidateMatches({
      baseMatches: [baseStrong, basePotential],
      candidateMatches: candidates,
      ids: ["new-ai", "strong"],
      idForMatch: match => match.id,
    }).map(match => match.id),
    ["new-ai", "strong"],
  );
  assert.deepEqual([baseStrong.id, basePotential.id], originalIds);

  const oversized = workflow.buildCandidateMatchMap({
    candidates: Array.from({ length: 40 }, (_, index) => ({ id: `candidate-${index}`, index })),
    baseMatches: [],
    idForMatch: match => match.id,
    limit: 40,
  });
  assert.equal(oversized.size, 32);
});

test("workflow metadata keeps Strong/Potential tier separate from AI provenance", () => {
  const workflow = loadWorkflow();
  assert.equal(workflow.workflowTierLabel({ workflowTier: "strong" }), "Strong");
  assert.equal(workflow.workflowTierLabel({ workflowTier: "potential" }), "Potential");
  assert.equal(workflow.workflowTierLabel({ workflowTier: "ai_candidate" }), "Strong");
  const evidence = workflow.matchMetadata({
    workflowTier: "potential",
    hybridExplanation: {
      source_field: "child_summary",
      source_label: "Child summary",
      excerpt: "Rare earth recycling ".repeat(40),
    },
  });
  assert.equal(evidence.workflow_tier, "potential");
  assert.equal(evidence.potential_evidence.source_field, "child_summary");
  assert.ok(evidence.potential_evidence.excerpt.length <= 360);
  assert.equal(workflow.matchMetadata({ workflowTier: "strong" }).potential_evidence, null);
  const identified = workflow.matchMetadata({
    workflowTier: "strong",
    aiIdentified: true,
    aiPhrases: ["electrochemical carbon conversion"],
  });
  assert.equal(identified.workflow_tier, "strong");
  assert.equal(identified.ai_identified, true);
  assert.deepEqual([...identified.ai_discovery_phrases], ["electrochemical carbon conversion"]);
});

test("AI candidates use the same pagination, save, calendar, chat-jump, and official-link paths", () => {
  assert.match(searchPage, /assets\/result-workflow\.js\?v=ai-feedback-20260901/);
  assert.match(app, /candidateMatches: new Map\(\)/);
  assert.match(app, /RESULT_WORKFLOW_API\.resolveCandidateMatches/);
  assert.match(app, /Math\.ceil\(currentDisplayMatches\(\)\.length \/ PAGE_SIZE\)/);
  assert.match(app, /data-save="\$\{escapeAttribute\(id\)\}"/);
  assert.match(app, /data-calendar="\$\{escapeAttribute\(id\)\}"/);
  assert.match(app, /jumpToResultFromChat[\s\S]*?currentDisplayMatches\(\)/);
  assert.match(app, /const actions = officialActions\(record\)/);
  assert.match(app, /clearAiState[\s\S]*?candidateMatches = new Map\(\)/);
});

test("exports and user-connected AI contexts carry bounded workflow evidence", () => {
  for (const heading of [
    "Workflow tier",
    "Potential evidence source field",
    "Potential evidence excerpt",
  ]) assert.match(app, new RegExp(`"${heading}"`));
  assert.match(app, /compactResultRecord\(record, match, 360,/);
  assert.match(app, /current_results:[\s\S]*?map\(evaluationResultMetadata\)/);
  assert.match(app, /ai_addition_results:[\s\S]*?map\(evaluationResultMetadata\)/);
  assert.match(app, /workflow_tier \\"strong\\" means a conservative local match/);
  assert.match(app, /bounded potential_evidence excerpt supports review but not confirmed fit/);
});

test("hosted Potential matching remains query-only while the page explains the boundary", () => {
  const launch = app.slice(
    app.indexOf("function launchHybridSearch"),
    app.indexOf("function scheduleHybridSearch"),
  );
  assert.match(launch, /context: ""/);
  assert.doesNotMatch(launch, /profile|cv_text|orcid/i);
  assert.match(searchPage, /hosted Potential matching requires a typed topic/);
  assert.match(help, /Your CV, full profile, researcher names, and ORCID publication text are not sent/);
  assert.match(help, /When you explicitly use AI refinement, chat, or an institution question/);
});

test("pending work is shared, filter updates are debounced, and Retry-After disables retry", () => {
  const workflow = loadWorkflow();
  assert.equal(workflow.retryDelaySeconds(110_000, 100_000), 10);
  assert.equal(workflow.retryDelaySeconds(110_000, 109_001), 1);
  assert.equal(workflow.retryDelaySeconds(110_000, 110_000), 0);
  assert.match(hybrid, /const pendingSearches = new Map\(\)/);
  assert.match(hybrid, /pendingSearches\.get\(localSignature\)/);
  assert.match(hybrid, /pendingSearches\.set\(localSignature, pending\)/);
  assert.match(hybrid, /eligible_parent_ids: eligible \? \[\.\.\.eligible\]\.sort\(\) : null/);
  assert.match(app, /pendingSignature === requestSignature/);
  assert.match(app, /HYBRID_FILTER_DEBOUNCE_MS = 180/);
  assert.ok((app.match(/hybridDebounceMs: HYBRID_FILTER_DEBOUNCE_MS/g) || []).length >= 3);
  assert.match(app, /abortController\?\.abort\(\)/);
  assert.match(app, /retryAvailableAt/);
  assert.match(app, /RESULT_WORKFLOW_API\.retryDelaySeconds/);
  assert.match(app, /retryWait \? " disabled" : ""/);
  assert.match(app, /Date\.now\(\) < state\.hybrid\.retryAvailableAt/);
});
