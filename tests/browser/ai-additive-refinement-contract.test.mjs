import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [workflowSource, appSource, pageSource, cssSource, profileSource] = await Promise.all([
  readFile(new URL("assets/result-workflow.js", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("assets/app.css", root), "utf8"),
  readFile(new URL("assets/profile.js", root), "utf8"),
]);

function loadWorkflow() {
  const context = { Date, Map, Math, Number, Object, Set, String };
  context.globalThis = context;
  vm.runInNewContext(workflowSource, context, { filename: "result-workflow.js" });
  return context.FUNDING_RESULT_WORKFLOW;
}

function ids(values) {
  return [...values].map(value => value.id);
}

test("realistic alternative phrases remain independent retrieval paths and generic terms cannot admit", () => {
  const workflow = loadWorkflow();
  const raw = [
    "reaction engineering",
    "heterogeneous catalyst design",
    "electrochemical carbon conversion",
    "carbon dioxide utilization",
    "catalytic reactor systems",
    "surface reaction kinetics",
    "sustainable chemical manufacturing",
    "porous catalytic materials",
    "low carbon fuels synthesis",
    "process intensification catalysis",
    "Research",
    "science",
    "technology",
    "health",
    "innovation",
    "energy",
    " reaction engineering ",
  ];
  const phrases = workflow.sanitizeAlternativePhrases(raw);
  assert.deepEqual([...phrases], raw.slice(0, 10));

  const calls = [];
  const byPhrase = new Map(phrases.map((phrase, index) => [phrase, [
    { id: `new-${index}`, score: 100 - index, workflowTier: "strong", evidence: { phrase } },
  ]]));
  const candidates = workflow.collectAlternativeCandidates({
    phrases,
    baselineIds: ["ordinary"],
    retrieve(phrase) {
      calls.push(phrase);
      assert.equal(byPhrase.has(phrase), true, "retrieval must receive one intact phrase");
      return byPhrase.get(phrase);
    },
    idForMatch: match => match.id,
    limit: 32,
  });

  assert.deepEqual(calls, [...phrases]);
  assert.equal(calls.includes(phrases.join(" ")), false);
  assert.equal(candidates.length, 10);
  assert.ok(candidates.every(match => match.workflowTier === "strong" && match.aiIdentified));
  assert.ok(candidates.every(match => match.aiPhrases.length === 1));
});

test("only new locally Strong records enter the bounded candidate set", () => {
  const workflow = loadWorkflow();
  const candidates = workflow.collectAlternativeCandidates({
    phrases: [
      "reaction engineering",
      "electrochemical conversion",
      "carbon utilization",
      "surface catalysis",
      "reactor design",
    ],
    baselineIds: ["ordinary-strong", "ordinary-potential"],
    retrieve: phrase => [
      { id: "ordinary-strong", score: 100, workflowTier: "strong" },
      { id: `eligible-${phrase}`, score: 80, workflowTier: "strong" },
      { id: `potential-${phrase}`, score: 99, workflowTier: "potential" },
    ],
    idForMatch: match => match.id,
  });

  assert.equal(candidates.length, 5);
  assert.ok(candidates.every(match => match.id.startsWith("eligible-")));
  assert.ok(candidates.every(match => match.workflowTier === "strong"));
  assert.equal(candidates.some(match => match.id.startsWith("potential-")), false);
});

test("additive merge preserves every ordinary tier and relative order while limiting additions to twelve", () => {
  const workflow = loadWorkflow();
  const ordinary = [
    { id: "strong-a", workflowTier: "strong", score: 91, evidence: { source: "title" } },
    { id: "strong-b", workflowTier: "strong", score: 80, evidence: { source: "child" } },
    { id: "potential-a", workflowTier: "potential", score: .9 },
    { id: "potential-b", workflowTier: "potential", score: .8 },
  ];
  const baseline = workflow.captureOrdinaryBaseline({
    matches: ordinary,
    strongMatches: ordinary.slice(0, 2),
    potentialMatches: ordinary.slice(2),
    page: 2,
    sort: "deadline",
    signature: "immutable-search",
    idForMatch: match => match.id,
  });
  const candidates = Array.from({ length: 18 }, (_, index) => ({
    id: `new-${index}`,
    score: 50 + index,
    workflowTier: "strong",
    aiIdentified: true,
    aiPhrases: [`specific phrase ${index}`],
    aiPhraseOrder: index,
  }));
  const providerAssessments = candidates.map((candidate, index) => ({
    id: candidate.id,
    score: 100 - index,
    verdict: "Possible fit",
    reason: "Bounded assessment",
    concern: "Verify scope",
  }));
  const selected = workflow.selectAssessedAdditions({
    candidates,
    assessments: [
      { ...providerAssessments[0], id: "unknown" },
      providerAssessments[0],
      providerAssessments[0],
      { ...providerAssessments[1], verdict: "unsupported" },
      ...providerAssessments.slice(2),
    ],
    idForMatch: match => match.id,
    limit: 99,
  });
  assert.equal(selected.additions.length, 12);
  assert.deepEqual(ids(selected.additions), [
    "new-17", "new-16", "new-15", "new-14", "new-13", "new-12",
    "new-11", "new-10", "new-9", "new-8", "new-7", "new-6",
  ]);

  const combined = workflow.mergeAdditiveResults({ baseline, additions: selected.additions });
  assert.deepEqual(ids(combined).slice(0, 2), ["strong-a", "strong-b"]);
  assert.deepEqual(ids(combined).slice(-2), ["potential-a", "potential-b"]);
  assert.ok(baseline.ids.every(id => ids(combined).includes(id)));
  assert.ok(combined.slice(2, -2).every(match => (
    match.workflowTier === "strong" && match.aiIdentified === true
  )));
});

test("baseline capture is immutable and exact restoration includes evidence, counts, page, and sort", () => {
  const workflow = loadWorkflow();
  const source = [
    { id: "s", workflowTier: "strong", score: 17, evidence: { terms: ["catalysis"] } },
    { id: "p", workflowTier: "potential", score: .7, hybridExplanation: { excerpt: "public passage" } },
  ];
  const baseline = workflow.captureOrdinaryBaseline({
    matches: source,
    strongMatches: source.slice(0, 1),
    potentialMatches: source.slice(1),
    page: 4,
    sort: "agency",
    signature: "query+profile+filters+sort",
    idForMatch: match => match.id,
  });
  source[0].evidence.terms[0] = "mutated";
  source.reverse();
  assert.deepEqual([...baseline.ids], ["s", "p"]);
  assert.deepEqual(JSON.parse(JSON.stringify(baseline.counts)), { total: 2, strong: 1, potential: 1 });
  assert.equal(baseline.matches[0].evidence.terms[0], "catalysis");
  assert.equal(Object.isFrozen(baseline), true);
  assert.equal(Object.isFrozen(baseline.matches[0].evidence), true);

  const restored = workflow.restoreOrdinaryBaseline(baseline);
  assert.deepEqual(ids(restored.matches), ["s", "p"]);
  assert.equal(restored.matches[0].score, 17);
  assert.equal(restored.matches[0].evidence.terms[0], "catalysis");
  assert.equal(restored.page, 4);
  assert.equal(restored.sort, "agency");
});

test("empty, duplicate, unknown, and unsupported assessments produce no additions", () => {
  const workflow = loadWorkflow();
  const candidates = [{
    id: "qualified",
    score: 10,
    workflowTier: "strong",
    aiIdentified: true,
  }];
  for (const assessments of [
    [],
    [{ id: "unknown", score: 100, verdict: "Strong fit", reason: "", concern: "" }],
    [{ id: "qualified", score: 100, verdict: "Invented fit", reason: "", concern: "" }],
  ]) {
    const selected = workflow.selectAssessedAdditions({
      candidates,
      assessments,
      idForMatch: match => match.id,
    });
    assert.equal(selected.additions.length, 0);
    assert.equal(selected.assessments.size, 0);
  }
});

test("runtime owns a separate refinement overlay, stale identity checks, exact restore, and bounded chat", () => {
  const refine = appSource.slice(
    appSource.indexOf("async function refineWithAi"),
    appSource.indexOf("function renderNofoContext"),
  );
  const restore = appSource.slice(
    appSource.indexOf("function restoreOriginalResults"),
    appSource.indexOf("function selectedFilterCount"),
  );
  const chatIds = appSource.slice(
    appSource.indexOf("function currentChatIds"),
    appSource.indexOf("function hasNofoDocument"),
  );
  assert.match(appSource, /refinement:\s*\{[\s\S]*?baseline: null,[\s\S]*?additions: \[\],[\s\S]*?combinedMatches: \[\],[\s\S]*?requestSequence: 0/);
  assert.match(refine, /await awaitPendingPotential\(sequence, signature\)/);
  assert.match(refine, /refinementRequestIsCurrent\(sequence, signature\)/);
  assert.match(refine, /retrieve: phrase => computeMatches\(phrase, "relevance"\)\.matches/);
  assert.doesNotMatch(refine, /expandedQuery|coverage: false|scheduleHybridSearch/);
  assert.match(refine, /researcher_profile: enabledProfileContext/);
  assert.match(appSource, /function refinementProfileContext\(\)[\s\S]*?state\.profile\.active[\s\S]*?: null/);
  assert.match(profileSource, /profile\.include_cv_in_ai && profile\.cv_text/);
  assert.match(restore, /restoreOrdinaryBaseline\(baseline\)/);
  assert.match(restore, /clearResultFocusPreservingConversation\(\)/);
  assert.doesNotMatch(restore, /clearAiState|clearNofoState|savedItems|savedIds|k-key|currentProfile/);
  assert.match(chatIds, /currentDisplayMatches\(\)[\s\S]*?slice\(0, MAX_CHAT_RESULTS\)/);
  assert.match(appSource, /knownResultIds\([\s\S]*?answer\.referenced_result_ids[\s\S]*?8/);
  assert.match(appSource, /AI refinement was cleared because the search criteria changed/);
  assert.match(appSource, /state\.refinement\.requestSequence \+= 1/);
  assert.match(appSource, /state\.ordinarySearchSignature = refinementSearchSignature\(\)/);
  assert.match(appSource, /function aiRefineSearchIsCurrent\(\)[\s\S]*?state\.ordinarySearchSignature === refinementSearchSignature\(\)/);
});

test("one accessible restore control and search-input controls have the required DOM and responsive order", () => {
  const searchArea = pageSource.slice(
    pageSource.indexOf('id="nofo-drop-zone"'),
    pageSource.indexOf('id="search-status"'),
  );
  assert.ok(searchArea.indexOf('id="query"') < searchArea.indexOf('id="find-funding"'));
  assert.ok(searchArea.indexOf('id="find-funding"') < searchArea.indexOf('id="nofo-file"'));
  assert.equal((pageSource.match(/id="restore-ai-refinement"/g) || []).length, 1);
  assert.equal((pageSource.match(/>Restore original results<\/button>/g) || []).length, 1);
  assert.doesNotMatch(pageSource, /Hide AI/);
  assert.match(cssSource, /\.search-workflow \.search-form\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto auto/s);
  assert.match(cssSource, /@media \(max-width: 820px\)[\s\S]*?\.search-workflow \.search-form\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s);
  assert.match(cssSource, /@media \(forced-colors: active\)/);
  assert.match(cssSource, /@media \(prefers-reduced-motion: reduce\)/);
});
