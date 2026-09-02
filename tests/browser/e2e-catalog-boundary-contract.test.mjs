import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [
  deterministicFundingSource,
  liveFundingSource,
  accessibilitySource,
  helpersSource,
  querySource,
  fixtureSource,
] = await Promise.all([
  readFile(new URL("tests/e2e/funding-finder.spec.mjs", root), "utf8"),
  readFile(new URL("tests/e2e/funding-finder-live.spec.mjs", root), "utf8"),
  readFile(new URL("tests/e2e/accessibility.spec.mjs", root), "utf8"),
  readFile(new URL("tests/e2e/helpers.mjs", root), "utf8"),
  readFile(new URL("assets/search-query.js", root), "utf8"),
  readFile(new URL("tests/fixtures/frozen/funding-catalog.js", root), "utf8"),
]);

test("deterministic Funding Finder E2E cannot borrow the daily catalog", () => {
  assert.match(
    deterministicFundingSource,
    /test\.beforeEach\([\s\S]*mockFrozenFundingSearchPackage\(page\)/,
  );
  const accessibilityFundingTests = accessibilitySource
    .split(/\ntest\(/)
    .slice(1)
    .filter(source => /\/match_explorer\.html|openFundingFinder\(/.test(source));
  assert.ok(accessibilityFundingTests.length > 0);
  accessibilityFundingTests.forEach(source => assert.match(
    source,
    /mockFrozenFundingSearchPackage\(/,
  ));
  assert.doesNotMatch(
    `${deterministicFundingSource}\n${accessibilitySource}`,
    /data\/opportunities\.js|liveCatalog|liveCurrentNumberedOpportunity|26-506|362900|334326|DE-FOA-0003600/,
  );
  assert.match(helpersSource, /data\/search-v2-voyage-manifest\.json/);
  assert.match(helpersSource, /data\/search-v2-voyage-vectors\.f16/);
  assert.match(helpersSource, /data\/subtopics\.js/);
});

test("the daily-catalog E2E is a behavior-only health smoke", () => {
  assert.match(liveFundingSource, /browse-all/);
  assert.match(liveFundingSource, /result-card/);
  assert.doesNotMatch(
    liveFundingSource,
    /opportunity_(?:id|number)|data-opportunity-id|[?&]focus=|\b\d{6}\b|\b(?:PAR|RFA|DE-FOA)-\d/i,
  );
});

test("the frozen E2E catalog exercises current, forecasted, archived, index, facet, and expansion paths", () => {
  const context = {};
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(querySource, context);
  vm.runInContext(fixtureSource, context);
  const catalog = context.GRANT_CATALOG;
  assert.equal(catalog.record_count, 1000);
  assert.deepEqual(
    { ...catalog.status_counts },
    { posted: 9, forecasted: 1, archived: 990 },
  );
  assert.ok(Object.keys(catalog.search_index.postings).length > 0);
  assert.deepEqual(
    Object.keys(catalog.facets).sort(),
    ["agency", "discipline", "eligibility", "funding_instrument", "source", "source_type", "topic"],
  );
  const ids = new Set(catalog.opportunities.map(record => record.opportunity_id));
  for (const id of [
    "363616",
    "fixture-hydrogen-catalysis",
    "fixture-forecasted-catalysis",
    "fixture-electrochemical-conversion",
  ]) {
    assert.ok(ids.has(id), `missing frozen E2E invariant record ${id}`);
  }
});
