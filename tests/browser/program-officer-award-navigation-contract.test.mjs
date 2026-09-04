import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import {
  awardMatchesProgramContact,
  makeProgramContact,
  programContactKey,
} from "../../workers/award-api/src/contract.js";
import { createHandler, storeSnapshot, validateSnapshotCreate } from "../../workers/award-api/src/index.js";
import {
  SNAPSHOT_EVIDENCE_ABSTRACT_LIMIT,
  SNAPSHOT_EVIDENCE_INDEXED_ABSTRACT_LIMIT,
  SNAPSHOT_EVIDENCE_LIMIT,
  SNAPSHOT_EVIDENCE_PLAN_FORMAT,
  SNAPSHOT_EVIDENCE_PAYLOAD_LIMIT,
  buildAwardSnapshot,
  snapshotEvidence,
  snapshotPage,
} from "../../workers/award-api/src/snapshot.js";

const root = new URL("../../", import.meta.url);
const [coreSource, pageSource, appSource, aiSource, configSource, deploySource, smokeSource, styleSource] = await Promise.all([
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence-snapshots.js", root), "utf8"),
  readFile(new URL("assets/ai-provider.js", root), "utf8"),
  readFile(new URL("assets/award-api-config.js", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL("tools/smoke_unit_b_award_worker.mjs", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence.css", root), "utf8"),
]);
const contentDigest = value => createHash("sha256").update(value).digest("hex");
const sandbox = { URL, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(coreSource, sandbox);
const core = sandbox.FUNDING_INSTITUTIONAL_INTELLIGENCE;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function contact(name = "Doe, Jane A., Jr.", source = "NSF") {
  return makeProgramContact({
    source,
    sourceDisplayName: name,
    name,
    role: source === "NIH" ? "Program Official" : "Program Officer",
    official_contact_url: "https://example.test/award",
  });
}

function award(index, overrides = {}) {
  const officer = contact();
  return {
    schema_version: 1,
    source: "NSF",
    award_id: `NSF-${String(index).padStart(3, "0")}`,
    title: index === 21 ? "Catalysis carbon conversion platform" : `Advanced materials project ${index}`,
    abstract: index === 20 ? "Catalysis and carbon dioxide conversion evidence outside the first visible page." : "General public project abstract.",
    award_date: [20, 21].includes(index) ? `2000-01-${String(index - 19).padStart(2, "0")}` : `2026-08-${String((index % 28) + 1).padStart(2, "0")}`,
    project_start: "2025-01-01",
    award_year: 2026,
    institution: { name: index % 2 ? "Alpha University" : "Beta Laboratory", normalized_name: index % 2 ? "Alpha University" : "Beta Laboratory" },
    principal_investigators: [{ name: `Researcher ${index}` }],
    program_contacts: [officer],
    program_name: index === 21 ? "Catalysis" : "Materials Research",
    subagency: "Engineering",
    program_codes: ["ENG"],
    official_award_url: `https://example.test/award/${index}`,
    ...overrides,
  };
}

function sourcePayload(records, { complete = true } = {}) {
  return {
    source: "NSF",
    adapter_version: "test",
    results: records,
    total_count: complete ? records.length : null,
    upstream_total_count: records.length,
    raw_record_count: records.length,
    upstream_pages: 1,
    safety_bound_reached: !complete,
    has_more: !complete,
    contact_post_validation: {
      version: "program-contact-v1",
      source: "NSF",
      display_name: "Doe, Jane A., Jr.",
      contact_key: programContactKey("Doe, Jane A., Jr."),
      returned_count: records.length + 1,
      retained_count: records.length,
      rejected_count: 1,
      complete,
    },
    retrieved_at: "2026-08-29T12:00:00.000Z",
  };
}

function programOfficerSnapshot(records = Array.from({ length: 30 }, (_, index) => award(index)), { complete = true, expiresAt = "2026-08-29T14:00:00.000Z" } = {}) {
  return buildAwardSnapshot({
    snapshotId: "a".repeat(64),
    queryId: "b".repeat(64),
    asOf: "2026-08-29T12:00:00.000Z",
    expiresAt,
    request: {
      sources: ["NSF"],
      criteria: {
        mode: "program_officer",
        program_officer: "Doe, Jane A., Jr.",
        program_contact_key: programContactKey("Doe, Jane A., Jr."),
        year_preset: "recent5",
        year_start: 2022,
        year_end: 2026,
      },
    },
    sourcePayloads: { NSF: sourcePayload(records, { complete }) },
  });
}

function retrievalPlan(concepts, { phrases = concepts, exclusions = [], intent = "awards" } = {}) {
  return { intent, concepts, phrases, exclusions };
}

test("Program Officer identity is strict, same-source, person-like, and browser/server coherent", () => {
  const equivalent = [
    "Doe, Jane A., Jr.",
    "Jane A Doe Jr",
    "JANE A. DOE, JR.",
  ];
  const expected = programContactKey(equivalent[0]);
  for (const name of equivalent) {
    assert.equal(programContactKey(name), expected);
    assert.equal(core.programContactKey(name), expected);
  }
  assert.notEqual(programContactKey("Jane Doe Jr"), expected, "a missing middle initial must not be merged");
  assert.notEqual(programContactKey("Jane B Doe Jr"), expected, "a different middle initial must not be merged");
  assert.equal(programContactKey("José O’Neil-Smith"), core.programContactKey("Jose O'Neil-Smith"));
  for (const value of ["DOE Program Manager", "Grants Help Desk", "Award Helpdesk", "NASA HQ", "Office of Science", "support@example.gov", "Program Contact 1234"]) {
    assert.equal(programContactKey(value), null);
    assert.equal(core.programContactKey(value), "");
  }
  const exact = award(1);
  assert.equal(awardMatchesProgramContact(exact, "NSF", expected), true);
  assert.equal(awardMatchesProgramContact({ ...exact, source: "NIH" }, "NSF", expected), false);
  assert.equal(awardMatchesProgramContact({ ...exact, program_contacts: [contact("Jane Doe Jr")] }, "NSF", expected), false);
  assert.equal(core.searchableProgramContact(plain(exact.program_contacts[0]), "NSF"), true);
  assert.equal(core.searchableProgramContact(plain(exact.program_contacts[0]), "NIH"), false);
});

test("Program Officer request, URL, and immutable recent-five-year restoration preserve only locked scope", () => {
  const key = core.programContactKey("Doe, Jane A., Jr.");
  const request = plain(core.buildAwardRequest({
    mode: "program_officer",
    agency: "NSF",
    program_officer_source: "NSF",
    program_officer_display_name: "Doe, Jane A., Jr.",
    program_contact_key: key,
    year_preset: "recent5",
    institution: "Must be ignored",
    topic: "Must be ignored",
  }, 50));
  assert.deepEqual(request, {
    sources: ["NSF"],
    criteria: { mode: "program_officer", program_officer: "Doe, Jane A., Jr.", program_contact_key: key, year_preset: "recent5" },
    limit: 25,
    offset: 0,
  });
  assert.throws(() => core.buildAwardRequest({
    mode: "program_officer",
    program_officer_source: "DOD",
    program_officer_display_name: "Doe, Jane A., Jr.",
    program_contact_key: key,
    year_preset: "all",
  }), /identity is invalid/);
  const customRange = {
    mode: "program_officer",
    program_officer_source: "NSF",
    program_officer_display_name: "Doe, Jane A., Jr.",
    program_contact_key: key,
    year_preset: "custom",
    year_start: 1989,
  };
  assert.equal(core.buildAwardRequest({ ...customRange, year_end: 2038 }).criteria.year_end, 2038, "a 50-year custom range remains valid");
  assert.throws(() => core.buildAwardRequest({ ...customRange, year_end: 2039 }), /50 years or fewer/);
  assert.deepEqual(plain(core.buildAwardRequest({ ...customRange, year_start: "", year_end: 2020 }).criteria), {
    mode: "program_officer",
    program_officer: "Doe, Jane A., Jr.",
    program_contact_key: key,
    year_preset: "custom",
    year_end: 2020,
  }, "one valid custom endpoint remains an intentional open range");
  assert.throws(() => core.buildAwardRequest({ ...customRange, year_start: 1988, year_end: 2020 }), /1989 through 2100/);
  assert.throws(() => core.buildAwardRequest({ ...customRange, year_start: 2020, year_end: 2101 }), /1989 through 2100/);
  assert.equal(validateSnapshotCreate({
    sources: ["DOD"],
    criteria: {
      mode: "program_officer",
      program_officer: "Doe, Jane A., Jr.",
      program_contact_key: key,
      year_preset: "all",
    },
  }, { maxResults: 25 }), null, "crafted DoD Program Officer snapshots are rejected server-side");
  const url = core.urlForState("https://example.test/funded_awards.html?unrelated=kept", {
    open: true,
    mode: "program_officer",
    agency: "NSF",
    program_officer_source: "NSF",
    program_officer_display_name: "Doe, Jane A., Jr.",
    program_contact_key: key,
    program_officer: "Doe, Jane A., Jr.",
    year_preset: "recent5",
    year_start: 2022,
    year_end: 2026,
    snapshot_id: "a".repeat(64),
    page: 3,
    page_size: 25,
    facet_type: "institution",
    facet_key: "institution:alpha",
  });
  const restored = plain(core.stateFromSearch(url.search));
  assert.equal(url.searchParams.get("unrelated"), "kept");
  assert.equal(restored.mode, "program_officer");
  assert.equal(restored.program_contact_key, key);
  assert.equal(restored.year_preset, "recent5");
  assert.equal(restored.year_start, "2022");
  assert.equal(restored.year_end, "2026");
  assert.equal(restored.page, 3);
  assert.equal(restored.facet_type, "institution");
  assert.equal(url.searchParams.has("ii_program_officer"), false, "locked links must not carry a broad-search fallback");
  const damaged = plain(core.stateFromSearch(url.href.replace(encodeURIComponent(key), "program-contact-v1:wrong|person")));
  assert.notEqual(damaged.mode, "program_officer");
  assert.equal(damaged.program_officer, "", "a damaged locked identity must not degrade into a broad name search");
});

test("one immutable UTC clock derives recent-five calendar years without a federal-fiscal rollover", () => {
  const body = { sources: ["NIH"], criteria: { mode: "program_officer", program_officer: "Jane A Doe", program_contact_key: programContactKey("Jane A Doe"), year_preset: "recent5" } };
  const config = { maxResults: 25 };
  const beforeFfy = validateSnapshotCreate(body, config, new Date("2026-09-30T23:59:59.999Z"));
  const afterFfy = validateSnapshotCreate(body, config, new Date("2026-10-01T00:00:00.000Z"));
  assert.deepEqual([beforeFfy.publicCriteria.year_start, beforeFfy.publicCriteria.year_end], [2022, 2026]);
  assert.deepEqual([afterFfy.publicCriteria.year_start, afterFfy.publicCriteria.year_end], [2022, 2026]);
  const beforeCalendar = validateSnapshotCreate(body, config, new Date("2026-12-31T23:59:59.999Z"));
  const afterCalendar = validateSnapshotCreate(body, config, new Date("2027-01-01T00:00:00.000Z"));
  assert.deepEqual([beforeCalendar.publicCriteria.year_start, beforeCalendar.publicCriteria.year_end], [2022, 2026]);
  assert.deepEqual([afterCalendar.publicCriteria.year_start, afterCalendar.publicCriteria.year_end], [2023, 2027]);
  assert.deepEqual(validateSnapshotCreate({ ...body, criteria: { ...body.criteria, year_preset: "all" } }, config, new Date("2026-08-29T12:00:00Z")).publicCriteria, { mode: "program_officer", program_officer: "Jane A Doe", program_contact_key: programContactKey("Jane A Doe"), year_preset: "all" });
  assert.deepEqual(validateSnapshotCreate({ ...body, criteria: { ...body.criteria, year_preset: "custom", year_start: 2018, year_end: 2020 } }, config, new Date("2026-08-29T12:00:00Z")).publicCriteria, { mode: "program_officer", program_officer: "Jane A Doe", program_contact_key: programContactKey("Jane A Doe"), year_preset: "custom", year_start: 2018, year_end: 2020 });
});

test("full-snapshot deterministic evidence finds beyond-page matches with stable weighting and bounded payloads", () => {
  const snapshot = programOfficerSnapshot();
  const firstPage = snapshotPage(snapshot, { page: 1, pageSize: 10, facet: { type: "all", key: "" } });
  assert.equal(firstPage.batches.flatMap(batch => batch.results).some(item => item.award_id === "NSF-020"), false);
  const evidence = snapshotEvidence(snapshot, { plan: retrievalPlan(["catalysis", "carbon", "conversion"], { phrases: ["catalysis carbon conversion"] }), limit: 24 });
  assert.equal(evidence.retrieval.records_scanned, 30);
  assert.ok(evidence.awards.some(item => item.award_id === "NSF-020"), "a match outside the visible page must remain discoverable");
  assert.equal(evidence.awards[0].award_id, "NSF-021", "a title/program match must outrank an abstract-only match");
  assert.equal(evidence.awards.find(item => item.award_id === "NSF-020").snapshot_position, 30, "evidence carries an immutable direct-navigation position");
  assert.ok(evidence.awards.length <= SNAPSHOT_EVIDENCE_LIMIT);
  assert.ok(evidence.awards.every(item => item.abstract_excerpt.length <= SNAPSHOT_EVIDENCE_ABSTRACT_LIMIT));
  assert.ok(evidence.retrieval.serialized_characters <= SNAPSHOT_EVIDENCE_PAYLOAD_LIMIT);
  assert.equal(snapshotEvidence(snapshot, { plan: retrievalPlan(["As", "toxicity"]), limit: 24 }), null, "ambiguous alphabetic two-letter concepts are rejected rather than partially searched");
  assert.deepEqual(
    snapshotEvidence(snapshot, { plan: retrievalPlan(["catalysis", "carbon", "conversion"], { phrases: ["catalysis carbon conversion"] }), limit: 24 }).awards.map(item => item.evidence_id),
    evidence.awards.map(item => item.evidence_id),
    "ties and repeated retrieval must remain deterministic",
  );
  const large = programOfficerSnapshot(Array.from({ length: 1_650 }, (_, index) => award(index, {
    title: `Catalysis platform ${index}`,
    abstract: `Carbon dioxide conversion evidence ${index}.`,
  })));
  const largeEvidence = snapshotEvidence(large, { plan: retrievalPlan(["catalysis", "carbon dioxide", "conversion"], { phrases: ["catalysis carbon dioxide conversion"] }), limit: 24 });
  assert.equal(largeEvidence.retrieval.records_scanned, 1_650);
  assert.equal(largeEvidence.retrieval.records_with_score, 1_650);
  assert.equal(largeEvidence.retrieval.records_selected, 24);
  assert.equal(largeEvidence.matched_aggregate.project_count, 1_650);
  assert.equal(largeEvidence.matched_aggregate.investigator_count, 1_650);
  assert.equal(largeEvidence.matched_aggregate.investigators.length, 12);
  assert.equal(largeEvidence.matched_aggregate.facets_truncated.investigators, true);
  assert.ok(largeEvidence.retrieval.serialized_characters <= SNAPSHOT_EVIDENCE_PAYLOAD_LIMIT);
  const largeAnswer = plain(core.deterministicProgramOfficerAnswer({
    question: "Which projects involve catalysis carbon dioxide conversion?",
    intent: "awards",
    aggregate: large.base_aggregate,
    snapshot: large,
    evidencePack: largeEvidence,
  }));
  assert.match(largeAnswer.answer, /1,650 related projects/);
  assert.match(largeAnswer.answer, /24 highest-scoring records/);
});

test("provider concepts gate admission, phrases rank, exclusions filter, and short-token policy is conservative", () => {
  const snapshot = programOfficerSnapshot([
    award(201, { title: "Catalysis platform", abstract: "Carbon conversion research." }),
    award(202, { title: "Quantum sensing platform", abstract: "Precision measurement research." }),
    award(203, { title: "Catalysis platform", abstract: "Quantum sensing for reaction measurements." }),
    award(204, { title: "Catalysis quantum sensing", abstract: "Combustion applications." }),
  ]);
  const plan = retrievalPlan(["catalysis", "quantum sensing"], {
    phrases: ["catalysis quantum sensing"],
    exclusions: ["combustion"],
  });
  const evidence = snapshotEvidence(snapshot, { plan, planFormat: SNAPSHOT_EVIDENCE_PLAN_FORMAT, limit: 24 });
  assert.deepEqual(evidence.awards.map(item => item.award_id), ["NSF-203"]);
  assert.equal(evidence.retrieval.concept_coverage, "all_provider_concepts_same_record");
  assert.equal(evidence.retrieval.required_concept_count, 3);
  assert.equal(evidence.retrieval.phrase_count, 1);
  assert.equal(evidence.retrieval.exclusion_count, 1);
  assert.deepEqual(evidence.awards[0].matched_fields, ["title", "abstract"]);

  const scientific = programOfficerSnapshot([
    award(205, { title: "AI safety for H2 storage", abstract: "Machine learning assurance." }),
    award(206, { title: "ML control of CO2", abstract: "pH monitoring and carbon conversion." }),
    award(207, { title: "Arsenic toxicity", abstract: "As2O3 exposure mechanisms." }),
    award(208, { title: "Toxicity as a concern", abstract: "General exposure mechanisms." }),
    award(209, { title: "T cells for immunotherapy", abstract: "Adaptive immune response." }),
    award(210, { title: "B lymphocytes in vaccine response", abstract: "Humoral immunity." }),
    award(211, { title: "X-rays for materials imaging", abstract: "Coherent diffraction." }),
    award(212, { title: "R language methods", abstract: "Statistical computing." }),
    award(213, { title: "C programming for scientific software", abstract: "Numerical methods." }),
    award(214, { title: "Q-learning for robotic control", abstract: "Reinforcement learning." }),
    award(215, { title: "k-means for materials discovery", abstract: "Clustering methods." }),
    award(216, { title: "p-values in clinical trials", abstract: "Statistical inference." }),
  ]);
  assert.deepEqual(snapshotEvidence(scientific, { plan: retrievalPlan(["AI", "H2"], { phrases: ["AI safety H2"] }), limit: 24 }).awards.map(item => item.award_id), ["NSF-205"]);
  assert.deepEqual(snapshotEvidence(scientific, { plan: retrievalPlan(["ML", "CO2", "pH"], { phrases: ["ML CO2 pH"] }), limit: 24 }).awards.map(item => item.award_id), ["NSF-206"]);
  assert.deepEqual(snapshotEvidence(scientific, { plan: retrievalPlan(["arsenic", "As2O3"], { phrases: ["arsenic As2O3"] }), limit: 24 }).awards.map(item => item.award_id), ["NSF-207"]);
  for (const symbol of ["Am", "As", "At", "Be", "He", "In"]) {
    assert.equal(snapshotEvidence(scientific, { plan: retrievalPlan([symbol, "toxicity"]), limit: 24 }), null, `${symbol} must be rejected without chemical inference`);
  }
  for (const [concept, awardId] of [
    ["T cells", "NSF-209"],
    ["B lymphocytes", "NSF-210"],
    ["X-rays", "NSF-211"],
    ["R language", "NSF-212"],
    ["C programming", "NSF-213"],
    ["Q-learning", "NSF-214"],
    ["k-means", "NSF-215"],
    ["p-values", "NSF-216"],
  ]) {
    const contextualPlan = retrievalPlan([concept]);
    assert.deepEqual(snapshotEvidence(scientific, { plan: contextualPlan, limit: 24 }).awards.map(item => item.award_id), [awardId]);
    assert.deepEqual(plain(core.validateProgramOfficerQuestionPlan(contextualPlan)), contextualPlan);
  }
  assert.equal(snapshotEvidence(scientific, { plan: retrievalPlan(["T"]), limit: 24 }), null, "a one-letter concept without its scientific qualifier is rejected");
  assert.equal(core.validateProgramOfficerQuestionPlan(retrievalPlan(["A study"])), null, "ordinary one-letter grammar cannot become a retrieval concept");

  const longAbstract = `${"background context ".repeat(260)}terminalconcept evidence`;
  assert.ok(longAbstract.indexOf("terminalconcept") > 4_000 && longAbstract.length < SNAPSHOT_EVIDENCE_INDEXED_ABSTRACT_LIMIT);
  const deepAbstract = programOfficerSnapshot([award(209, { title: "Extended abstract evidence", abstract: longAbstract })]);
  assert.deepEqual(snapshotEvidence(deepAbstract, { plan: retrievalPlan(["terminalconcept"]), limit: 24 }).awards.map(item => item.award_id), ["NSF-209"]);

  assert.deepEqual(plain(core.validateProgramOfficerQuestionPlan(plan)), plan);
  assert.equal(core.validateProgramOfficerQuestionPlan(retrievalPlan(["As", "toxicity"])), null);
  assert.deepEqual(plain(core.validateProgramOfficerQuestionPlan({ intent: "count", concepts: [], phrases: [], exclusions: [] })), { intent: "count", concepts: [], phrases: [], exclusions: [] });
  assert.equal(core.validateProgramOfficerQuestionPlan({ intent: "count", concepts: ["catalysis"], phrases: [], exclusions: [] }), null);
});

test("topic-qualified answer intents use structured metadata and retain investigator and institution facets", () => {
  const snapshot = programOfficerSnapshot([
    award(301, { award_year: 2023, award_date: "2023-06-01", principal_investigators: [{ name: "Earlier Researcher" }] }),
    award(302, { award_year: 2024, award_date: "2024-06-01", principal_investigators: [{ name: "Target Researcher" }] }),
  ]);
  const evidence = snapshotEvidence(snapshot, { plan: retrievalPlan(["2024"], { intent: "investigators" }), limit: 24 });
  assert.deepEqual(evidence.awards.map(item => item.award_id), ["NSF-302"]);
  assert.deepEqual(evidence.awards[0].matched_fields, ["year"]);
  const answer = plain(core.deterministicProgramOfficerAnswer({
    question: "Who received awards in FY2024?",
    intent: "investigators",
    aggregate: snapshot.base_aggregate,
    snapshot,
    evidencePack: evidence,
  }));
  assert.match(answer.answer, /Matching investigators: Target Researcher/);
  assert.doesNotMatch(answer.answer, /Earlier Researcher/);
  const institutionEvidence = snapshotEvidence(snapshot, { plan: retrievalPlan(["2024"], { intent: "institutions" }), limit: 24 });
  const institutionAnswer = plain(core.deterministicProgramOfficerAnswer({
    question: "Which institutions received awards in FY2024?",
    intent: "institutions",
    aggregate: snapshot.base_aggregate,
    snapshot,
    evidencePack: institutionEvidence,
  }));
  assert.match(institutionAnswer.answer, /Matching recipient institutions: Beta Laboratory/);
  assert.doesNotMatch(institutionAnswer.answer, /Alpha University/);
  const refreshSource = appSource.slice(
    appSource.indexOf("async function refreshProgramOfficerQuestionAnswer"),
    appSource.indexOf("async function refreshQuestionAnswer"),
  );
  assert.match(refreshSource, /const aggregateSource = topical \? evidencePack\.matched_aggregate : baseAggregate;/);
  assert.match(refreshSource, /ordered_refs: topical \? \[\] :/);
  const renderSource = appSource.slice(
    appSource.indexOf("function renderDirectAnswer"),
    appSource.indexOf("function renderQuestionAnswer"),
  );
  assert.match(renderSource, /aggregate\.investigator_count/);
  assert.match(renderSource, /aggregate\.institution_count/);
  assert.match(renderSource, /aggregate\.program_count/);
  assert.match(renderSource, /Showing the.*most frequent below/);
});

test("provider plans cannot broaden locked snapshot membership or invent award identifiers", () => {
  const snapshot = programOfficerSnapshot([
    award(401, { title: "Smith predictors", abstract: "Statistical estimation methods." }),
    award(402, { title: "Predictors", abstract: "General estimation methods." }),
  ]);
  const evidence = snapshotEvidence(snapshot, { plan: retrievalPlan(["smith", "predictors"]), limit: 24 });
  assert.deepEqual(evidence.awards.map(item => item.award_id), ["NSF-401"]);
  assert.ok(evidence.awards.every(item => snapshot.awards.some(awardRecord => awardRecord.award_id === item.award_id)));
  assert.equal(evidence.exact_total, 2, "provider-selected concepts cannot alter the deterministic portfolio total");
});

test("snapshot-native institutions, coverage, abstract facts, and absence language remain explicit", () => {
  const complete = programOfficerSnapshot();
  assert.equal(complete.mode, "program_officer");
  assert.equal(complete.program_officer.membership_rule, "exact_same_source_program_contact_key");
  assert.equal(complete.coverage_state, "complete");
  assert.equal(complete.abstract_coverage.total_records, 30);
  assert.equal(complete.base_aggregate.institution_count, 2);
  const institution = complete.base_aggregate.institutions.find(item => item.name === "Alpha University");
  const page = snapshotPage(complete, { page: 1, pageSize: 10, facet: { type: "institution", key: institution.key } });
  assert.equal(page.aggregate.project_count, institution.projects);
  assert.deepEqual(page.base_aggregate.ordered_refs, [], "facet payloads stay bounded instead of duplicating full award references");
  const renderPageSource = appSource.slice(appSource.indexOf("function baseAggregateForPage"), appSource.indexOf("async function fetchPage"));
  assert.match(renderPageSource, /ordered_refs: Array\.isArray\(previous\?\.ordered_refs\) \? previous\.ordered_refs : \[\]/);
  assert.match(renderPageSource, /state\.baseAggregate = baseAggregateForPage\(payload, state\.baseAggregate\)/);
  const countOnlyAnswer = plain(core.deterministicInstitutionAnswer({
    question: "Which awards are in this snapshot?",
    intent: "awards",
    aggregate: { ...complete.base_aggregate, ordered_refs: [] },
    sources: complete.sources,
  }));
  assert.equal(countOnlyAnswer.answer, "30 matching awards are in these results; award titles are unavailable in this view.");
  const legacyCached = structuredClone(complete);
  delete legacyCached.base_aggregate.institutions;
  assert.deepEqual(snapshotPage(legacyCached, { page: 1, pageSize: 10 }).aggregate.institutions, [], "pre-deploy cached snapshots remain readable during rollout");
  assert.equal(snapshotPage(legacyCached, { page: 1, pageSize: 10, facet: { type: "institution", key: "missing" } }), null);
  const incomplete = programOfficerSnapshot([], { complete: false });
  assert.equal(incomplete.coverage_state, "safety_bounded");
  const answer = plain(core.deterministicProgramOfficerAnswer({ question: "What involved quantum sensing?", intent: "awards", aggregate: incomplete.base_aggregate, snapshot: incomplete, evidencePack: { awards: [], retrieval: { records_with_score: 0 } } }));
  assert.equal(answer.answer, "No related project was identified in the available records, but the source snapshot is incomplete, so this is not a negative finding.");
  const completeNegative = plain(core.deterministicProgramOfficerAnswer({ question: "What involved quantum sensing?", intent: "awards", aggregate: complete.base_aggregate, snapshot: complete, evidencePack: { awards: [], retrieval: { records_with_score: 0 } } }));
  assert.match(completeNegative.answer, /scoped snapshot result, not a complete-career claim/);
  const partialPayload = sourcePayload([award(1)]);
  partialPayload.total_count = null;
  partialPayload.has_more = true;
  partialPayload.safety_bound_reached = false;
  partialPayload.contact_post_validation.complete = false;
  const partial = buildAwardSnapshot({
    snapshotId: "f".repeat(64), queryId: "1".repeat(64), asOf: "2026-08-29T12:00:00.000Z",
    request: complete.request,
    sourcePayloads: { NSF: partialPayload },
  });
  assert.equal(partial.coverage_state, "partial");
  assert.equal(partial.exact_total, null);
  for (const [status, expected] of [["rate_limited", "rate_limited"], ["unsupported", "unsupported"], ["unavailable", "unavailable"]]) {
    const value = buildAwardSnapshot({
      snapshotId: "d".repeat(64), queryId: "e".repeat(64), asOf: "2026-08-29T12:00:00.000Z",
      request: complete.request,
      sourcePayloads: { NSF: { source: "NSF", status, error: { code: status } } },
    });
    assert.equal(value.coverage_state, expected);
    assert.equal(value.exact_total, null);
    assert.equal(value.at_least, 0);
  }
});

test("upstream contact search is post-validated before complete totals and cached metadata", async () => {
  class MemoryCache {
    constructor() { this.values = new Map(); }
    async match(request) { return this.values.get(request.url)?.clone() || null; }
    async put(request, response) { this.values.set(request.url, response.clone()); }
  }
  const cache = new MemoryCache();
  let upstreamCalls = 0;
  const rawAward = (id, poName) => ({
    id,
    title: `Award ${id}`,
    awardeeName: "Test University",
    pdPIName: "Test Investigator",
    poName,
    fundProgramName: "Test Program",
    orgLongName: "Engineering",
    date: "08/01/2026",
    startDate: "01/01/2026",
    expDate: "12/31/2028",
  });
  const handler = createHandler({
    cache,
    now: () => new Date("2026-08-29T12:00:00.000Z"),
    fetchImpl: async url => {
      assert.match(String(url), /api\.nsf\.gov/);
      upstreamCalls += 1;
      return new Response(JSON.stringify({ response: {
        award: [rawAward("EXACT", "Doe, Jane A., Jr."), rawAward("PREFIX", "Jane Doe Jr")],
        pagination: { totalCount: 2 },
      } }), { headers: { "Content-Type": "application/json" } });
    },
  });
  const env = {
    AWARD_API_ENABLED: "true", CACHE_TTL_SECONDS: "3600", MAX_SOURCE_RESULTS: "25",
    AWARD_SOURCE_RATE_LIMIT: "12", ROR_SEARCH_RATE_LIMIT: "60", ROR_RESOLVE_RATE_LIMIT: "20",
    AWARD_RATE_LIMIT_SECRET: "post-validation-test-secret",
    AWARD_RATE_LIMITER: { idFromName: value => value, get: () => ({ fetch: async () => new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } }) }) },
  };
  const body = { sources: ["NSF"], criteria: { mode: "program_officer", program_officer: "Doe, Jane A., Jr.", program_contact_key: programContactKey("Doe, Jane A., Jr."), year_preset: "recent5" } };
  const request = () => new Request("https://award.test/awards/snapshots", { method: "POST", headers: { Origin: "https://mporosoff.github.io", "Content-Type": "application/json" }, body: JSON.stringify(body) });
  for (let index = 0; index < 2; index += 1) {
    const response = await handler(request(), env);
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.completeness, "complete");
    assert.equal(payload.exact_total, 1);
    assert.equal(payload.at_least, 1);
    assert.deepEqual(payload.sources[0].contact_post_validation, {
      version: "program-contact-v1", source: "NSF", display_name: "Doe, Jane A., Jr.", contact_key: programContactKey("Doe, Jane A., Jr."),
      returned_count: 2, retained_count: 1, rejected_count: 1, complete: true,
    });
    assert.deepEqual(payload.initial_batches[0].results.map(item => item.award_id), ["EXACT"]);
  }
  assert.equal(upstreamCalls, 1, "the cache hit is revalidated without losing original returned/rejected counts");
});

test("evidence endpoint is Program-Officer-only, origin-protected, expiration-aware, and rate-controlled", async () => {
  class MemoryCache {
    constructor() { this.values = new Map(); }
    async match(request) { return this.values.get(request.url)?.clone() || null; }
    async put(request, response) { this.values.set(request.url, response.clone()); }
  }
  const cache = new MemoryCache();
  const snapshot = programOfficerSnapshot();
  await storeSnapshot(cache, snapshot, 3600);
  const buckets = [];
  const env = {
    AWARD_API_ENABLED: "true",
    CACHE_TTL_SECONDS: "3600",
    MAX_SOURCE_RESULTS: "25",
    AWARD_SOURCE_RATE_LIMIT: "12",
    ROR_SEARCH_RATE_LIMIT: "60",
    ROR_RESOLVE_RATE_LIMIT: "20",
    AWARD_RATE_LIMIT_SECRET: "program-officer-evidence-secret",
    AWARD_RATE_LIMITER: {
      idFromName: value => value,
      get: () => ({ fetch: async (_url, init) => {
        buckets.push(JSON.parse(init.body).bucket);
        return new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } });
      } }),
    },
  };
  const handler = createHandler({ cache, now: () => new Date("2026-08-29T12:30:00.000Z"), fetchImpl: async () => { throw new Error("no upstream"); } });
  const request = (body, origin = "https://mporosoff.github.io") => new Request("https://award.test/awards/snapshots/evidence", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const evidenceBody = body => ({ plan_format: SNAPSHOT_EVIDENCE_PLAN_FORMAT, ...body });
  const response = await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan(["catalysis"]), limit: 24 })), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).retrieval.records_scanned, 30);
  assert.ok(buckets.includes("award:evidence"));
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan(["catalysis"], { intent: "topical" }), limit: 24 })), env)).status, 400, "unsupported answer intents are rejected");
  const privatePhrase = "retrieval-private-marker";
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan([privatePhrase]), limit: 24 })), env)).status, 200);
  const storedSnapshot = await [...cache.values.entries()].find(([url]) => url.includes("award-snapshot.internal"))[1].clone().text();
  assert.doesNotMatch(storedSnapshot, new RegExp(privatePhrase), "provider retrieval plans must not be persisted into the snapshot cache");
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan([]), limit: 24 })), env)).status, 400);
  assert.equal((await handler(request({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan(["catalysis"]), limit: 24 }), env)).status, 400, "the plan format is mandatory");
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, retrieval_plan: retrievalPlan(["catalysis"]), limit: 24 }), "https://evil.example"), env)).status, 403);

  const expired = programOfficerSnapshot([], { expiresAt: "2026-08-29T12:29:59.999Z" });
  expired.snapshot_id = "c".repeat(64);
  await storeSnapshot(cache, expired, 3600);
  assert.equal((await handler(request(evidenceBody({ snapshot_id: expired.snapshot_id, retrieval_plan: retrievalPlan(["catalysis"]), limit: 24 })), env)).status, 410);
  assert.equal(core.validateNarrativeAnswer({ claims: [{ text: "Unsupported", evidence_ids: ["NSF:NOT-IN-EVIDENCE"] }] }, [{ evidence_id: "NSF:KNOWN" }]), null);
});

test("served page exposes one coherent Program Officer cache identity and the browser uses full-snapshot evidence", () => {
  for (const [asset, source] of [
    ["institutional-intelligence.css", styleSource],
    ["award-api-config.js", configSource],
    ["institutional-intelligence-core.js", coreSource],
    ["institutional-intelligence-snapshots.js", appSource],
    ["ai-provider.js", aiSource],
  ]) {
    assert.match(pageSource, new RegExp(`${asset.replace(".", "\\.")}\\?v=${contentDigest(source)}`));
  }
  assert.match(appSource, /Search this contact’s recent/);
  assert.match(pageSource, /id="ii-year-preset"/);
  assert.match(pageSource, /id="ii-institutions"/);
  assert.match(configSource, /snapshotEvidenceUrl/);
  assert.match(appSource, /programOfficerEvidence/);
  assert.match(appSource, /plan_format: "provider-concepts-v1"/);
  assert.match(appSource, /operation: "program_officer_question_plan"/);
  assert.match(appSource, /operation: "program_officer_evidence_answer"/);
  assert.match(appSource, /Hosted AI included/);
  assert.match(appSource, /questionState\.provider === "hosted"/);
  assert.match(aiSource, /program_officer_question_plan_v1/);
  assert.match(aiSource, /program_officer_evidence_answer_v1/);
  assert.doesNotMatch(coreSource, /programOfficerRetrievalPhrases|caseSensitiveScientificSymbols|explicit_notation/);
  assert.match(appSource, /records_scanned/);
  assert.doesNotMatch(appSource.slice(appSource.indexOf("function programOfficerEvidence"), appSource.indexOf("function refreshProgramOfficerQuestionAnswer")), /residentAwards/);
  assert.match(deploySource, /program-officer-evidence-v4/);
  assert.match(deploySource, /provider-concepts-v1/);
  assert.match(deploySource, /all_provider_concepts_same_record/);
  assert.match(deploySource, /matched_facet_limit/);
  assert.match(deploySource, /indexed_abstract_characters_per_record/);
  assert.match(smokeSource, /retrieval_plan: \{ intent: "awards", concepts: \[evidenceConcept\]/);
  assert.doesNotMatch(smokeSource, /intent: "topical"/);
});
