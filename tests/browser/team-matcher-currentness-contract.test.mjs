import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [querySource, matcherSource, teamPage] = await Promise.all([
  readFile(new URL("assets/search-query.js", root), "utf8"),
  readFile(new URL("assets/team-matcher.js", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
]);
const context = { globalThis: {} };
vm.runInNewContext(querySource, context);
vm.runInNewContext(matcherSource, context);
const query = context.globalThis.FUNDING_SEARCH_QUERY;
const matcher = context.globalThis.FUNDING_TEAM_MATCHER;
const now = new Date("2026-08-29T12:00:00.000Z");

function parent(overrides = {}) {
  return {
    opportunity_id: overrides.opportunity_id || "parent",
    title: "Quantum sensing and microfluidic transport",
    description: "Research in quantum sensing and microfluidic transport systems.",
    status: "posted",
    posted_date: "2026-08-01",
    close_date: "2026-08-29",
    ...overrides,
  };
}

function profile(name, term) {
  return { name, key_terms: [term], domains: [] };
}

test("one immutable clock enforces close, rolling, forecasted, archived, and stale-undated currentness", () => {
  assert.equal(matcher.recordIsCurrent(parent({ close_date: "2026-08-29" }), now), true);
  assert.equal(matcher.recordIsCurrent(parent({ close_date: "2026-08-28" }), now), false);
  assert.equal(matcher.recordIsCurrent(parent({ close_date: "", rolling: true, posted_date: "2010-01-01" }), now), true);
  assert.equal(matcher.recordIsCurrent(parent({ status: "forecasted", close_date: "" }), now), true);
  assert.equal(matcher.recordIsCurrent(parent({ status: "archived", close_date: "" }), now), false);
  assert.equal(matcher.recordIsCurrent(parent({ close_date: "", posted_date: "2020-08-26" }), now), false);
  assert.equal(matcher.recordIsCurrent(parent({ status: "draft", close_date: "" }), now), false);
  assert.equal(matcher.recordIsCurrent(parent({ title: "Request for Information: Quantum research" }), now), false);
});

test("current runtime catalog membership is authoritative before any Team Match result", () => {
  const records = [
    parent({ opportunity_id: "open", close_date: "2026-08-29" }),
    parent({ opportunity_id: "expired", close_date: "2026-08-28" }),
    parent({ opportunity_id: "archived", status: "archived", close_date: "" }),
    parent({ opportunity_id: "stale", close_date: "", posted_date: "2010-01-01" }),
  ];
  const engine = matcher.create({ opportunities: records }, {}, query, { now, catalogRole: "parent" });
  assert.deepEqual(Array.from(engine.records, item => item.id), ["open"]);
  const results = engine.matchTeam([
    profile("Researcher A", "quantum sensing"),
    profile("Researcher B", "microfluidic transport"),
  ]).results;
  assert.deepEqual(Array.from(results, item => item.id), ["open"]);
});

test("publication-eligible child topics retain full-team evidence without sibling or unpublished leakage", () => {
  const children = [
    {
      subtopic_id: "child-shared",
      opportunity_id: "child-shared",
      parent_id: "parent-open",
      title: "Joint quantum sensing and microfluidic transport topic",
      summary: "Research in quantum sensing and microfluidic transport.",
      description: "Research in quantum sensing and microfluidic transport.",
      publication_state: "publishable",
      child_type: "subject",
    },
    {
      subtopic_id: "child-sibling",
      opportunity_id: "child-sibling",
      parent_id: "parent-open",
      title: "Unrelated quantum sensing sibling",
      summary: "Research in quantum sensing only.",
      description: "Research in quantum sensing only.",
      publication_state: "publishable",
      child_type: "subject",
    },
    {
      subtopic_id: "child-unpublished",
      opportunity_id: "child-unpublished",
      parent_id: "parent-open",
      title: "Quantum sensing and microfluidic transport draft",
      summary: "Research in quantum sensing and microfluidic transport.",
      description: "Research in quantum sensing and microfluidic transport.",
      publication_state: "excluded",
      child_type: "subject",
    },
  ];
  const engine = matcher.create({ opportunities: children }, {}, query, { now, catalogRole: "child" });
  const allHajim = engine.matchTeam([
    profile("Reviewed Hajim A", "quantum sensing"),
    profile("Reviewed Hajim B", "microfluidic transport"),
  ]).results;
  const mixed = engine.matchTeam([
    profile("Reviewed Hajim A", "quantum sensing"),
    { name: "External collaborator", keywords: ["microfluidic transport"], domains: [] },
  ]).results;
  assert.deepEqual(Array.from(allHajim, item => item.id), ["child-shared"]);
  assert.deepEqual(Array.from(mixed, item => item.id), ["child-shared"]);
  assert.equal(engine.records.some(item => item.id === "child-unpublished"), false);
});

test("adding a researcher only narrows the on-demand result intersection", () => {
  const records = [
    parent({ opportunity_id: "ab", description: "Quantum sensing and microfluidic transport research." }),
    parent({ opportunity_id: "abc", description: "Quantum sensing, microfluidic transport, and laser diagnostics research." }),
  ];
  const engine = matcher.create({ opportunities: records }, {}, query, { now, catalogRole: "parent" });
  const two = engine.matchTeam([
    profile("A", "quantum sensing"),
    profile("B", "microfluidic transport"),
  ]).results.map(item => item.id);
  const three = engine.matchTeam([
    profile("A", "quantum sensing"),
    profile("B", "microfluidic transport"),
    profile("C", "laser diagnostics"),
  ]).results.map(item => item.id);
  assert.ok(three.every(id => two.includes(id)));
  assert.ok(three.length <= two.length);
});

test("parent rollup accepts only children of runtime-current parents and keeps attributable child evidence", () => {
  assert.match(teamPage, /currentParentIds = new Set\(MATCH_ENGINE\.records/);
  assert.match(teamPage, /childOutcome\.results\.filter[\s\S]*?currentParentIds\.has/);
  assert.match(teamPage, /!currentParentIds\.has\(String\(row\.id\)\)/);
  assert.match(teamPage, /topicMatches: row\.childDroveMatch/);
  assert.match(teamPage, /fits: \(evidence && evidence\.fits\) \|\| \[\]/);
});
