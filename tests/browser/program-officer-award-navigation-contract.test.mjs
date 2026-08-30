import assert from "node:assert/strict";
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
  SNAPSHOT_EVIDENCE_PHRASE_FORMAT,
  SNAPSHOT_EVIDENCE_PAYLOAD_LIMIT,
  buildAwardSnapshot,
  snapshotEvidence,
  snapshotPage,
} from "../../workers/award-api/src/snapshot.js";

const root = new URL("../../", import.meta.url);
const [coreSource, pageSource, appSource, configSource, deploySource] = await Promise.all([
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence-snapshots.js", root), "utf8"),
  readFile(new URL("assets/award-api-config.js", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
]);
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
  const evidence = snapshotEvidence(snapshot, { phrases: ["catalysis carbon conversion"], limit: 24 });
  assert.equal(evidence.retrieval.records_scanned, 30);
  assert.ok(evidence.awards.some(item => item.award_id === "NSF-020"), "a match outside the visible page must remain discoverable");
  assert.equal(evidence.awards[0].award_id, "NSF-021", "a title/program match must outrank an abstract-only match");
  assert.equal(evidence.awards.find(item => item.award_id === "NSF-020").snapshot_position, 30, "evidence carries an immutable direct-navigation position");
  assert.ok(evidence.awards.length <= SNAPSHOT_EVIDENCE_LIMIT);
  assert.ok(evidence.awards.every(item => item.abstract_excerpt.length <= SNAPSHOT_EVIDENCE_ABSTRACT_LIMIT));
  assert.ok(evidence.retrieval.serialized_characters <= SNAPSHOT_EVIDENCE_PAYLOAD_LIMIT);
  assert.deepEqual(snapshotEvidence(snapshot, { phrases: ["awards projects funding"], limit: 24 }).awards, [], "generic words must not dominate retrieval");
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["catalysis carbon conversion"], limit: 24 }).awards.map(item => item.evidence_id),
    evidence.awards.map(item => item.evidence_id),
    "ties and repeated retrieval must remain deterministic",
  );
  const large = programOfficerSnapshot(Array.from({ length: 1_650 }, (_, index) => award(index, {
    title: `Catalysis platform ${index}`,
    abstract: `Carbon dioxide conversion evidence ${index}.`,
  })));
  const largeEvidence = snapshotEvidence(large, { phrases: ["catalysis carbon dioxide conversion"], limit: 24 });
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
    intent: "topical",
    aggregate: large.base_aggregate,
    snapshot: large,
    evidencePack: largeEvidence,
  }));
  assert.match(largeAnswer.answer, /1,650 related projects/);
  assert.match(largeAnswer.answer, /24 highest-scoring records/);
});

test("topical evidence requires every substantive query concept in the same award", () => {
  const snapshot = programOfficerSnapshot([
    award(201, { title: "Catalysis platform", abstract: "Carbon conversion research." }),
    award(202, { title: "Quantum sensing platform", abstract: "Precision measurement research." }),
    award(203, { title: "Catalysis platform", abstract: "Quantum sensing for reaction measurements." }),
  ]);
  const phrases = plain(core.programOfficerRetrievalPhrases("Which projects involve catalysis and quantum sensing?"));
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which investigators work on catalysis and quantum sensing?")), ["catalysis quantum sensing"]);
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which institutions received catalysis awards?")), ["catalysis"]);
  const evidence = snapshotEvidence(snapshot, { phrases, limit: 24 });
  assert.deepEqual(evidence.awards.map(item => item.award_id), ["NSF-203"]);
  const topicalStarter = programOfficerSnapshot([
    award(204, { title: "Quantum control", abstract: "Precision methods." }),
    award(205, { title: "Show quantum control", abstract: "Explicit topical vocabulary." }),
  ]);
  assert.deepEqual(
    snapshotEvidence(topicalStarter, { phrases: ["show quantum control"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-205"],
    "the Worker treats browser-packed normalized concepts literally and preserves every required concept",
  );
  const shortConcepts = programOfficerSnapshot([
    award(206, { title: "AI safety", abstract: "Machine learning assurance." }),
    award(207, { title: "Safety engineering", abstract: "General assurance." }),
    award(208, { title: "ML safety", abstract: "Machine learning assurance." }),
    award(209, { title: "As toxicity", abstract: "Arsenic exposure mechanisms." }),
    award(210, { title: "Toxicity as a concern", abstract: "General exposure mechanisms." }),
    award(211, { title: "In semiconductor devices", abstract: "Indium transport layers." }),
    award(212, { title: "Semiconductor transport in devices", abstract: "General device physics." }),
    award(213, { title: "Semiconductor manufacturing", abstract: "In semiconductor manufacturing, process controls improve yield." }),
    award(214, { title: "Toxicity controls", abstract: "As toxicity increases, process controls improve." }),
    award(216, { title: "In 2024 catalysis research", abstract: "Catalysis process controls." }),
    award(217, { title: "In-doped catalysis", abstract: "Doped catalyst synthesis." }),
    award(218, { title: "As (III) oxidation", abstract: "Oxidation-state measurements." }),
  ]);
  assert.deepEqual(
    snapshotEvidence(shortConcepts, { phrases: ["ai safety"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-206"],
    "a two-character concept remains mandatory under all-concepts same-record admission",
  );
  assert.deepEqual(
    snapshotEvidence(shortConcepts, { phrases: ["As toxicity"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-209"],
    "an exact scientific symbol is not satisfied by the same lowercase grammar token",
  );
  assert.deepEqual(
    snapshotEvidence(shortConcepts, { phrases: ["In semiconductor"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-211"],
    "an In concept is not satisfied by the ordinary preposition in",
  );
  assert.deepEqual(
    snapshotEvidence(shortConcepts, { phrases: ["In catalysis"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-217"],
    "a following year does not establish chemical notation while an adjacent -doped modifier does",
  );
  assert.deepEqual(
    snapshotEvidence(shortConcepts, { phrases: ["As oxidation"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-218"],
    "a compact Roman oxidation state establishes explicit chemical notation",
  );
  const longAbstract = `${"background context ".repeat(260)}terminalconcept evidence`;
  assert.ok(longAbstract.indexOf("terminalconcept") > 4_000 && longAbstract.length < SNAPSHOT_EVIDENCE_INDEXED_ABSTRACT_LIMIT);
  const deepAbstract = programOfficerSnapshot([
    award(215, { title: "Extended abstract evidence", abstract: longAbstract }),
  ]);
  assert.deepEqual(
    snapshotEvidence(deepAbstract, { phrases: ["terminalconcept"], phraseFormat: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, limit: 24 }).awards.map(item => item.award_id),
    ["NSF-215"],
    "matching tokenizes the full retained abstract beyond the former 4,000-character cutoff",
  );
  assert.equal(evidence.retrieval.concept_coverage, "all_substantive_query_concepts_same_record");
  assert.equal(evidence.retrieval.required_concept_count, 3, "conjunctions and question scaffolding are not substantive concepts");
  assert.deepEqual(evidence.awards[0].matched_fields, ["title", "abstract"]);
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["investigators catalysis quantum sensing"], limit: 24 }).awards.map(item => item.award_id),
    ["NSF-203"],
    "server normalization must not treat aggregate facet nouns as topical concepts",
  );
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["Doe Jane catalysis quantum sensing"], limit: 24 }).awards.map(item => item.award_id),
    ["NSF-203"],
    "server scoring independently removes the immutable snapshot officer identity",
  );
  const investigatorAnswer = plain(core.deterministicProgramOfficerAnswer({
    question: "Which investigators work on catalysis and quantum sensing?",
    intent: "topical",
    aggregateIntent: "investigators",
    aggregate: snapshot.base_aggregate,
    snapshot,
    evidencePack: evidence,
  }));
  assert.match(investigatorAnswer.answer, /Matching investigators: Researcher 203 \(1 matching award\)/);
  assert.doesNotMatch(investigatorAnswer.answer, /Researcher 201|Researcher 202/);
  const institutionAnswer = plain(core.deterministicProgramOfficerAnswer({
    question: "Which institutions received catalysis and quantum sensing awards?",
    intent: "topical",
    aggregateIntent: "institutions",
    aggregate: snapshot.base_aggregate,
    snapshot,
    evidencePack: evidence,
  }));
  assert.match(institutionAnswer.answer, /Matching recipient institutions: Alpha University \(1\)/);
  assert.doesNotMatch(institutionAnswer.answer, /Beta Laboratory/);
});

test("explicit award-year qualifiers use structured metadata and retain topical aggregate facets", () => {
  const snapshot = programOfficerSnapshot([
    award(301, { award_year: 2023, award_date: "2023-06-01", principal_investigators: [{ name: "Earlier Researcher" }] }),
    award(302, { award_year: 2024, award_date: "2024-06-01", principal_investigators: [{ name: "Target Researcher" }] }),
  ]);
  const phrases = plain(core.programOfficerRetrievalPhrases("Who received awards in FY2024?"));
  assert.deepEqual(phrases, ["2024"]);
  const evidence = snapshotEvidence(snapshot, { phrases, limit: 24 });
  assert.deepEqual(evidence.awards.map(item => item.award_id), ["NSF-302"]);
  assert.deepEqual(evidence.awards[0].matched_fields, ["year"]);
  const answer = plain(core.deterministicProgramOfficerAnswer({
    question: "Who received awards in FY2024?",
    intent: "topical",
    aggregateIntent: "investigators",
    aggregate: snapshot.base_aggregate,
    snapshot,
    evidencePack: evidence,
  }));
  assert.match(answer.answer, /Matching investigators: Target Researcher/);
  assert.doesNotMatch(answer.answer, /Earlier Researcher/);
});

test("Worker identity removal is sequence-aware and preserves surname research concepts", () => {
  const snapshot = programOfficerSnapshot([
    award(401, { title: "Smith predictors", abstract: "Statistical estimation methods." }),
    award(402, { title: "Predictors", abstract: "General estimation methods." }),
  ]);
  snapshot.program_officer.display_name = "Jane Smith";
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["Smith predictors"], limit: 24 }).awards.map(item => item.award_id),
    ["NSF-401"],
    "a surname-only topic must not be stripped",
  );
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["Jane Smith smith predictors"], limit: 24 }).awards.map(item => item.award_id),
    ["NSF-401"],
    "only the actual full-name occurrence is stripped when the surname is repeated as a topic",
  );
  snapshot.program_officer.display_name = "J Smith";
  assert.deepEqual(snapshotEvidence(snapshot, { phrases: ["J Smith"], limit: 24 }).awards, [], "a repeated initial-plus-surname identity is removed before scoring");
  assert.deepEqual(
    snapshotEvidence(snapshot, { phrases: ["J Smith smith predictors"], limit: 24 }).awards.map(item => item.award_id),
    ["NSF-401"],
    "short identity components do not consume a repeated surname topic",
  );
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
  const legacyCached = structuredClone(complete);
  delete legacyCached.base_aggregate.institutions;
  assert.deepEqual(snapshotPage(legacyCached, { page: 1, pageSize: 10 }).aggregate.institutions, [], "pre-deploy cached snapshots remain readable during rollout");
  assert.equal(snapshotPage(legacyCached, { page: 1, pageSize: 10, facet: { type: "institution", key: "missing" } }), null);
  const incomplete = programOfficerSnapshot([], { complete: false });
  assert.equal(incomplete.coverage_state, "safety_bounded");
  const answer = plain(core.deterministicProgramOfficerAnswer({ question: "What involved quantum sensing?", intent: "topical", aggregate: incomplete.base_aggregate, snapshot: incomplete, evidencePack: { awards: [] } }));
  assert.equal(answer.answer, "No related project was identified in the available records, but the source snapshot is incomplete, so this is not a negative finding.");
  const completeNegative = plain(core.deterministicProgramOfficerAnswer({ question: "What involved quantum sensing?", intent: "topical", aggregate: complete.base_aggregate, snapshot: complete, evidencePack: { awards: [] } }));
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
  assert.equal(core.programOfficerAggregateIntent("Which projects involve quantum sensing?"), "");
  assert.equal(core.programOfficerAggregateIntent("Which projects are in this snapshot?"), "awards");
  assert.equal(core.programOfficerAggregateIntent("Which awards did this program officer fund?"), "awards");
  assert.equal(core.programOfficerAggregateIntent("What research did they fund?"), "awards");
  assert.equal(core.programOfficerAggregateIntent("What awards did Jane Smith fund?", "Jane Smith"), "awards");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What awards did Jane Smith fund?", "Jane Smith")), []);
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which Jane Smith awards involve quantum sensing?", "Jane Smith")), ["quantum sensing"]);
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which awards use Smith predictors?", "Jane Smith")), ["smith predictors"], "a surname remains topical when the full locked identity is absent");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which Jane Smith awards use Smith predictors?", "Jane Smith")), ["smith predictors"], "only the repeated full-name occurrence is removed");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What awards did Jane Doe fund?", "Doe, Jane A., Jr.")), [], "source last-first order accepts the natural normalized identity");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What awards did J Smith fund?", "J Smith")), [], "initials participate in identity matching without becoming retrieval concepts");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What awards did Jane Li fund?", "Jane Li")), [], "two-letter name components participate in identity matching");
  assert.equal(core.programOfficerAggregateIntent("Where did Jane Smith fund projects?", "Jane Smith"), "institutions");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Where did Jane Smith fund projects?", "Jane Smith")), []);
  assert.equal(core.programOfficerAggregateIntent("Where did Jane Smith fund quantum sensing projects?", "Jane Smith"), "institutions");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Where did Jane Smith fund quantum sensing projects?", "Jane Smith")), ["quantum sensing"]);
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Are there awards about catalysis?")), ["catalysis"], "existential scaffolding is not a required concept");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Could you find awards about quantum sensing?")), ["quantum sensing"], "request scaffolding is not a required concept");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Show me projects about catalysis")), ["catalysis"], "a leading show request is not a required concept");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Can you help me find projects about catalysis?")), ["catalysis"], "a nested help/find request is not a required concept");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Could you show projects about linked list algorithms?")), ["linked list algorithms"], "topic vocabulary after the request clause is preserved");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects show quantum control?")), ["show quantum control"], "non-leading research vocabulary is not globally blacklisted");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects involve AI?")), ["ai"], "two-character acronyms remain substantive");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects involve ML and H2?")), ["ml h2"], "short acronyms and scientific formulas remain substantive");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects involve AI safety?")), ["ai safety"], "short concepts remain required in mixed queries");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects involve As toxicity?")), ["As toxicity"], "case-sensitive element symbols retain their notation");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects involve He cooling and Be alloys?")), ["He cooling Be alloys"], "colliding scientific symbols remain substantive and case-preserved");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects use In semiconductors?")), ["In semiconductors"], "scientific In remains distinct from the preposition in");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects measure pH?")), ["measure pH"], "mixed-case scientific notation retains its notation");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects are as relevant as this snapshot?")), [], "lowercase grammar collisions remain excluded");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Which projects are in this snapshot?")), [], "two-character grammar noise remains excluded");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("Are there any awards?")), [], "a broad scaffold-only question remains aggregate-eligible");
  assert.equal(core.programOfficerAggregateIntent("What types of projects did they fund?"), "awards");
  assert.equal(core.programOfficerAggregateIntent("What kinds of projects did they fund?"), "awards");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What categories and themes of projects did they fund?")), []);
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("What types of quantum sensing projects did they fund?")), ["quantum sensing"]);
  assert.equal(core.programOfficerAggregateIntent("Which programs did this program officer manage?"), "programs");
  assert.deepEqual(plain(core.programOfficerRetrievalPhrases("How many awards are in this snapshot?")), []);
  const longConcepts = [
    "electrochemical", "interfacial", "photophysical", "spectroscopy", "nanostructured", "heterogeneous",
    "catalysis", "quantum", "sensing", "bioengineering", "microfluidics", "metamaterials",
    "thermochemical", "electrocatalytic", "operando", "plasmonic", "biomolecular", "microfabrication",
  ];
  const packedPhrases = plain(core.programOfficerRetrievalPhrases(`Which projects involve ${longConcepts.join(" ")}?`));
  assert.ok(packedPhrases.length <= 8);
  assert.ok(packedPhrases.every(phrase => phrase.length <= 120));
  assert.deepEqual(
    packedPhrases.flatMap(phrase => phrase.split(" ")).sort(),
    [...longConcepts].sort(),
    "bounded phrases retain every whole concept without mid-token truncation",
  );
  const overCapacityConcepts = Array.from({ length: 9 }, (_, index) => String.fromCharCode(97 + index).repeat(105));
  assert.equal(core.programOfficerRetrievalPhrases(`Which projects involve ${overCapacityConcepts.join(" ")}?`), null, "queries that exceed the published phrase capacity must be rejected instead of partially retrieved");
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
  const evidenceBody = body => ({ phrase_format: SNAPSHOT_EVIDENCE_PHRASE_FORMAT, ...body });
  const response = await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, phrases: ["catalysis"], limit: 24 })), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).retrieval.records_scanned, 30);
  assert.ok(buckets.includes("award:evidence"));
  const privatePhrase = "retrieval-private-marker";
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, phrases: [privatePhrase], limit: 24 })), env)).status, 200);
  const storedSnapshot = await [...cache.values.entries()].find(([url]) => url.includes("award-snapshot.internal"))[1].clone().text();
  assert.doesNotMatch(storedSnapshot, new RegExp(privatePhrase), "retrieval phrases must not be persisted into the snapshot cache");
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, phrases: [], limit: 24 })), env)).status, 400);
  assert.equal((await handler(request({ snapshot_id: snapshot.snapshot_id, phrases: ["catalysis"], limit: 24 }), env)).status, 400, "the phrase format is mandatory");
  assert.equal((await handler(request(evidenceBody({ snapshot_id: snapshot.snapshot_id, phrases: ["catalysis"], limit: 24 }), "https://evil.example"), env)).status, 403);

  const expired = programOfficerSnapshot([], { expiresAt: "2026-08-29T12:29:59.999Z" });
  expired.snapshot_id = "c".repeat(64);
  await storeSnapshot(cache, expired, 3600);
  assert.equal((await handler(request(evidenceBody({ snapshot_id: expired.snapshot_id, phrases: ["catalysis"], limit: 24 })), env)).status, 410);
  assert.equal(core.validateNarrativeAnswer({ claims: [{ text: "Unsupported", evidence_ids: ["NSF:NOT-IN-EVIDENCE"] }] }, [{ evidence_id: "NSF:KNOWN" }]), null);
});

test("served page exposes one coherent Program Officer cache identity and the browser uses full-snapshot evidence", () => {
  const key = "po-award-navigation-20260830-12";
  for (const asset of ["institutional-intelligence.css", "award-api-config.js", "institutional-intelligence-core.js", "institutional-intelligence-snapshots.js"]) {
    assert.match(pageSource, new RegExp(`${asset.replace(".", "\\.")}\\?v=${key}`));
  }
  assert.match(appSource, /Search this contact’s recent/);
  assert.match(pageSource, /id="ii-year-preset"/);
  assert.match(pageSource, /id="ii-institutions"/);
  assert.match(configSource, /snapshotEvidenceUrl/);
  assert.match(appSource, /programOfficerEvidence/);
  assert.match(appSource, /phrase_format: "normalized-concepts-v2"/);
  assert.match(appSource, /records_scanned/);
  assert.doesNotMatch(appSource.slice(appSource.indexOf("function programOfficerEvidence"), appSource.indexOf("function refreshProgramOfficerQuestionAnswer")), /residentAwards/);
  assert.match(deploySource, /program-officer-evidence-v2/);
  assert.match(deploySource, /normalized-concepts-v2/);
  assert.match(deploySource, /all_substantive_query_concepts_same_record/);
  assert.match(deploySource, /matched_facet_limit/);
  assert.match(deploySource, /indexed_abstract_characters_per_record/);
});
