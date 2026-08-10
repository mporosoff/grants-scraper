import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [
  querySource,
  retrievalSource,
  teamSource,
  teamPage,
  catalogSource,
  facultyMatchesSource,
] = await Promise.all([
  readFile(new URL("../../assets/search-query.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-retrieval.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/team-researchers.js", import.meta.url), "utf8"),
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
  return {
    query: context.globalThis.FUNDING_SEARCH_QUERY,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
    team: context.globalThis.FUNDING_TEAM_RESEARCHERS,
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

test("wires the external researcher editor into a syntactically valid page", () => {
  assert.match(teamPage, /id="add-researcher"/);
  assert.match(teamPage, /id="external-researcher-form"/);
  assert.match(teamPage, /assets\/team-researchers\.js/);
  assert.match(teamPage, /assets\/search-retrieval\.js/);
  assert.match(teamPage, /RETRIEVAL_API\.create\(catalogData, SEARCH_API\)/);
  assert.match(teamPage, /function rebuildResearcherMatches/);
  assert.match(teamPage, /keywords: metadata\.key_terms/);
  const inlineScripts = [...teamPage.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map(match => match[1].trim())
    .filter(Boolean);
  assert.equal(inlineScripts.length, 1);
  assert.doesNotThrow(() => new Function(inlineScripts[0]));
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

test("presents only full-team relevance-and-recency matches without broad-specific labels", () => {
  assert.match(teamPage, /Opportunities matching the full selected team/);
  assert.match(teamPage, /fit every selected researcher/);
  assert.match(teamPage, /Adding a researcher can only narrow these results/);
  assert.match(teamPage, /TEAM_API\.intersectMemberMatches/);
  assert.doesNotMatch(teamPage, /fit 2\+ of \{/);
  assert.doesNotMatch(teamPage, /departmentGroups\s*=\s*buildShared\(names\)/);
  assert.match(teamPage, /balanced by research fit and listing date/);
  assert.match(teamPage, /research_summary/);
  assert.match(teamPage, /Listed /);
  assert.doesNotMatch(teamPage, /broad · verify fit/);
  assert.doesNotMatch(teamPage, />specific<\/span>/);
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
