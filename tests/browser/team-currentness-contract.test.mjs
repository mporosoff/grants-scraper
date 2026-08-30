import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const FIXED_NOW = new Date("2026-08-30T00:00:00.000Z");
const [matcherSource, retrievalSource, teamPage, releaseSource] = await Promise.all([
  readFile(new URL("../../assets/team-matcher.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-retrieval.js", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../data/search-v2-release.json", import.meta.url), "utf8"),
]);

function loadApis() {
  const context = { globalThis: {} };
  vm.runInNewContext(retrievalSource, context);
  vm.runInNewContext(matcherSource, context);
  return {
    matcher: context.globalThis.FUNDING_TEAM_MATCHER,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
  };
}

function record(id, overrides = {}) {
  return {
    opportunity_id: id,
    status: "posted",
    title: "Catalysis and carbon conversion research",
    description: "Heterogeneous catalysis and carbon dioxide conversion.",
    source_first_seen_date: "2026-08-29",
    ...overrides,
  };
}

function buildSharedSource() {
  const start = teamPage.indexOf("  function buildShared(members) {");
  const end = teamPage.indexOf("  function matchesQuery(e, q) {", start);
  assert.ok(start >= 0 && end > start, "expected the existing Team Match rollup function");
  return teamPage.slice(start, end);
}

test("Team Match currentness uses posted age only for undated non-rolling opportunities", () => {
  const { matcher } = loadApis();
  const catalog = { opportunities: [
    record("recent-undated", { posted_date: "2024-08-30" }),
    record("obsolete-2018", { posted_date: "2018-06-01" }),
    record("obsolete-2015", { posted_date: "2015-03-01" }),
    record("old-rolling", { posted_date: "2015-03-01", rolling: true }),
    record("missing-posted-date"),
    record("invalid-posted-date", { posted_date: "not-a-date" }),
    record("future-close", { posted_date: "2015-03-01", close_date: "2026-12-31" }),
    record("past-close", { posted_date: "2026-08-01", close_date: "2026-08-28" }),
    record("past-archive", { posted_date: "2026-08-01", archive_date: "2026-08-30" }),
    ...["archived", "closed", "cancelled", "canceled", "withdrawn", "expired"]
      .map(status => record(`status-${status}`, { posted_date: "2026-08-29", status })),
  ] };

  const engine = matcher.create(catalog, {}, null, { now: FIXED_NOW });
  const ids = new Set(engine.records.map(item => item.id));

  for (const id of [
    "recent-undated",
    "old-rolling",
    "missing-posted-date",
    "invalid-posted-date",
    "future-close",
  ]) assert.equal(ids.has(id), true, id);
  for (const id of [
    "obsolete-2018",
    "obsolete-2015",
    "past-close",
    "past-archive",
    "status-archived",
    "status-closed",
    "status-cancelled",
    "status-canceled",
    "status-withdrawn",
    "status-expired",
  ]) assert.equal(ids.has(id), false, id);
});

test("child evidence can help only runtime-current parents and final rows stay eligible", () => {
  const { retrieval } = loadApis();
  const observedChildIds = [];
  const guardedRetrieval = {
    rollupRankedRecords(options) {
      observedChildIds.push(...options.childRows.map(row => row.id));
      const rolled = retrieval.rollupRankedRecords(options);
      return {
        ...rolled,
        rows: [...rolled.rows, {
          id: "202",
          parent: null,
          parentNormalized: 0,
          childNormalized: 1,
          bestChild: null,
          children: [],
          childDroveMatch: false,
          relevance: 1,
        }],
      };
    },
  };
  const parentResults = [
    {
      id: "101", title: "Current parent", relevanceScore: .2, recencyBoost: 1,
      fits: [{ name: "Parent evidence" }], themeHits: [],
    },
    {
      id: "303", title: "Second current parent", relevanceScore: 1, recencyBoost: 1,
      fits: [{ name: "Second parent evidence" }], themeHits: [],
    },
  ];
  const childResults = [
    {
      id: "topic-current", relevanceScore: .8, record: { parent_id: 101 },
      fits: [{ name: "Current child evidence" }], themeHits: [{ label: "Catalysis" }],
    },
    {
      id: "topic-expired", relevanceScore: 5, record: { parent_id: 202 },
      fits: [{ name: "Expired child evidence" }], themeHits: [{ label: "Stale" }],
    },
  ];
  const context = {
    MATCH_ENGINE: {
      records: [{ id: 101 }, { id: "303" }],
      buildThemes() { return []; },
      matchTeam() { return { themes: [], results: parentResults }; },
    },
    CHILD_MATCH_ENGINE: {
      matchTeam() { return { themes: [], results: childResults }; },
    },
    CHILD_CATALOG: {},
    RETRIEVAL_API: guardedRetrieval,
    byId: {
      "101": { opportunity_id: "101", title: "Current parent", agency: "DOE" },
      "202": { opportunity_id: "202", title: "Archived parent", agency: "DOE", status: "archived" },
      "303": { opportunity_id: "303", title: "Second current parent", agency: "NSF" },
    },
    selected: [{ name: "One" }, { name: "Two" }],
    profiles: [{ name: "One" }, { name: "Two" }],
    themeState: {},
    lastHybridProfiles: [],
    lastHybridThemes: [],
    memberProfile(member) { return member; },
    renderThemes() {},
    liveEntry(result) { return { d: { id: result.id }, result }; },
  };
  vm.createContext(context);
  vm.runInContext(`${buildSharedSource()}\nthis.output = buildShared(profiles);`, context);

  assert.deepEqual(observedChildIds, ["topic-current"]);
  assert.deepEqual(Array.from(context.output, entry => entry.d.id), ["101", "303"]);
  assert.ok(context.output.every(entry => new Set(["101", "303"]).has(String(entry.d.id))));
  const childDriven = context.output.find(entry => entry.d.id === "101");
  assert.equal(childDriven.result.fits[0].name, "Current child evidence");
  assert.deepEqual(Array.from(childDriven.result.topicMatches, row => row.id), ["topic-current"]);
});

test("Team Match cache and release identities cover the changed page", () => {
  const release = JSON.parse(releaseSource);
  const teamPageHash = createHash("sha256").update(teamPage).digest("hex");

  assert.match(teamPage, /assets\/team-matcher\.js\?v=team-currentness-20260830/);
  assert.equal(release.source_hashes["team_match.html"], teamPageHash);
});
