import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [
  querySource,
  retrievalSource,
  teamSource,
  matcherSource,
  teamPage,
  catalogSource,
  facultyMatchesSource,
] = await Promise.all([
  readFile(new URL("../../assets/search-query.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-retrieval.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-researchers.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-matcher.js", import.meta.url), "utf8"),
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
  return {
    query: context.globalThis.FUNDING_SEARCH_QUERY,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
    team: context.globalThis.FUNDING_TEAM_RESEARCHERS,
    matcher: context.globalThis.FUNDING_TEAM_MATCHER,
  };
}

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
  assert.match(teamPage, /id="researcher-choice"/);
  assert.match(teamPage, /id="choose-researcher"/);
  assert.match(teamPage, /id="external-researcher-form"/);
  assert.match(teamPage, /id="external-orcid"/);
  assert.match(teamPage, /id="import-external-orcid"/);
  assert.match(teamPage, /assets\/orcid\.js/);
  assert.match(teamPage, /assets\/team-researchers\.js/);
  assert.match(teamPage, /assets\/team-matcher\.js/);
  assert.match(teamPage, /assets\/search-retrieval\.js/);
  assert.match(teamPage, /assets\/search-hybrid\.js/);
  assert.match(teamPage, /assets\/team-hybrid\.js/);
  assert.match(teamPage, /MATCHER_API\.create\(catalogData, M \|\| \{\}, SEARCH_API\)/);
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

test("starts with one Add researcher control and separates directory from manual entry", () => {
  const grid = teamPage.match(/<div class="pi-grid" id="pi-grid">([\s\S]*?)<\/div>/)?.[1] || "";
  assert.match(grid, />\s*Add researcher\s*<\/button>/);
  assert.equal((grid.match(/class="pi-toggle/g) || []).length, 1);
  assert.doesNotMatch(teamPage, /names\.forEach\(function \(n\) \{[\s\S]*?grid\.insertBefore/);
  assert.match(teamPage, /Search Hajim faculty at the University of Rochester/);
  assert.match(teamPage, /id="faculty-search"[^>]+role="combobox"/);
  assert.match(teamPage, /id="manual-researcher"/);
  assert.match(teamPage, /Add a researcher manually/);
  assert.doesNotMatch(teamPage, /facultyGroup\.label = "Department faculty"/);
  assert.match(teamPage, /selected\.indexOf\(key\) === -1/);
});

test("opens an accessible bounded faculty combobox", () => {
  assert.match(teamPage, /picker\.hidden = !opening/);
  assert.doesNotMatch(teamPage, /\$\("researcher-choice"\)\.focus\(\)/);
  assert.match(teamPage, /aria-autocomplete="list"/);
  assert.match(teamPage, /aria-controls="faculty-suggestions"/);
  assert.match(teamPage, /aria-activedescendant/);
  assert.match(teamPage, /event\.key === "ArrowDown"/);
  assert.match(teamPage, /event\.key === "Enter"/);
  assert.match(teamPage, /event\.key === "Escape"/);
});

test("the prominent manual path opens the researcher editor directly", () => {
  assert.match(teamPage, /\$\("manual-researcher"\)\.addEventListener\("click", function \(\) \{[\s\S]*?openExternalEditor\(""\)/);
  assert.match(teamPage, /\$\("choose-researcher"\)\.addEventListener\("click", chooseResearcher\)/);
});

test("shows an accessible progress state while adding a researcher", () => {
  assert.match(teamPage, /id="researcher-picker-status" role="status" aria-live="polite"/);
  assert.match(teamPage, /function setResearcherAddBusy\(busy, member\)/);
  assert.match(teamPage, /button\.textContent = busy \? "Adding…" : "Add to team"/);
  assert.match(teamPage, /button\.setAttribute\("aria-busy", "true"\)/);
  assert.match(teamPage, /"Adding " \+ memberName\(member\) \+ " to the team…"/);
  assert.match(teamPage, /setResearcherAddBusy\(true, member\);[\s\S]*?setTimeout\(function \(\) \{[\s\S]*?toggle\(member\)/);
  assert.match(teamPage, /setResearcherAddBusy\(false, member\)/);
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
  assert.match(teamPage, /function chooseResearcher\(\)/);
  assert.match(teamPage, /if \(selected\.indexOf\(member\) !== -1\)/);
  assert.match(teamPage, /toggleButton\.setAttribute\("aria-label", "Remove "/);
  assert.match(teamPage, /if \(profile\) \{[\s\S]*?openExternalEditor\(profile\.id\)/);
  assert.match(teamPage, /addButton\.hidden = selected\.length >= MAX/);
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
  const { query, retrieval, team } = loadApis();
  const catalog = assignmentJson(catalogSource);
  const generated = assignmentJson(facultyMatchesSource);
  const engine = retrieval.create(catalog, query);

  for (const name of ["Marc D. Porosoff", "Siddharth Deshpande"]) {
    const metadata = generated.faculty[name];
    const matches = team.buildMatches(
      { name, keywords: metadata.key_terms, domains: metadata.domains },
      catalog,
      query,
      generated.niche_topics,
      engine,
    );
    assert.equal(matches.some(match => match.title === "Egypt Annual Program Statement"), false);
  }
  assert.equal(
    generated.multi_pi_suggestions.some(group => group.title === "Egypt Annual Program Statement"),
    false,
  );
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

test("production acceptance suite keeps broad and focused calls while excluding noise", () => {
  const { query, matcher } = loadApis();
  const catalog = assignmentJson(catalogSource);
  const generated = assignmentJson(facultyMatchesSource);
  const engine = matcher.create(catalog, generated, query, { now: new Date("2026-08-11T00:00:00Z") });
  const names = ["Marc D. Porosoff", "Astrid M. Muller", "Siddharth Deshpande", "Yasemin Basdogan"];
  const profiles = names.map(name => ({ name, ...generated.faculty[name] }));
  const two = engine.matchTeam(profiles.slice(0, 2)).results;
  const three = engine.matchTeam(profiles.slice(0, 3)).results;
  const four = engine.matchTeam(profiles).results;
  const ids = new Set(four.map(item => item.id));

  const expectedBroadPatterns = [
    /Office of Science Financial Assistance Program/i,
    /Long Range Broad Agency Announcement.*Navy and Marine Corps/i,
  ];
  for (const pattern of expectedBroadPatterns) {
    const current = engine.records.find(item => pattern.test(item.record.title || ""));
    if (current) {
      assert.ok(ids.has(current.id), `expected current broad call to match: ${current.record.title}`);
    }
  }
  assert.ok(four.length >= 1, "the production team intersection should not be empty");
  assert.ok(four.some(item => item.broad), "the production team should retain a broad sponsor call");
  assert.equal(
    four.some(item => /public diplomacy|embassy|consulate/i.test(`${item.agency} ${item.title}`)),
    false,
    "public-diplomacy calls must be excluded",
  );
  assert.equal(
    four.some(item => /mine safety|Brookwood-Sago/i.test(`${item.agency} ${item.title}`)),
    false,
    "mine-safety calls must be excluded",
  );
  assert.equal(
    four.some(item => /^ROSES\s*(?:20)?\d{2}:\s*[A-Z]\.\d+/i.test(item.title)),
    false,
    "specific NASA program elements must not inherit the agency-wide scope signal",
  );
  assert.ok(four.every(item => item.fits.length === profiles.length));
  assert.ok(three.length <= two.length);
  assert.ok(four.length <= three.length);

  const onr = four.find(item => /Navy and Marine Corps Science and Technology/i.test(item.title));
  if (onr) assert.equal(onr.broad, true);

  Object.values(generated.faculty).forEach(metadata => {
    const count = engine.matchProfile({ name: metadata.resolved_name, ...metadata }).length;
    assert.ok(count >= 1 && count <= 500, `per-PI match count ${count} should remain bounded`);
  });
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
