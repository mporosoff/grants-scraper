import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [
  querySource,
  retrievalSource,
  teamSource,
  matcherSource,
  matchConfigSource,
  teamPage,
  catalogSource,
  facultyMatchesSource,
] = await Promise.all([
  readFile(new URL("../../assets/search-query.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-retrieval.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-researchers.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-matcher.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-match-config.js", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../data/opportunities.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/faculty_matches.js", import.meta.url), "utf8"),
]);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

function loadApis() {
  const context = { globalThis: {} };
  vm.runInNewContext(querySource, context);
  vm.runInNewContext(retrievalSource, context);
  vm.runInNewContext(teamSource, context);
  vm.runInNewContext(matcherSource, context);
  vm.runInNewContext(matchConfigSource, context);
  return {
    query: context.globalThis.FUNDING_SEARCH_QUERY,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
    team: context.globalThis.FUNDING_TEAM_RESEARCHERS,
    matcher: context.globalThis.FUNDING_TEAM_MATCHER,
    matchConfig: context.globalThis.FUNDING_TEAM_MATCH_CONFIG,
  };
}

test("keeps manual and ORCID matching configuration eager and roster-independent", () => {
  const { matchConfig } = loadApis();
  assert.ok(Object.keys(matchConfig.theme_lexicon).length >= 15);
  assert.equal(matchConfig.bridge_themes.length, 11);
  assert.equal(matchConfig.agency_scope.length, 6);
  assert.match(matchConfig.broad_pattern, /broad agency announcement/);
  assert.equal("faculty" in matchConfig, false);
  assert.match(teamPage, /assets\/team-match-config\.js/);
  assert.match(teamPage, /MATCHER_API\.create\(catalogData, TEAM_MATCH_CONFIG, SEARCH_API, \{ now: TEAM_RUNTIME_NOW \}\)/);
  assert.match(teamPage, /MATCHER_API\.create\(CHILD_CATALOG, TEAM_MATCH_CONFIG, SEARCH_API, \{ now: TEAM_RUNTIME_NOW \}\)/);
});

function childTopicCatalog(query, children, excluded = []) {
  const index = buildIndex(children, query);
  return {
    schema_version: 1,
    records: {
      parent: {
        subtopics: [...children, ...excluded],
      },
    },
    search_index: {
      ...index,
      record_ids: children.map(child => child.subtopic_id),
    },
  };
}

function childTopicFixtures(apis, profiles) {
  const parent = {
    opportunity_id: "parent",
    title: "Umbrella research program",
    description: "Broad research areas without the specific child terminology.",
    status: "posted",
    close_date: "2027-01-15",
  };
  const eligible = {
    subtopic_id: "parent:eligible",
    parent_id: "parent",
    title: "Catalytic carbon conversion and catalyst screening",
    summary: "Heterogeneous catalysis, reaction kinetics, and machine learning catalyst screening for carbon conversion.",
    publication_state: "publishable",
    child_type: "subject",
    topic_areas: ["Catalysis and reaction engineering", "Artificial intelligence and machine learning"],
  };
  const unrelated = {
    subtopic_id: "parent:unrelated",
    parent_id: "parent",
    title: "Community arts engagement",
    summary: "Public art workshops and cultural events.",
    publication_state: "publishable",
    child_type: "subject",
    topic_areas: ["Arts and culture"],
  };
  const excluded = {
    subtopic_id: "parent:excluded",
    parent_id: "parent",
    title: "Catalytic carbon conversion internal draft",
    summary: eligible.summary,
    publication_state: "excluded",
    child_type: "subject",
  };
  const sidecar = childTopicCatalog(apis.query, [eligible, unrelated], [excluded]);
  const childCatalog = apis.retrieval.createChildCatalog(sidecar);
  const childEngine = apis.matcher.create(childCatalog, apis.matchConfig, apis.query, {
    now: new Date("2026-08-29T12:00:00Z"),
  });
  return {
    parent,
    outcome: childEngine.matchTeam(profiles),
  };
}

function rollupChildOnly(apis, parent, childResults) {
  return apis.matcher.rollupTeamMatches({
    parentResults: [],
    childResults,
    parentRecord: id => id === parent.opportunity_id ? parent : null,
    retrievalApi: apis.retrieval,
    now: new Date("2026-08-29T12:00:00Z"),
  });
}

test("all-Hajim teams retain publication-eligible child-only parent matches", () => {
  const apis = loadApis();
  const profiles = [
    {
      name: "Hajim Catalysis Researcher",
      key_terms: ["heterogeneous catalysis", "reaction kinetics"],
      domains: ["Catalysis and reaction engineering"],
    },
    {
      name: "Hajim Data Researcher",
      key_terms: ["machine learning catalyst screening", "carbon conversion"],
      domains: ["Artificial intelligence and machine learning"],
    },
  ];
  const { parent, outcome } = childTopicFixtures(apis, profiles);
  const rows = rollupChildOnly(apis, parent, outcome.results);

  assert.deepEqual(Array.from(rows, row => row.id), ["parent"]);
  assert.deepEqual(Array.from(rows[0].topicMatches, row => row.id), ["parent:eligible"]);
  assert.ok(rows[0].fits.every(fit => fit.evidenceSource === "child_topic"));
  assert.equal(rows[0].topicMatches.some(row => row.id === "parent:unrelated"), false);
  assert.equal(rows[0].topicMatches.some(row => row.id === "parent:excluded"), false);
});

test("mixed Hajim and custom teams retain child evidence and every-researcher gating", () => {
  const apis = loadApis();
  const mixedProfiles = [
    {
      name: "Hajim Catalysis Researcher",
      key_terms: ["heterogeneous catalysis", "reaction kinetics"],
      domains: ["Catalysis and reaction engineering"],
    },
    {
      name: "Manual Collaborator",
      keywords: ["machine learning catalyst screening", "carbon conversion"],
      key_terms: ["machine learning catalyst screening", "carbon conversion"],
      domains: ["Artificial intelligence and machine learning"],
    },
  ];
  const mixed = childTopicFixtures(apis, mixedProfiles);
  const rows = rollupChildOnly(apis, mixed.parent, mixed.outcome.results);
  assert.equal(rows.length, 1);
  assert.deepEqual(Array.from(rows[0].fits, fit => fit.name), ["Hajim Catalysis Researcher", "Manual Collaborator"]);

  const unrelatedResearcher = {
    name: "Unrelated Researcher",
    key_terms: ["medieval poetry", "community theater"],
    domains: ["Arts and culture"],
  };
  const gated = childTopicFixtures(apis, [mixedProfiles[0], unrelatedResearcher]);
  assert.equal(gated.outcome.results.length, 0);
  assert.equal(rollupChildOnly(apis, gated.parent, gated.outcome.results).length, 0);

  const graphIndex = new Map([["parent", { edge: true }]]);
  const customIndex = new Map();
  assert.equal(apis.matcher.intersectEvidenceIndexes([graphIndex, customIndex]).length, 0);
});

test("ordinary custom team results use the same rollup without expanding eligibility", () => {
  const apis = loadApis();
  const parent = {
    opportunity_id: "ordinary",
    title: "Ordinary custom-team opportunity",
    status: "posted",
    close_date: "2027-01-15",
  };
  const direct = {
    id: "ordinary",
    title: parent.title,
    relevanceScore: 7,
    rankScore: 7,
    recencyBoost: 1,
    fits: [{ name: "Custom A" }, { name: "Custom B" }],
    themeHits: [],
    record: parent,
  };
  const rows = apis.matcher.rollupTeamMatches({
    parentResults: [direct],
    childResults: [],
    parentRecord: () => parent,
    retrievalApi: apis.retrieval,
    now: new Date("2026-08-29T12:00:00Z"),
  });
  assert.deepEqual(Array.from(rows, row => row.id), ["ordinary"]);
  assert.deepEqual(Array.from(rows[0].fits, fit => fit.name), ["Custom A", "Custom B"]);
  assert.deepEqual(Array.from(rows[0].topicMatches), []);
});

test("graph membership cannot override the shared runtime catalog state", () => {
  const apis = loadApis();
  const expired = {
    opportunity_id: "expired-graph-member",
    title: "Expired graph member",
    status: "posted",
    close_date: "2026-08-28",
  };
  const graphResult = {
    id: expired.opportunity_id,
    relevanceScore: 10,
    fits: [{ name: "Hajim A" }, { name: "Hajim B" }],
    record: expired,
  };
  const rows = apis.matcher.rollupTeamMatches({
    parentResults: [graphResult],
    parentRecord: () => expired,
    retrievalApi: apis.retrieval,
    now: new Date("2026-08-29T12:00:00Z"),
    childEnabled: false,
  });
  assert.equal(rows.length, 0);
  assert.match(teamPage, /RETRIEVAL_API\.recordIsCurrent\(record, TEAM_RUNTIME_NOW\)/);
  assert.match(teamPage, /MATCHER_API\.rollupTeamMatches/);
  assert.match(teamPage, /CHILD_MATCH_ENGINE\.matchTeam\(profiles, profileActiveLabels\)/);
});

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, value); },
  };
}

function buildIndex(records, query) {
  const postings = {};
  const documentLengths = [];
  records.forEach((record, documentId) => {
    const text = [
      record.title,
      record.description,
      ...(record.topic_areas || []),
      ...(record.disciplines || []),
    ].join(" ");
    const counts = new Map();
    query.tokenize(text).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    documentLengths.push([...counts.values()].reduce((sum, value) => sum + value, 0));
    counts.forEach((frequency, term) => {
      (postings[term] ||= []).push(documentId, frequency);
    });
  });
  return {
    postings,
    document_count: records.length,
    document_lengths: documentLengths,
    average_document_length: documentLengths.reduce((sum, value) => sum + value, 0) / records.length,
  };
}

test("wires the researcher picker and editor into a syntactically valid page", () => {
  assert.match(teamPage, /id="add-researcher"/);
  assert.match(teamPage, /id="researcher-picker"/);
  assert.match(teamPage, /id="faculty-search"[^>]+role="combobox"/);
  assert.match(teamPage, /id="faculty-suggestions" role="listbox"/);
  assert.match(teamPage, /id="manual-researcher"/);
  assert.match(teamPage, /id="external-researcher-form"/);
  assert.match(teamPage, /id="external-orcid"/);
  assert.match(teamPage, /id="import-external-orcid"/);
  assert.match(teamPage, /assets\/orcid\.js/);
  assert.match(teamPage, /assets\/team-researchers\.js/);
  assert.match(teamPage, /assets\/team-matcher\.js/);
  assert.match(teamPage, /assets\/search-retrieval\.js/);
  assert.match(teamPage, /assets\/search-hybrid\.js/);
  assert.match(teamPage, /assets\/team-hybrid\.js/);
  assert.match(teamPage, /MATCHER_API\.create\(catalogData, TEAM_MATCH_CONFIG, SEARCH_API, \{ now: TEAM_RUNTIME_NOW \}\)/);
  assert.match(teamPage, /function rebuildResearcherMatches/);
  assert.match(teamPage, /function memberProfile/);
  assert.match(teamPage, /function opportunityCard/);
  assert.match(teamPage, /Research overlap across this team/);
  assert.match(teamPage, /Show full description &amp; details/);
  assert.match(teamPage, /Per-award amount/);
  assert.match(teamPage, /Eligible applicants/);
  assert.match(teamPage, /Open official FOA/);
  assert.match(teamPage, /Team Match is an informational research-planning aid/);
  assert.match(teamPage, /not an official source of record/);
  assert.match(teamPage, /independently verify fit, eligibility, deadlines, requirements, and terms/);
  assert.match(teamPage, /&copy; 2026 Marc D\. Porosoff/);
  assert.match(teamPage, /All rights reserved/);
  assert.match(teamPage, /Personal, non-commercial use is permitted/);
  assert.match(teamPage, /including modification, redistribution, and commercial or organizational use/);
  assert.match(teamPage, /requires written permission from the author/);
  assert.doesNotMatch(teamPage, /MIT License|href="\.\/LICENSE"/);
  assert.doesNotMatch(teamPage, /UR ChemE/i);
  const inlineScripts = [...teamPage.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map(match => match[1].trim())
    .filter(Boolean);
  assert.equal(inlineScripts.length, 1);
  assert.doesNotThrow(() => new Function(inlineScripts[0]));
});

test("starts with one Add researcher control instead of a faculty button wall", () => {
  const grid = teamPage.match(/<div class="pi-grid" id="pi-grid">([\s\S]*?)<\/div>/)?.[1] || "";
  assert.match(grid, />\s*Add a researcher\s*<\/button>/);
  assert.equal((grid.match(/class="pi-toggle/g) || []).length, 1);
  assert.doesNotMatch(teamPage, /names\.forEach\(function \(n\) \{[\s\S]*?grid\.insertBefore/);
  assert.match(teamPage, /Search Hajim faculty at the University of Rochester/);
  assert.match(teamPage, /Add a researcher manually/);
  assert.match(teamPage, /facultySearchResults = HAJIM_API\.search/);
  assert.match(teamPage, /limit: 12/);
  assert.match(teamPage, /selected\.indexOf\(key\) !== -1/);
});

test("opens an accessible bounded faculty combobox", () => {
  assert.match(teamPage, /picker\.hidden = !opening/);
  assert.match(teamPage, /aria-autocomplete="list"/);
  assert.match(teamPage, /aria-controls="faculty-suggestions"/);
  assert.match(teamPage, /aria-activedescendant/);
  assert.match(teamPage, /event\.key === "ArrowDown"/);
  assert.match(teamPage, /event\.key === "Enter"/);
  assert.match(teamPage, /event\.key === "Escape"/);
});

test("shows an accessible progress state while lazy-loading faculty matches", () => {
  assert.match(teamPage, /id="researcher-picker-status" role="status" aria-live="polite"/);
  assert.match(teamPage, /id="faculty-search-status" role="status" aria-live="polite"/);
  assert.match(teamPage, /Loading evidence-qualified matches for/);
  assert.match(teamPage, /function ensureFacultyGraph\(\)/);
  assert.match(teamPage, /ensureFacultyGraph\(\)\.then/);
  assert.match(teamPage, /Directory search and manual entry are still available; try again/);
  assert.match(teamPage, /var facultyChoicePending = false/);
  assert.match(teamPage, /facultyChoicePending \|\| !faculty\[facultyId\]/);
  assert.match(teamPage, /closeFacultySuggestions\(false\)/);
  assert.match(teamPage, /if \(selected\.indexOf\(facultyId\) !== -1 \|\| selected\.length >= MAX\)/);
});

test("preserves native scroll restoration and omits the catalog-count hero line", () => {
  assert.doesNotMatch(teamPage, /history\.scrollRestoration = "manual"/);
  assert.doesNotMatch(teamPage, /window\.addEventListener\("pageshow"/);
  assert.doesNotMatch(teamPage, /window\.scrollTo\(0, 0\)/);
  assert.match(teamPage, /TEAM_HISTORY_STATE_KEY = "fundingFinderTeamMatch"/);
  assert.match(teamPage, /window\.addEventListener\("pagehide", saveTeamHistory\)/);
  assert.match(teamPage, /restoreTeamHistory\(\)/);
  assert.match(teamPage, /finishHistoryRestore\(\)/);
  assert.doesNotMatch(teamPage, /id="meta-line"/);
  assert.doesNotMatch(teamPage, /department faculty profiles|live graded matching across/);
});

test("supports repeated selection, removal, editing, and the four-person maximum", () => {
  assert.match(teamPage, /function chooseFaculty\(facultyId\)/);
  assert.match(teamPage, /selected\.indexOf\(facultyId\) !== -1/);
  assert.match(teamPage, /toggleButton\.setAttribute\("aria-label", "Remove "/);
  assert.match(teamPage, /if \(profile\) \{[\s\S]*?openExternalEditor\(profile\.id\)/);
  assert.match(teamPage, /addButton\.disabled = selected\.length >= MAX/);
  assert.match(teamPage, /Team limit reached: remove a researcher/);
  assert.match(teamPage, /selected = selected\.filter\(function \(member\) \{ return member !== key; \}\)/);
  assert.match(teamPage, /autoSelected = !wasEditing && selected\.length < MAX/);
  assert.match(teamPage, /TEAM_API\.save\(externalStorage, nextProfiles\)/);
  assert.match(teamPage, /ORCID_API\.fetchProfile/);
});

test("uses neutral visitor-facing researcher terminology", () => {
  const visibleText = teamPage
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
  assert.doesNotMatch(visibleText, /\b(?:internal|external)\b/i);
  assert.doesNotMatch(teamPage, /\(internal\)/i);
  assert.match(visibleText, /Researchers you add are saved only in this browser/);
});

test("normalizes and saves no more than four external researchers", () => {
  const { team } = loadApis();
  const storage = memoryStorage();
  const profiles = ["Ada", "Grace", "Katherine", "George", "Evelyn"].map((name, index) => ({
    id: `ext-person-${index}`,
    name,
    keywords: "carbon capture; catalysis; membranes; energy storage; hydrogen; hydrogen",
  }));

  const saved = team.save(storage, profiles);
  const loaded = team.load(storage);

  assert.equal(saved.saved, true);
  assert.equal(loaded.profiles.length, 4);
  assert.deepEqual(
    [...loaded.profiles[0].keywords],
    ["carbon capture", "catalysis", "membranes", "energy storage", "hydrogen"],
  );
  const withOrcid = team.save(storage, [{
    id: "ext-ada",
    name: "Ada",
    keywords: ["carbon capture", "catalysis", "membranes"],
    orcid_id: "0000-0002-1825-0097",
    orcid_name: "Ada Researcher",
    orcid_text: "Ionic liquid separation publications",
    orcid_work_count: 7,
  }]);
  assert.equal(withOrcid.profiles[0].orcid_id, "0000-0002-1825-0097");
  assert.match(withOrcid.profiles[0].orcid_text, /Ionic liquid/);
});

test("drops standalone umbrella keywords from external profiles", () => {
  const { team } = loadApis();
  assert.deepEqual(
    [...team.parseKeywords("materials science; energy; battery interfaces; carbon conversion; catalysis")],
    ["battery interfaces", "carbon conversion", "catalysis"],
  );
});

test("requires every selected researcher to match a shared opportunity", () => {
  const { team } = loadApis();
  const match = id => ({
    id,
    title: `Opportunity ${id}`,
    score: 5,
    rank_score: 6,
    terms: [`concept ${id}`],
  });
  const researchers = [
    { key: "a", name: "Researcher A", matches: [match("shared"), match("partial")] },
    { key: "b", name: "Researcher B", matches: [match("shared"), match("partial")] },
    { key: "c", name: "Researcher C", matches: [match("shared")] },
    { key: "d", name: "Researcher D", matches: [match("different")] },
  ];

  const twoPerson = team.intersectMemberMatches(researchers.slice(0, 2));
  const threePerson = team.intersectMemberMatches(researchers.slice(0, 3));
  const fourPerson = team.intersectMemberMatches(researchers);

  assert.deepEqual(Array.from(twoPerson, item => item.d.id), ["shared", "partial"]);
  assert.deepEqual(Array.from(threePerson, item => item.d.id), ["shared"]);
  assert.deepEqual(Array.from(fourPerson, item => item.d.id), []);
  assert.ok(threePerson.length <= twoPerson.length);
  assert.ok(fourPerson.length <= threePerson.length);
  assert.equal(threePerson[0].totalN, 3);
});

test("graded team scoring combines evidence, supports scope-only BAAs, and rejects generic noise", () => {
  const { query, matcher } = loadApis();
  const catalog = {
    opportunities: [
      {
        opportunity_id: "graded",
        title: "Data-driven reaction discovery",
        description: "Catalytic conversion, reaction kinetics, and machine learning catalyst screening.",
        topic_areas: ["Catalysis and reaction engineering", "Artificial intelligence and machine learning"],
        posted_date: "2026-08-08",
        close_date: "2026-08-20",
      },
      {
        opportunity_id: "generic",
        title: "General materials program",
        description: "A broad program for technology development.",
        topic_areas: ["Materials science", "Technology development"],
        posted_date: "2026-08-09",
        close_date: "2026-10-01",
      },
      {
        opportunity_id: "onr",
        title: "Long Range Broad Agency Announcement",
        description: "Meritorious research across a spectrum of science and engineering.",
        agency: "Office of Naval Research",
        topic_areas: [],
        posted_date: "2025-01-01",
        close_date: "2026-10-01",
      },
    ],
  };
  const config = {
    theme_lexicon: {
      "Catalysis and reaction engineering": ["catalytic", "reaction kinetics", "catalyst"],
      "Artificial intelligence and machine learning": ["machine learning", "catalyst screening"],
      "Materials science": ["advanced materials", "polymer", "nanomaterial"],
      Energy: ["energy conversion", "energy storage"],
    },
    bridge_themes: [{
      label: "Data-driven catalyst discovery",
      domains: ["Artificial intelligence and machine learning", "Catalysis and reaction engineering"],
      terms: ["catalyst screening", "machine learning"],
    }],
    agency_scope: [{
      label: "Office of Naval Research",
      pattern: "office of naval research",
      domains: ["Materials science", "Energy"],
    }],
    broad_pattern: "broad agency announcement|long[\\s-]?range",
  };
  const gradedTeam = [
    {
      name: "Catalysis PI",
      key_terms: ["heterogeneous catalysis", "reaction kinetics"],
      domains: ["Catalysis and reaction engineering", "Materials science"],
    },
    {
      name: "Data PI",
      key_terms: ["machine learning catalyst discovery", "catalyst screening"],
      domains: ["Artificial intelligence and machine learning", "Energy"],
    },
  ];
  const engine = matcher.create(catalog, config, query, { now: new Date("2026-08-11T00:00:00Z") });
  const result = engine.matchTeam(gradedTeam);
  const ids = Array.from(result.results, item => item.id);

  assert.ok(ids.includes("graded"));
  assert.ok(ids.includes("onr"));
  assert.equal(ids.includes("generic"), false);
  assert.equal(result.results.find(item => item.id === "graded").closingSoon, true);
  const onr = result.results.find(item => item.id === "onr");
  assert.equal(onr.broad, true);
  assert.ok(onr.fits.every(fit => fit.scopeLabel === "Office of Naval Research"));
  assert.ok(onr.fits.every(fit => fit.researchReasons.length === 0));
  assert.ok(onr.fits.every(fit => fit.reasons.includes("Office of Naval Research")));
  assert.ok(result.themes.some(theme => theme.label === "Data-driven catalyst discovery"));
  assert.ok(result.results.every(item => item.fits.length === gradedTeam.length));
});

test("team matching never includes archived or otherwise expired catalog records", () => {
  const { query, matcher } = loadApis();
  const base = {
    title: "Catalytic carbon conversion",
    description: "Heterogeneous catalysis and carbon dioxide conversion.",
    topic_areas: ["Catalysis and reaction engineering"],
    close_date: "2026-12-31",
  };
  const catalog = { opportunities: [
    { ...base, opportunity_id: "current", status: "posted" },
    { ...base, opportunity_id: "archived", status: "archived" },
    { ...base, opportunity_id: "archive-date", status: "posted", archive_date: "2026-08-10" },
    { ...base, opportunity_id: "cancelled", status: "cancelled" },
  ] };
  const profile = {
    name: "Catalysis PI",
    key_terms: ["heterogeneous catalysis", "carbon dioxide conversion"],
    domains: ["Catalysis and reaction engineering"],
  };
  const engine = matcher.create(catalog, {}, query, { now: new Date("2026-08-13T00:00:00Z") });
  const ids = engine.matchProfile(profile).map(result => result.id);

  assert.deepEqual(Array.from(ids), ["current"]);
  assert.equal(engine.records.length, 1);
});

test("team matching resolves a researcher acronym from local profile context", () => {
  const { query, matcher } = loadApis();
  const catalog = { opportunities: [
    {
      opportunity_id: "cfd",
      status: "posted",
      title: "Hypersonic flow simulation",
      description: "Computational fluid dynamics using advanced numerical methods.",
      topic_areas: ["Space and aeronautics"],
      close_date: "2026-12-31",
    },
    {
      opportunity_id: "fluid-only",
      status: "posted",
      title: "Experimental fluid measurements",
      description: "Fluid mechanics instrumentation and imaging.",
      close_date: "2026-12-31",
    },
  ] };
  const engine = matcher.create(catalog, {}, query, {
    now: new Date("2026-08-13T00:00:00Z"),
  });
  const matches = engine.matchProfile({
    name: "Contextual Researcher",
    key_terms: ["CFD"],
    research_summary: "Uses computational fluid dynamics to study transport phenomena.",
    domains: ["Space and aeronautics"],
  });

  assert.deepEqual(Array.from(matches, item => item.id), ["cfd"]);
  assert.deepEqual(
    Array.from(matches[0].fits[0].researchReasons),
    ["CFD", "Space and aeronautics"],
  );
});

test("builds opportunity matches from an external researcher's keywords", () => {
  const { query, retrieval, team } = loadApis();
  const records = [
    {
      opportunity_id: "carbon",
      title: "Carbon dioxide capture and conversion",
      description: "Catalytic carbon capture and membrane separations.",
      topic_areas: ["Carbon management", "Catalysis and reaction engineering"],
      disciplines: ["Engineering"],
      close_date: "2027-01-15",
      detail_page: "https://example.test/carbon",
    },
    {
      opportunity_id: "arts",
      title: "Community arts program",
      description: "Public art and cultural engagement.",
      topic_areas: ["Arts"],
      disciplines: ["Humanities"],
    },
  ];
  const catalog = { opportunities: records, search_index: buildIndex(records, query) };
  const engine = retrieval.create(catalog, query);
  const profile = {
    name: "External Researcher",
    keywords: ["CO2 capture", "heterogeneous catalysis", "membrane separations"],
  };

  const matches = team.buildMatches(
    profile,
    catalog,
    query,
    ["Carbon management", "Catalysis and reaction engineering"],
    engine,
  );

  assert.equal(matches.length, 1);
  assert.equal(matches[0].id, "carbon");
  assert.equal(matches[0].tier, "focused");
  assert.ok(matches[0].terms.includes("CO2 capture"));

  const partnerMatches = team.buildMatches(
    {
      name: "Second External Researcher",
      keywords: ["carbon dioxide", "CO2 conversion", "membrane separations"],
    },
    catalog,
    query,
    ["Carbon management", "Catalysis and reaction engineering"],
    engine,
  );
  const sharedIds = new Set(matches.map(match => match.id));
  assert.ok(partnerMatches.some(match => sharedIds.has(match.id)));
});

test("requires focused evidence and balances relevance with listing date", () => {
  const { query, team } = loadApis();
  const records = [
    {
      opportunity_id: "older-strong",
      title: "Integrated carbon catalyst initiative",
      description: "Heterogeneous catalysis for carbon dioxide conversion.",
      topic_areas: ["Catalysis and reaction engineering", "Carbon management"],
      disciplines: ["Engineering"],
      posted_date: "2026-02-01",
    },
    {
      opportunity_id: "newer-focused",
      title: "New catalyst initiative",
      description: "Heterogeneous catalysis research.",
      topic_areas: ["Catalysis and reaction engineering"],
      disciplines: ["Engineering"],
      source_first_seen_date: "2026-08-09",
    },
    {
      opportunity_id: "newer-broad",
      title: "Egypt Annual Program Statement",
      description: "Commercial diplomacy, energy exports, manufacturing, and critical minerals.",
      topic_areas: ["Energy", "Materials science", "Manufacturing"],
      disciplines: ["Engineering"],
      source_first_seen_date: "2026-08-10",
    },
  ];
  const catalog = { opportunities: records, search_index: buildIndex(records, query) };
  const matches = team.buildMatches(
    {
      name: "Balanced Researcher",
      keywords: ["heterogeneous catalysis", "carbon dioxide conversion"],
      domains: ["Energy", "Materials science", "Catalysis and reaction engineering"],
    },
    catalog,
    query,
    ["Catalysis and reaction engineering"],
    null,
  );

  assert.deepEqual(Array.from(matches, match => match.id), ["older-strong", "newer-focused"]);
  assert.equal(matches[0].terms.length, 2);
  assert.equal(matches[1].terms.length, 1);
  assert.ok(matches[0].rank_score > matches[1].rank_score);
});

test("the live Egypt diplomacy notice is not a faculty research match", () => {
  const catalog = assignmentJson(catalogSource);
  const generated = assignmentJson(facultyMatchesSource);
  const egypt = catalog.opportunities.find(record => record.title === "Egypt Annual Program Statement");
  if (!egypt) return;
  const id = String(egypt.opportunity_id || egypt.opportunity_number);
  const edges = (generated.by_opportunity[id] || []).map(index => generated.edges[index]);
  assert.equal(edges.some(edge => ["marc-d-porosoff", "siddharth-deshpande"].includes(edge.faculty_id)), false);
});

test("presents one interactive full-team list with graded themes and broad-call flags", () => {
  assert.match(teamPage, /Opportunities matching the full selected team/);
  assert.match(teamPage, /fit every selected researcher/);
  assert.match(teamPage, /Adding a researcher can only narrow these results/);
  assert.match(teamPage, /Team themes · click to steer the search/);
  assert.match(teamPage, /function teamChips\(fits, themeLabels\)/);
  assert.match(teamPage, /teamChips\(entry\.fits, d\.themeLabels\)/);
  assert.match(teamPage, /Blue = shared research areas/);
  assert.match(teamPage, /Purple = complementary bridge themes/);
  assert.match(teamPage, /Broad \/ umbrella call/);
  assert.match(teamPage, /Broad sponsor-scope signal:/);
  assert.match(teamPage, /Broad sponsor-scope match/);
  assert.doesNotMatch(teamPage, /" of " \+ selected\.length/);
  assert.match(teamPage, /new or substantively updated in the last 14 days/);
  assert.match(teamPage, /Opportunities matching the full selected team · ordered by relevance and recency/);
  assert.doesNotMatch(teamPage, /new or substantively updated in the last 14 days · ordered/);
  assert.match(teamPage, /\.count\{[^}]*font-weight:750/);
  assert.match(teamPage, /\.count:empty\{display:none;\}/);
  assert.match(teamPage, /&amp;focus=/);
  assert.match(teamPage, /target="_blank" rel="noopener">Open in Funding Finder/);
  assert.doesNotMatch(teamPage, /Internal tool/);
  assert.doesNotMatch(teamPage, /dept-toggle|Department-wide overview|function renderDept/);
  assert.match(teamPage, /Closing soon/);
  assert.match(teamPage, /MATCH_ENGINE\.matchTeam/);
  assert.doesNotMatch(teamPage, /fit 2\+ of \{/);
  assert.doesNotMatch(teamPage, /departmentGroups\s*=\s*buildShared\(names\)/);
  assert.match(teamPage, /research_summary/);
  assert.match(teamPage, /Listed /);
  assert.doesNotMatch(teamPage, />specific<\/span>/);
});

test("production graph keeps every-member intersections monotonic and bounded", () => {
  const generated = assignmentJson(facultyMatchesSource);
  const faculty = Object.entries(generated.by_faculty)
    .filter(([, indexes]) => indexes.length >= 3)
    .slice(0, 4)
    .map(([id]) => id);
  assert.ok(faculty.length >= 2);
  const opportunitySet = id => new Set(generated.by_faculty[id].map(index => generated.edges[index].opportunity_id));
  const intersections = faculty.map(opportunitySet).reduce((rows, current, index) => {
    if (index === 0) return [current];
    const next = new Set([...rows[index - 1]].filter(id => current.has(id)));
    rows.push(next);
    return rows;
  }, []);
  for (let index = 1; index < intersections.length; index += 1) {
    assert.ok(intersections[index].size <= intersections[index - 1].size);
  }
  assert.ok(Object.values(generated.by_opportunity).every(indexes => indexes.length <= 12));
  assert.ok(Object.values(generated.by_faculty).every(indexes => indexes.length <= 25));
  assert.equal(new Set(generated.edges.map(edge => `${edge.faculty_id}:${edge.opportunity_id}`)).size, generated.edges.length);
});

test("uses the same PFAS and fuzzy retrieval for faculty and external profiles", () => {
  const { query, retrieval, team } = loadApis();
  const records = [
    {
      opportunity_id: "water",
      title: "Persistent contaminant remediation in drinking water",
      description: "Groundwater pollution treatment and water purification research.",
      topic_areas: ["Environmental science", "Water"],
      disciplines: ["Engineering"],
    },
    {
      opportunity_id: "membrane",
      title: "Advanced membrane separation systems",
      description: "Novel filtration and selective separations.",
      topic_areas: ["Separations and membranes"],
      disciplines: ["Engineering"],
    },
    {
      opportunity_id: "arts",
      title: "Community arts program",
      description: "Public art and cultural engagement.",
      topic_areas: ["Arts and culture"],
      disciplines: ["Humanities"],
    },
  ];
  const catalog = { opportunities: records, search_index: buildIndex(records, query) };
  const engine = retrieval.create(catalog, query);
  const niche = ["Environmental science", "Water", "Separations and membranes"];

  const faculty = team.buildMatches(
    { name: "Faculty PI", keywords: ["PFAS"], domains: ["Environmental science", "Water"] },
    catalog,
    query,
    niche,
    engine,
  );
  const external = team.buildMatches(
    { name: "External collaborator", keywords: ["PFAS"] },
    catalog,
    query,
    niche,
    engine,
  );
  const typo = team.buildMatches(
    { name: "Typo profile", keywords: ["membrnae separation"] },
    catalog,
    query,
    niche,
    engine,
  );

  assert.ok(faculty.some(match => match.id === "water"));
  assert.ok(external.some(match => match.id === "water"));
  assert.ok(typo.some(match => match.id === "membrane"));
  assert.equal(faculty.some(match => match.id === "arts"), false);
  assert.equal(external.some(match => match.id === "arts"), false);
});

test("reports storage failures without losing the in-tab profiles", () => {
  const { team } = loadApis();
  const storage = { setItem() { throw new Error("blocked"); } };
  const profiles = [{ id: "ext-ada", name: "Ada", keywords: ["carbon", "catalysis", "membranes"] }];

  const result = team.save(storage, profiles);

  assert.equal(result.saved, false);
  assert.equal(result.profiles.length, 1);
  assert.match(result.error, /available in this tab/);
});
