import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { searchDoe } from "../../workers/award-api/src/adapters/doe.js";
import { buildNihRequest, searchNih } from "../../workers/award-api/src/adapters/nih.js";
import { searchNsf } from "../../workers/award-api/src/adapters/nsf.js";
import { nihFiscalYears, recordSatisfiesYearFilter, yearFilterDiagnostics } from "../../workers/award-api/src/year-filter.js";

const root = new URL("../../", import.meta.url);
const [coreSource, appSource, fundedSource, nsfFixture, nihFixture, doeForm, doePage1, doePage2, doeAbstract] = await Promise.all([
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence.js", root), "utf8"),
  readFile(new URL("assets/funded-awards.js", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/nsf_award.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/nih_project_years.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/doe_search_form.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page1.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page2.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_public_abstract.html", root), "utf8"),
]);

const sandbox = { URL, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(coreSource, sandbox);
const core = sandbox.FUNDING_INSTITUTIONAL_INTELLIGENCE;
const fixedNow = () => new Date("2026-08-26T12:00:00.000Z");

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function nsfRaw(id, year) {
  return {
    ...nsfFixture.response.award[0],
    id,
    date: year === null ? "" : `08/01/${year}`,
    title: `Award ${id}`,
  };
}

function nihRaw({ id, core, year, amount, start }) {
  return {
    ...nihFixture.results[0],
    appl_id: id,
    core_project_num: core,
    project_num: `${core}-01`,
    fiscal_year: year,
    award_amount: amount,
    project_start_date: start,
    project_detail_url: `https://reporter.nih.gov/project-details/${id}`,
  };
}

function award({ source, id, name, year = 2024, parent, leaf, code = null, email = null }) {
  return {
    source,
    award_id: id,
    award_year: year,
    title: `${source} ${id}`,
    subagency: parent,
    program_name: leaf,
    activity_code: source === "NIH" ? leaf : null,
    program_codes: code ? [code] : [],
    institution: {
      name: "University of Rochester",
      normalized_name: "University of Rochester",
      identifiers: { ror: "https://ror.org/022kthw22" },
    },
    principal_investigators: [{ name, email }],
  };
}

test("inclusive and one-sided year filters are bounded and explicit", () => {
  assert.deepEqual(nihFiscalYears({ year_start: 2024 }, 2026), [2024, 2025, 2026]);
  assert.deepEqual(nihFiscalYears({ year_end: 1991 }, 2026), [1989, 1990, 1991]);
  assert.deepEqual(buildNihRequest({ year_start: 2024 }, { limit: 25, offset: 0, currentYear: 2026 }).body.criteria.fiscal_years, [2024, 2025, 2026]);
  const diagnostics = yearFilterDiagnostics({ year_start: 2022, year_end: 2024 });
  assert.equal(recordSatisfiesYearFilter(2022, { year_start: 2022, year_end: 2024 }, diagnostics), true);
  assert.equal(recordSatisfiesYearFilter(2024, { year_start: 2022, year_end: 2024 }, diagnostics), true);
  assert.equal(recordSatisfiesYearFilter(2021, { year_start: 2022, year_end: 2024 }, diagnostics), false);
  assert.equal(recordSatisfiesYearFilter(null, { year_start: 2022, year_end: 2024 }, diagnostics), false);
  assert.equal(recordSatisfiesYearFilter(2025, { year_start: 2024 }), true);
  assert.equal(recordSatisfiesYearFilter(2023, { year_start: 2024 }), false);
  assert.equal(recordSatisfiesYearFilter(2020, { year_end: 2020 }), true);
  assert.equal(recordSatisfiesYearFilter(2021, { year_end: 2020 }), false);
  assert.deepEqual(diagnostics, {
    active: true,
    requested_start: 2022,
    requested_end: 2024,
    rejected_missing_year: 1,
    rejected_out_of_range: 1,
  });
});

test("NSF applies year validation before normalized offsets and reaches later valid awards", async () => {
  const raw = [
    ...Array.from({ length: 24 }, (_value, index) => nsfRaw(`OLD-${index}`, 2020)),
    nsfRaw("MISSING", null),
    nsfRaw("VALID-1", 2024),
    nsfRaw("VALID-2", 2024),
  ];
  const offsets = [];
  const fetchImpl = async url => {
    const parsed = new URL(url);
    const offset = Number(parsed.searchParams.get("offset"));
    const limit = Number(parsed.searchParams.get("rpp"));
    offsets.push(offset);
    return new Response(JSON.stringify({
      response: { award: raw.slice(offset, offset + limit), metadata: { totalCount: raw.length } },
    }), { headers: { "Content-Type": "application/json" } });
  };
  const result = await searchNsf(fetchImpl, { topic: "catalysis", year_start: 2024, year_end: 2024 }, { limit: 2, offset: 0, now: fixedNow });
  assert.deepEqual(result.results.map(item => item.award_id), ["VALID-1", "VALID-2"]);
  assert.deepEqual(offsets, [0, 25]);
  assert.equal(result.has_more, false);
  assert.equal(result.year_filter.rejected_out_of_range, 24);
  assert.equal(result.year_filter.rejected_missing_year, 1);
});

test("NIH qualifies projects by in-range annual support and excludes unrelated years and amounts", async () => {
  const raw = [
    ...Array.from({ length: 100 }, (_value, index) => nihRaw({
      id: 50_000_000 + index,
      core: `R01ZZ${String(index).padStart(6, "0")}`,
      year: 2020,
      amount: 1_000,
      start: "2020-01-01",
    })),
    nihRaw({ id: 60_000_001, core: "R01GM000001", year: 2023, amount: 100, start: "2024-01-01" }),
    nihRaw({ id: 60_000_002, core: "R01GM000001", year: 2024, amount: 200, start: "2024-01-01" }),
    nihRaw({ id: 60_000_003, core: "R01GM000002", year: null, amount: 900, start: "2024-02-01" }),
    nihRaw({ id: 60_000_004, core: "R01GM000003", year: 2024, amount: 300, start: "2024-03-01" }),
  ];
  const fetchImpl = async (_url, options) => {
    const body = JSON.parse(options.body);
    return new Response(JSON.stringify({
      meta: { total: raw.length, offset: body.offset },
      results: raw.slice(body.offset, body.offset + body.limit),
    }), { headers: { "Content-Type": "application/json" } });
  };
  const result = await searchNih(fetchImpl, { topic: "catalysis", year_start: 2024, year_end: 2024 }, { limit: 2, offset: 0, now: fixedNow });
  assert.equal(result.results.length, 2);
  const grouped = result.results.find(item => item.award_id === "R01GM000001");
  assert.deepEqual(grouped.annual_support.map(item => item.fiscal_year), [2024]);
  assert.equal(grouped.award_year, 2024);
  assert.equal(grouped.total_award, 200);
  assert.equal(grouped.award_amount_basis, "returned_support_years");
  assert.equal(result.year_filter.rejected_out_of_range, 101);
  assert.equal(result.year_filter.rejected_missing_year, 1);
});

test("DOE applies year validation before paging and reaches a later valid award", async () => {
  const oldFirst = doePage1.replace("07/15/2026", "07/15/2020");
  const validSecond = doePage2.replace("07/21/2026", "07/21/2024");
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push(String(url));
    if (String(url).includes("ViewPublicAbstract.aspx")) return new Response(doeAbstract);
    if (options.method === "POST") {
      return new Response(decodeURIComponent(String(options.body || "")).includes("grdAwardsList") ? validSecond : oldFirst);
    }
    return new Response(doeForm);
  };
  const result = await searchDoe(fetchImpl, { topic: "catalysis", year_start: 2024, year_end: 2024 }, { limit: 1, offset: 0, now: fixedNow, sleep: async () => {} });
  assert.deepEqual(result.results.map(item => item.award_id), ["DE-SC0024701"]);
  assert.equal(result.year_filter.rejected_out_of_range, 1);
  assert.equal(result.has_more, false);
  assert.equal(result.upstream_pages, 2);
  assert.equal(calls.length, 4);
});

test("mixed-source metrics use deduplicated awards, conservative people, leaf programs, and loaded years", () => {
  const awards = [
    award({ source: "NSF", id: "N-1", name: "Dr. Anne-Marie O’Neill Jr.", year: 2023, parent: "Chemistry", leaf: "Catalysis Science" }),
    award({ source: "DOE", id: "D-1", name: "Marc Porosoff", year: 2024, parent: "Office of Basic Energy Sciences", leaf: "Catalysis Science" }),
    award({ source: "DOE", id: "D-2", name: "Marc D Porosoff", year: 2024, parent: "Office of Basic Energy Sciences", leaf: "Catalysis Science" }),
    award({ source: "DOE", id: "D-3", name: "Zoe Alpha-Beta", year: 2025, parent: "Office of Basic Energy Sciences", leaf: "Chemical Physics" }),
    award({ source: "DOE", id: "D-4", name: "Alex Zeta", year: 2025, parent: "Office of Basic Energy Sciences", leaf: "Office of Basic Energy Sciences" }),
  ];
  const aggregate = core.aggregateAwards([...awards, awards[1]]);
  assert.equal(aggregate.project_count, 5);
  assert.equal(aggregate.investigator_count, 4);
  assert.equal(aggregate.program_count, 4);
  assert.deepEqual([aggregate.year_start, aggregate.year_end], [2023, 2025]);
  assert.deepEqual(plain(aggregate.investigators.map(item => item.name)), ["Zoe Alpha-Beta", "Anne-Marie O’Neill", "Marc D. Porosoff", "Alex Zeta"]);
  const marc = aggregate.investigators.find(item => item.name === "Marc D. Porosoff");
  assert.equal(marc.projects, 2);
  assert.deepEqual(new Set(marc.variants.map(item => item.name)), new Set(["Marc Porosoff", "Marc D Porosoff"]));
  const catalysis = aggregate.programs.find(item => item.source === "DOE" && item.leaf_label === "Catalysis Science");
  assert.equal(catalysis.projects, 2);
  assert.equal(catalysis.parent_label, "Office of Basic Energy Sciences");
  assert.equal(catalysis.label, "DOE · Office of Basic Energy Sciences › Catalysis Science");
  assert.equal(aggregate.programs.filter(item => item.source === "DOE" && item.parent_label === "Office of Basic Energy Sciences").length, 3);
  assert.ok(aggregate.programs.some(item => item.source === "NSF" && item.leaf_label === "Catalysis Science"));
});

test("dropdown rendering omits counts while submitted state controls paging and drill-downs", () => {
  const facetSource = appSource.slice(appSource.indexOf("function renderFacetSelect"), appSource.indexOf("function renderLoadMore"));
  assert.doesNotMatch(facetSource, /projects|currently loaded award|project count/i);
  assert.match(facetSource, /select\.value = selected\.identity_key/);
  assert.match(appSource, /state\.submittedState \|\| formState\(\)/);
  assert.match(appSource, /searchState \? \{ \.\.\.searchState \} : formState\(\)/);
  assert.match(fundedSource, /submittedState: state\.submittedState/);
  assert.match(fundedSource, /const submitted = state\.submittedState \|\| formState\(\)/);
});
